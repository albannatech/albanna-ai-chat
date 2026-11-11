"""AI Chat Conversation — one thread, and the turn that is running in it.

The controller is deliberately thin.  Everything that decides *what a turn
does* lives in :mod:`albanna_ai_chat.chat.turn`, which is Frappe-free and
testable without a site; this class only persists and restores that state.

The one thing it does own is ``status``.  The doctype's Select options mirror
``TurnState``, and a derived field that is computed in two places disagrees
with itself — so the mapping lives here, in one function, and a test asserts
the two sets are equal in both directions.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.model.naming import get_default_naming

from albanna_ai_chat.chat.turn import TurnState


def status_options() -> tuple[str, ...]:
    """The doctype's status options, in the order the JSON declares them."""
    meta = frappe.get_meta("AI Chat Conversation")
    field = meta.get_field("status")
    return tuple((field.options or "").split("\n"))


def assert_status_matches_turn_states() -> None:
    """The doctype's Select options and ``TurnState`` are one fact.

    Called from the test suite rather than from a hook, because a drift here
    is a developer bug and it should fail the build rather than surface as a
    conversation stuck in a state the runtime does not recognise.
    """
    options = {o for o in status_options() if o}
    states = {s.value for s in TurnState}
    missing = states - options
    extra = options - states
    if missing or extra:
        raise AssertionError(
            "AI Chat Conversation.status and TurnState have drifted: "
            f"missing from the doctype={sorted(missing)}, "
            f"not a TurnState={sorted(extra)}"
        )


class AIChatConversation(Document):
    """One conversation, owned by the reader who started it."""

    def before_insert(self) -> None:
        if not self.title:
            self.title = "New conversation"

    def validate(self) -> None:
        if not self.status:
            self.status = TurnState.IDLE.value
