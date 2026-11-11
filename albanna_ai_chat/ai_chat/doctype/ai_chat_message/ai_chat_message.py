"""AI Chat Message — one line of a conversation.

Thin by design.  The shape of a message is decided in
:mod:`albanna_ai_chat.chat.message`, which is Frappe-free; this class only
persists it and enforces the one rule the pure layer cannot: a ``tool``
message must name the call it answers, because a result with no address is a
result the model cannot match.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from albanna_ai_chat.chat.message import Role


def role_options() -> tuple[str, ...]:
    """The doctype's role options, in the order the JSON declares them."""
    meta = frappe.get_meta("AI Chat Message")
    field = meta.get_field("role")
    return tuple((field.options or "").split("\n"))


def assert_role_matches_message_roles() -> None:
    """The doctype's Select options and ``Role`` are one fact."""
    options = {o for o in role_options() if o}
    roles = {r.value for r in Role}
    missing = roles - options
    extra = options - roles
    if missing or extra:
        raise AssertionError(
            "AI Chat Message.role and Role have drifted: "
            f"missing from the doctype={sorted(missing)}, "
            f"not a Role={sorted(extra)}"
        )


class AIChatMessage(Document):
    """One message, owned by the reader whose conversation it is in."""

    def validate(self) -> None:
        if self.role == Role.TOOL.value and not (self.tool_call_id or self.tool_name):
            frappe.throw(
                "A tool result must name the call it answers — a result with "
                "no address is a result the model cannot match.",
                title="Unaddressable tool result",
            )
