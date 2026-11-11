"""The chat API — the seven endpoints the transport declares.

Every path here is named in ``public/js/lib/wire.mjs``, which is the one place
the frontend's assumptions about the server live.  When the two disagree, a test
fails rather than the panel silently doing nothing.

What this API is careful about
------------------------------
**The reader is the caller.**  Every endpoint runs as the session user, and
every read is narrowed to that user's own threads by the permission hooks in
``hooks.py``.  A whitelisted method that trusted its arguments would let any
reader name any conversation.

**A turn is addressed by its conversation.**  One turn runs in a thread at a
time, so the stream id *is* the conversation name.  That is not a shortcut — it
is what makes ``get_turn`` answerable without a second registry, and what makes
a turn survive a worker restart: the address is a row, not a handle in some
process's memory.

**Stopping is a client action.**  ``stop_turn`` marks the turn stopped and
drops the wait.  The worker keeps running and the answer is still parked, so the
turn is not lost — it is merely no longer waited for.  A server-side cancel
would have to reach into the worker to stop a model call already in flight, and
the cost of that is a whole cancellation channel between the browser and the
queue.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from albanna_ai_chat.chat.message import Message
from albanna_ai_chat.chat.turn import Turn, TurnEvent, TurnState
from albanna_ai_chat.install import CHAT_USER_ROLE
from albanna_ai_chat.services.turn_loop import advance, load_turn, persist_message, save_turn

#: The role that may chat at all.
CHAT_ROLE = CHAT_USER_ROLE


def _may_chat(user: str | None = None) -> bool:
    """Whether this reader may chat.

    A reader who may not chat gets no widget at all — not a disabled one.  A
    widget that renders and then refuses is a widget that teaches the reader
    the app is broken.
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    return CHAT_ROLE in frappe.get_roles(user)


@frappe.whitelist()
def access() -> dict:
    """Whether the widget should exist for this reader.

    Called by the launcher before it puts anything on the page, and the answer
    is published for the form button to share — see
    ``public/js/lib/access.mjs``, which exists because the two bundles used to
    answer this question separately.
    """
    allowed = _may_chat()
    return {
        "visible": allowed,
        "chat_access": allowed,
        "app": frappe.scrub("Albanna AI Chat"),
    }


@frappe.whitelist()
def conversations(limit: int = 50) -> list[dict]:
    """The threads this reader may see, newest first.

    Narrowed by the permission hooks, so a reader who is not the owner sees
    nothing of a thread — including its existence.
    """
    rows = frappe.get_all(
        "AI Chat Conversation",
        fields=["name", "title", "status", "last_activity", "message_count", "pinned"],
        order_by="pinned desc, last_activity desc",
        limit_page_length=max(1, min(int(limit or 50), 200)),
    )
    return rows


@frappe.whitelist()
def start_turn(
    question: str,
    attachments: str = "[]",
    attachment_urls: str = "[]",
    conversation_id: str = "",
    page: str = "",
    page_context: str = "",
) -> dict:
    """Start a turn, and return its address.

    The turn itself runs in a background job: Frappe's request model cannot
    stream a response, so the worker parks the finished answer and the poll
    reads it back.  What this returns is the address to poll.
    """
    if not _may_chat():
        frappe.throw(_("You do not have access to the chat."), frappe.PermissionError)

    question = str(question or "").strip()
    if not question:
        frappe.throw(_("A question is required."), title=_("Nothing asked"))

    conversation = str(conversation_id or "").strip()
    if conversation:
        # A thread the reader does not own is a thread they may not continue.
        owner = frappe.db.get_value("AI Chat Conversation", conversation, "user")
        if owner and owner != frappe.session.user:
            frappe.throw(_("That conversation is not yours."), frappe.PermissionError)
    else:
        conversation = _new_conversation(page)

    persist_message(conversation, Message.user(question))

    turn = Turn().start(conversation)
    save_turn(turn)

    frappe.enqueue(
        "albanna_ai_chat.services.turn_loop.advance",
        queue="short",
        conversation=conversation,
        job_name=f"albanna-ai-chat-turn:{conversation}",
    )

    return {
        "status": "queued",
        "stream_id": conversation,
        "conversation_id": conversation,
    }


def _new_conversation(page: str = "") -> str:
    """A fresh thread, owned by the reader who asked."""
    doc = frappe.get_doc(
        {
            "doctype": "AI Chat Conversation",
            "title": "New conversation",
            "user": frappe.session.user,
            "status": TurnState.RUNNING.value,
            "page": page or "",
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


@frappe.whitelist()
def get_turn(stream_id: str, conversation: str = "") -> dict:
    """Read a turn back — the poll.

    The delivery guarantee.  A client whose socket died still gets its answer,
    because this does not care about the socket.
    """
    name = str(stream_id or conversation or "").strip()
    if not name:
        frappe.throw(_("A turn is required."), title=_("Nothing to read"))

    owner = frappe.db.get_value("AI Chat Conversation", name, "user")
    if owner and owner != frappe.session.user and frappe.session.user != "Administrator":
        frappe.throw(_("That conversation is not yours."), frappe.PermissionError)

    turn = load_turn(name)
    from albanna_ai_chat.services.turn_loop import _report

    return _report(turn)


@frappe.whitelist()
def stop_turn(stream_id: str) -> dict:
    """Stop waiting for a turn.

    The work finishes on the server and the answer is still parked, so the turn
    is not lost — it is merely no longer waited for.  What arrived is kept: it
    is the truth so far.
    """
    name = str(stream_id or "").strip()
    if not name:
        frappe.throw(_("A turn is required."), title=_("Nothing to stop"))

    turn = load_turn(name)
    if turn.is_live and not turn.is_waiting:
        turn.apply(TurnEvent.READER_STOPPED)
        save_turn(turn)

    return {"status": "stopped", "stream_id": name}


@frappe.whitelist()
def answer_question(stream_id: str, answer: str = "") -> dict:
    """Answer a question the assistant asked, and resume the turn."""
    name = str(stream_id or "").strip()
    if not name:
        frappe.throw(_("A turn is required."), title=_("Nothing to answer"))

    turn = load_turn(name)
    if turn.state is not TurnState.AWAITING_ANSWER:
        return {"status": "not_waiting", "stream_id": name}

    persist_message(name, Message.user(str(answer or "")))
    turn.pending_question = {}
    turn.apply(TurnEvent.READER_ANSWERED)
    save_turn(turn)

    frappe.enqueue(
        "albanna_ai_chat.services.turn_loop.advance",
        queue="short",
        conversation=name,
        job_name=f"albanna-ai-chat-turn:{name}",
    )
    return {"status": "resumed", "stream_id": name}


@frappe.whitelist()
def resolve_approval(stream_id: str, request_id: str = "", approved: bool = False) -> dict:
    """Approve or refuse a write that is waiting, and resume the turn.

    A refusal is fed back to the model as the tool's result, so the turn
    continues rather than dying — a refused write is information, not a failure.
    """
    name = str(stream_id or "").strip()
    if not name:
        frappe.throw(_("A turn is required."), title=_("Nothing to resolve"))

    turn = load_turn(name)
    if turn.state is not TurnState.AWAITING_APPROVAL:
        return {"status": "not_waiting", "stream_id": name}

    call = turn.awaiting_approval_for
    if call is None:
        return {"status": "not_waiting", "stream_id": name}

    # A decision about a different request than the one waiting is a stale
    # button, and acting on it would approve a write the reader never saw.
    if request_id and call.id and request_id != call.id:
        return {"status": "stale", "stream_id": name}

    granted = _truthy(approved)
    persist_message(
        name,
        Message.user("Approved." if granted else "Refused."),
    )

    if granted:
        turn.apply(TurnEvent.APPROVAL_GRANTED)
    else:
        # The refusal becomes the tool's result, so the model learns the write
        # did not happen and can say so rather than retrying.
        if turn.pending_calls:
            refused = turn.pending_calls[0]
            persist_message(
                name,
                Message.tool_result(refused, "The reader refused this change."),
            )
            turn.pending_calls = turn.pending_calls[1:]
        turn.awaiting_approval_for = None
        turn.apply(TurnEvent.APPROVAL_REFUSED)

    save_turn(turn)

    frappe.enqueue(
        "albanna_ai_chat.services.turn_loop.advance",
        queue="short",
        conversation=name,
        job_name=f"albanna-ai-chat-turn:{name}",
    )
    return {"status": "resumed", "stream_id": name, "approved": granted}


def _truthy(value: Any) -> bool:
    """Frappe hands whitelisted arguments over as strings.

    ``"false"`` is a string that means false, and ``bool("false")`` is True —
    which would approve every write a reader refused.  This is the whole reason
    the helper exists.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")
