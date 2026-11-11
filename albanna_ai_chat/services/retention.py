"""Retention — chat logs are an audit trail, not a business record.

They are pruned by age so the table does not grow without bound.  Conversations
themselves are kept until the reader deletes them: a conversation is the
reader's own history, and a log row is the app's bookkeeping.

The distinction matters because getting it wrong in either direction is
expensive.  Pruning conversations deletes something a person wanted to keep;
never pruning logs grows a table nobody is watching until the disk notices.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime


def prune_chat_logs() -> int:
    """Delete chat log rows older than the configured retention.

    @returns: how many rows were deleted, so the scheduler's log says what
        happened rather than only that something ran.
    """
    settings = frappe.get_single("AI Chat Settings")
    days = settings.retention_days or 90
    cutoff = add_days(now_datetime(), -days)

    names = frappe.get_all(
        "AI Chat Log",
        filters={"creation": ["<", cutoff]},
        pluck="name",
        limit_page_length=0,
    )
    for name in names:
        frappe.delete_doc("AI Chat Log", name, ignore_permissions=True, force=True)

    if names:
        frappe.db.commit()
    return len(names)
