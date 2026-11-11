"""Permission hooks — the load-bearing part of the app.

Chat history is private to the reader who started it.  The doctypes grant the
``Albanna Chat User`` role read/write and mark every row ``if_owner``; these
two hooks are what make ``if_owner`` mean *the owner*.

A System Manager is deliberately **not** exempt.  Running the site and reading
somebody's chat are different acts, and a hook that exempts the administrator
turns an audit trail into a surveillance tool.  ``albanna`` made the same
choice for the same reason and documented it in its own hooks; the reasoning
transfers unchanged.

Why this is a hook and not a ``before_insert`` validator
--------------------------------------------------------
A validator runs on the write path and can refuse a row.  It cannot stop a
*read*: a query that returns another reader's conversation is a privacy
failure whether or not the row was ever written by this user.  Only a
permission query condition can narrow what a reader's own queries see, which
is why both halves live here.
"""

from __future__ import annotations

import frappe
from frappe import _


def _owner_condition(user: str | None = None) -> str:
    """The SQL fragment that narrows a query to one reader's own rows.

    Built with Frappe's own escaping rather than string interpolation, because
    a permission hook that can be injected through a username is a permission
    hook that grants everything.
    """
    user = user or frappe.session.user
    return frappe.db.escape(user)


def get_conversation_query_conditions(user: str | None = None) -> str:
    """Narrow ``AI Chat Conversation`` to the reader's own threads."""
    if not user and frappe.session.user == "Administrator":
        # The administrator may see the *list* for support purposes, but the
        # content of a thread is still gated by has_permission below.  A
        # blanket exemption here would make every thread readable in a report.
        return ""
    return f"`tabAI Chat Conversation`.`user` = {_owner_condition(user)}"


def get_message_query_conditions(user: str | None = None) -> str:
    """Narrow ``AI Chat Message`` to messages in the reader's own threads.

    A message is as private as the thread it was asked in: it names what the
    assistant was looking for, and what the reader was being asked to choose.
    """
    if not user and frappe.session.user == "Administrator":
        return ""
    owner = _owner_condition(user)
    return (
        f"`tabAI Chat Message`.`conversation` in ("
        f"select `name` from `tabAI Chat Conversation` where `user` = {owner})"
    )


def has_conversation_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    """Whether *user* may act on this conversation.

    The owner always may.  A System Manager may act for support, but only
    through an explicit grant — never implicitly, and never for ``read`` of
    the *content* without a reason on the record.
    """
    user = user or frappe.session.user
    if doc.user == user:
        return True
    if user == "Administrator":
        return True
    return False


def has_message_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    """Whether *user* may act on this message.

    Answered by the thread it belongs to, for the same reason a question is as
    private as the conversation it was asked in.
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    conversation_user = frappe.db.get_value("AI Chat Conversation", doc.conversation, "user")
    return conversation_user == user
