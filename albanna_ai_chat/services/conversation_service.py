"""Conversation service — the derived fields, maintained in one place.

A conversation's ``last_activity`` and ``message_count`` are derived from its
messages.  A derived field computed in two places is a derived field that
disagrees with itself, so both are maintained here, on the event that makes
them change, and nowhere else.

This module is the Frappe-coupled half.  The *rules* about what a conversation
is live in :mod:`albanna_ai_chat.chat`, which is Frappe-free; this module only
applies them to rows.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def on_message_inserted(doc, method=None) -> None:
    """Maintain the conversation's derived fields after a message is inserted.

    Registered as an ``after_insert`` hook on ``AI Chat Message``.  It runs
    *after* the row exists, so the count it writes includes the message that
    triggered it — a count maintained ``before_insert`` is off by one for the
    rest of the conversation's life.
    """
    if not doc.conversation:
        return

    values = {
        "last_activity": now_datetime(),
        "message_count": frappe.db.count("AI Chat Message", {"conversation": doc.conversation}),
    }

    # The title is derived from the first *reader* message, and only while it
    # still holds its placeholder.  A title the reader has edited is theirs,
    # and overwriting it on the next message is the kind of small rudeness
    # that makes an assistant feel untrustworthy.
    if doc.role == "user":
        current = frappe.db.get_value("AI Chat Conversation", doc.conversation, "title")
        if not current or current == "New conversation":
            values["title"] = _derive_title(doc.content)

    frappe.db.set_value("AI Chat Conversation", doc.conversation, values, update_modified=False)


def _derive_title(content: str, limit: int = 60) -> str:
    """A conversation's title, from its first question.

    Truncated on a word boundary rather than mid-word, because a title that
    reads ``which sales orders are o`` is worse than a shorter one that reads
    ``which sales orders are open``.
    """
    text = " ".join((content or "").split())
    if len(text) <= limit:
        return text or "New conversation"
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(".,;:") + "…"
