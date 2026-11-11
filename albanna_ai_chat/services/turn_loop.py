"""The turn loop — advancing a turn as far as it can go, then parking it.

This is the Frappe-coupled half of the runtime.  The *rules* about what a turn
does live in :mod:`albanna_ai_chat.chat.turn`, which is Frappe-free and tested
without a site; this module applies them to rows, calls a provider, runs tools,
and parks the result where the poll can find it.

Why it is resumable, and why that is not optional
-------------------------------------------------
A turn *waits*.  It waits for a tool, for the reader's approval of a write, for
the reader's answer to a question — and while it waits, the worker that started
it must be free to do something else.  A turn modelled as nested function calls
cannot survive that.

So :func:`advance` is idempotent and re-entrant: it loads the turn's state from
the conversation, moves it as far as it can, and writes the state back.  A turn
parked on the reader is picked up by the next call — from the reader's answer,
from an approval, or from a poll that finds the work already done.  Nothing is
held in memory between calls, which is what lets a turn survive a worker
restart.

The one seam
------------
The provider.  Everything else here is specified by the contract; the model
call is the one thing this core does not implement, and
:class:`~albanna_ai_chat.core.provider.NullProvider` refuses honestly rather
than letting a turn die with a stack trace.  A site with no provider configured
gets a sentence an operator can act on.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from albanna_ai_chat.chat.message import Message, Role, ToolCall
from albanna_ai_chat.chat.turn import (
    Action,
    Turn,
    TurnEvent,
    TurnState,
)
from albanna_ai_chat.core.file_tools import CORE_TOOLS
from albanna_ai_chat.core.port import Principal, ToolContext, ToolResult
from albanna_ai_chat.core.provider import NullProvider, ProviderResponse
from albanna_ai_chat.core.toolset import visible_tools
from albanna_ai_chat.core.tools import ToolSpec, validate_arguments
from albanna_ai_chat.services.extensions import live_registry
from albanna_ai_chat.services.reach import reach_for

#: How a turn's phase is reported to the poll.
#:
#: The transport settles on ``ok`` and ``error``; everything else means "keep
#: waiting".  A stopped turn is ``ok`` because the reader asked for it — a stop
#: is not a failure, and reporting it as one teaches the reader that pressing
#: Stop breaks things.
_POLL_STATUS = {
    TurnState.RUNNING: "running",
    TurnState.AWAITING_TOOL: "running",
    TurnState.AWAITING_APPROVAL: "awaiting_approval",
    TurnState.AWAITING_ANSWER: "awaiting_answer",
    TurnState.DONE: "ok",
    TurnState.FAILED: "error",
    TurnState.STOPPED: "ok",
}


# --------------------------------------------------------------------------
# Serialisation — a turn is state, and state has to survive the worker.
# --------------------------------------------------------------------------


def _call_to_json(call: ToolCall) -> dict:
    return {"id": call.id, "name": call.name, "arguments": call.arguments}


def _call_from_json(data: dict) -> ToolCall:
    return ToolCall(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        arguments=dict(data.get("arguments") or {}),
    )


def save_turn(turn: Turn) -> None:
    """Write a turn's state onto its conversation.

    The whole state, not just the phase: a turn that cannot be resumed cannot
    be recovered, and a turn parked on the reader is exactly the one that has
    to be resumed later.
    """
    payload = {
        "state": turn.state.value,
        "provider_calls": turn.provider_calls,
        "pending_calls": [_call_to_json(c) for c in turn.pending_calls],
        "awaiting_approval_for": (
            _call_to_json(turn.awaiting_approval_for) if turn.awaiting_approval_for else None
        ),
        "pending_question": turn.pending_question,
        "error": turn.error,
    }
    frappe.db.set_value(
        "AI Chat Conversation",
        turn.conversation,
        {
            "status": turn.state.value,
            "turn_snapshot": json.dumps(payload, default=str),
        },
        update_modified=False,
    )


def load_turn(conversation: str) -> Turn:
    """Rebuild a turn from its conversation.

    A conversation with no snapshot is a conversation with no turn running,
    which is a legitimate state and not an error — it is what a reader sees
    when they open a thread whose turns have all finished.
    """
    snapshot = frappe.db.get_value("AI Chat Conversation", conversation, "turn_snapshot")
    if not snapshot:
        return Turn(conversation=conversation)
    try:
        data = json.loads(snapshot)
    except (json.JSONDecodeError, TypeError):
        return Turn(conversation=conversation)

    turn = Turn(conversation=conversation)
    turn.provider_calls = int(data.get("provider_calls") or 0)
    turn.pending_calls = tuple(_call_from_json(c) for c in data.get("pending_calls") or [])
    approval = data.get("awaiting_approval_for")
    turn.awaiting_approval_for = _call_from_json(approval) if approval else None
    turn.pending_question = dict(data.get("pending_question") or {})
    turn.error = str(data.get("error") or "")
    try:
        turn.state = TurnState(str(data.get("state") or TurnState.IDLE.value))
    except ValueError:
        turn.state = TurnState.IDLE
    return turn


# --------------------------------------------------------------------------
# The conversation's messages, as the provider sees them.
# --------------------------------------------------------------------------


def load_messages(conversation: str) -> list[Message]:
    """Every message in a thread, in order, as canonical ``Message`` objects."""
    rows = frappe.get_all(
        "AI Chat Message",
        filters={"conversation": conversation},
        fields=["role", "content", "tool_name", "tool_call_id", "source"],
        order_by="creation asc",
        limit_page_length=0,
    )
    messages: list[Message] = []
    for row in rows:
        role = str(row.get("role") or "")
        try:
            parsed = Role(role)
        except ValueError:
            continue  # a role the runtime does not recognise is skipped, not fatal
        messages.append(
            Message(
                role=parsed,
                content=str(row.get("content") or ""),
                tool_name=str(row.get("tool_name") or ""),
                tool_call_id=str(row.get("tool_call_id") or ""),
                source=str(row.get("source") or ""),
            )
        )
    return messages


def persist_message(conversation: str, message: Message) -> None:
    """Write one message, and let the conversation's derived fields follow."""
    doc = frappe.get_doc(
        {
            "doctype": "AI Chat Message",
            "conversation": conversation,
            "role": message.role.value,
            "content": message.content,
            "tool_name": message.tool_name,
            "tool_call_id": message.tool_call_id,
            "source": message.source,
        }
    )
    doc.insert(ignore_permissions=True)


# --------------------------------------------------------------------------
# The tool surface one turn is offered.
# --------------------------------------------------------------------------


def visible_tools_for(user: str) -> list[ToolSpec]:
    """The tools *user* is offered: live extensions, narrowed by reach.

    Two filters, in this order and for different reasons.  Activation decides
    which extensions exist at all; reach decides which of their writes this
    caller may make.  An extension cannot opt out of the second, because the
    extension does not own this function.
    """
    registry = live_registry()
    reach = reach_for(user)
    try:
        settings = frappe.get_single("AI Chat Settings")
        disabled = list(settings.disabled_tool_names())
    except Exception:  # noqa: BLE001 — no settings, nothing disabled
        disabled = []
    return visible_tools(registry, reach, disabled).enabled()


def _backend():
    """The tool backend.  One implementation today, behind the port."""
    from albanna_ai_chat.tools.files import FileToolBackend

    return FileToolBackend()


def _provider():
    """The configured provider, or an honest refusal.

    A site with no provider configured is a site where every turn would
    otherwise fail with a stack trace the reader cannot act on.
    """
    try:
        settings = frappe.get_single("AI Chat Settings")
        provider_name = (settings.default_provider or "").strip()
        if not provider_name:
            return NullProvider()
    except Exception:  # noqa: BLE001
        return NullProvider()
    # No provider implementation ships in this layer yet, so a configured name
    # still refuses — but it refuses naming what is missing, which is the
    # difference between a sentence an operator can act on and a 500.
    return NullProvider(
        f"Provider {provider_name!r} is configured but no implementation is "
        "installed for it yet."
    )


# --------------------------------------------------------------------------
# Running one tool.
# --------------------------------------------------------------------------


def _run_tool(
    spec: ToolSpec,
    arguments: dict[str, Any],
    principal: Principal,
    conversation: str,
) -> ToolResult:
    """Validate, then run, one tool call.

    Validation happens *here* and not in the backend, because a malformed
    argument payload is a contract violation and the contract is the core's to
    enforce.  The backend's job is to run a tool it was handed correctly, not
    to defend itself against a model that misread the schema.
    """
    problem = validate_arguments(spec, arguments)
    if problem:
        return ToolResult.failure(problem, error="invalid_arguments")

    context = ToolContext(
        principal=principal,
        site=frappe.local.site,
        conversation=conversation,
    )
    backend = _backend()
    if not backend.handles(spec.name):
        return ToolResult.failure(
            f"Tool {spec.name!r} is declared but no backend can run it.",
            error="no_backend",
        )
    return backend.call(spec, arguments, context)


# --------------------------------------------------------------------------
# The driver.
# --------------------------------------------------------------------------


def advance(conversation: str) -> dict:
    """Move a turn as far as it can go, then park it.

    Idempotent and re-entrant: it reads the turn's state, acts, and writes the
    state back.  A turn parked on the reader is picked up by the next call.

    @param conversation: the thread's name
    @returns: what the poll should report
    """
    turn = load_turn(conversation)
    if not turn.is_live:
        return _report(turn)

    action = turn.next_action()

    if action is Action.CALL_PROVIDER:
        _call_provider(turn, conversation)
    elif action is Action.RUN_TOOLS:
        _run_tools(turn, conversation)
    # WAIT_FOR_READER, FINISH and FAIL need no work here: the turn is parked
    # on the reader, or it is over.

    save_turn(turn)
    return _report(turn)


def _call_provider(turn: Turn, conversation: str) -> None:
    """One provider round-trip, and whatever it implies."""
    guard = turn.guard()
    if guard:
        turn.error = guard
        turn.apply(TurnEvent.ERROR)
        return

    turn.record_provider_call()
    messages = load_messages(conversation)
    user = frappe.db.get_value("AI Chat Conversation", conversation, "user") or frappe.session.user
    tools = visible_tools_for(user)

    response = _provider().complete(messages, tools)

    if not response.ok:
        turn.error = response.error
        turn.apply(TurnEvent.ERROR)
        return

    # The assistant's turn is persisted either way: a turn that called a tool
    # still has a transcript that reads as a sentence rather than a gap.
    persist_message(
        conversation,
        Message.assistant(content=response.text, tool_calls=response.tool_calls),
    )

    if response.wants_tools:
        try:
            turn.request_calls(response.tool_calls)
        except Exception as e:  # noqa: BLE001 — too many calls is a refusal, not a crash
            turn.error = str(e)
            turn.apply(TurnEvent.ERROR)
        return

    turn.apply(TurnEvent.PROVIDER_TEXT)


def _run_tools(turn: Turn, conversation: str) -> None:
    """Run the pending tool calls, parking on the first write that needs approval."""
    user = frappe.db.get_value("AI Chat Conversation", conversation, "user") or frappe.session.user
    principal = Principal(user=user, roles=tuple(frappe.get_roles(user)))
    registry = live_registry()

    while turn.pending_calls:
        call = turn.pending_calls[0]
        spec = registry.get(call.name)

        if spec is None:
            persist_message(
                conversation,
                Message.tool_result(call, f"Tool {call.name!r} is not available."),
            )
            turn.pending_calls = turn.pending_calls[1:]
            continue

        # A write parks the turn on the reader.  The remaining calls stay in
        # pending_calls, so resuming continues exactly where it stopped rather
        # than re-running what already ran.
        if spec.mutating and turn.awaiting_approval_for is None:
            turn.awaiting_approval_for = call
            turn.apply(TurnEvent.APPROVAL_REQUIRED)
            return

        result = _run_tool(spec, call.arguments, principal, conversation)
        persist_message(conversation, Message.tool_result(call, result.content))
        turn.pending_calls = turn.pending_calls[1:]
        turn.awaiting_approval_for = None

    turn.clear_calls()
    turn.apply(TurnEvent.TOOLS_DONE)


def _report(turn: Turn) -> dict:
    """What the poll reports for this turn."""
    status = _POLL_STATUS.get(turn.state, "running")
    payload: dict[str, Any] = {"status": status}

    if turn.state is TurnState.AWAITING_APPROVAL and turn.awaiting_approval_for:
        call = turn.awaiting_approval_for
        payload["pending"] = {
            "request_id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }
    if turn.state is TurnState.AWAITING_ANSWER and turn.pending_question:
        payload["question"] = turn.pending_question
    if turn.state is TurnState.DONE:
        payload["answer"] = _last_assistant_text(turn.conversation)
    if turn.state is TurnState.FAILED:
        payload["error"] = turn.error or "The turn failed."
    if turn.state is TurnState.STOPPED:
        payload["stopped"] = True
        payload["answer"] = _last_assistant_text(turn.conversation)

    return payload


def _last_assistant_text(conversation: str) -> str:
    """The last thing the assistant said, for a finished turn."""
    row = frappe.get_all(
        "AI Chat Message",
        filters={"conversation": conversation, "role": Role.ASSISTANT.value},
        fields=["content"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return str(row[0].get("content") or "") if row else ""
