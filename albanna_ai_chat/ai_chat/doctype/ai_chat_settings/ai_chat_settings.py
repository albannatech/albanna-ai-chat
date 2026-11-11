"""AI Chat Settings — the Single row that configures the core.

A Single doctype, so there is exactly one row and no question of which site's
settings are in force.  The installer creates it, so the app is usable the
moment it is installed rather than failing on a missing document the first
time somebody opens the widget.

The limits here mirror constants in the pure layer
(:data:`~albanna_ai_chat.chat.turn.MAX_PROVIDER_CALLS` and
:data:`~albanna_ai_chat.chat.turn.MAX_TOOL_CALLS_PER_RESPONSE`).  They are
mirrored rather than shared because the pure layer must stay importable
without a site, and a setting an operator can lower is a setting worth having
— but it may only ever *lower* the ceiling, never raise it past what the pure
layer considers safe.
"""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from albanna_ai_chat.chat.turn import (
    MAX_PROVIDER_CALLS,
    MAX_TOOL_CALLS_PER_RESPONSE,
)

DEFAULT_CORE_PROMPT = (
    "You are Albanna, an assistant living inside this site's Desk. "
    "You answer questions about the reader's own data and carry out the "
    "changes they ask for, using the tools you have been given.\n\n"
    "Rules that are not negotiable:\n"
    "- Act only on what the reader asked about. Never change a document they "
    "did not name, and never change a field they did not mention.\n"
    "- When a required value is missing, ask for it rather than inventing one.\n"
    "- When a tool refuses, say so and stop. Do not retry, and do not look "
    "for another way to do the same thing.\n"
    "- When you are not certain which document is meant, ask. A guess that "
    "changes the wrong record is worse than a question."
)


class AIChatSettings(Document):
    """The one settings row."""

    def validate(self) -> None:
        # A setting may lower a ceiling, never raise it.  An operator who
        # raises it past the pure layer's limit has not made the app more
        # capable; they have made it able to exhaust a context window.
        if self.max_provider_calls and self.max_provider_calls > MAX_PROVIDER_CALLS:
            frappe.throw(
                f"Max provider calls may not exceed {MAX_PROVIDER_CALLS}. "
                "A turn that needs more steps should be a flow.",
                title="Limit too high",
            )
        if (
            self.max_tool_calls_per_response
            and self.max_tool_calls_per_response > MAX_TOOL_CALLS_PER_RESPONSE
        ):
            frappe.throw(
                f"Max tool calls per response may not exceed "
                f"{MAX_TOOL_CALLS_PER_RESPONSE}. Running many writes before "
                "looking at any of them is how one bad turn becomes many.",
                title="Limit too high",
            )
        if self.enabled_extensions:
            self._validate_extensions_json()

    def _validate_extensions_json(self) -> None:
        """The extension list must be a JSON array of strings.

        A malformed list is not a cosmetic problem: it is read on every turn
        to decide which extensions are live, and a list that fails to parse
        silently activates nothing.
        """
        try:
            parsed = json.loads(self.enabled_extensions)
        except (json.JSONDecodeError, TypeError) as e:
            frappe.throw(
                f"Enabled extensions must be a JSON array of app names: {e}",
                title="Invalid extension list",
            )
            return
        if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
            frappe.throw(
                "Enabled extensions must be a JSON array of app names.",
                title="Invalid extension list",
            )

    def enabled_extension_names(self) -> tuple[str, ...]:
        """The activated extensions, as a tuple.  Empty when none or unparseable."""
        if not self.enabled_extensions:
            return ()
        try:
            parsed = json.loads(self.enabled_extensions)
        except (json.JSONDecodeError, TypeError):
            return ()
        if not isinstance(parsed, list):
            return ()
        return tuple(str(x) for x in parsed if isinstance(x, str))

    def disabled_tool_names(self) -> tuple[str, ...]:
        """The tool names the operator has hidden, deduplicated, in order.

        Delegates to the pure parser in :mod:`albanna_ai_chat.core.tools` so
        the rule is testable without a doctype, a site or a database.
        """
        from albanna_ai_chat.core.tools import parse_tool_names

        return parse_tool_names(self.disabled_tools)
