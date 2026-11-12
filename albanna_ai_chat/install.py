"""Installation — making the app usable the moment it is installed.

The installer creates the Single settings row and the role the permission
hooks depend on, so the app works on first use instead of failing on a missing
document the first time somebody opens the widget.

``after_migrate`` re-runs the same work, and that is deliberate rather than
lazy: a site restored from a backup, or a bench migrated onto a new machine,
can arrive with the app's tables present and its settings row absent.  Both
functions are idempotent, so running them twice is free.
"""

from __future__ import annotations

import frappe

from albanna_ai_chat.ai_chat.doctype.ai_chat_settings.ai_chat_settings import (
    DEFAULT_CORE_PROMPT,
)

#: The role the permission hooks and the doctype permissions both depend on.
CHAT_USER_CORE_APP = "albanna_ai_chat"
ROLE = "Albanna Chat User"


def _ensure_role() -> None:
    """Create the chat role if it is absent.

    A role is not a permission — it is the *name* the permissions are written
    against.  Without it the doctype's ``if_owner`` rows grant nothing, and
    the failure is silent: the widget simply never appears.
    """
    if frappe.db.exists("Role", CHAT_USER_ROLE):
        return
    frappe.get_doc(
        {
            "doctype": "Role",
            "role_name": CHAT_USER_ROLE,
            "desk_access": 1,
        }
    ).insert(ignore_permissions=True)


def _ensure_settings() -> None:
    """Create the Single settings row with the core's default prompt."""
    if frappe.db.exists("AI Chat Settings", "AI Chat Settings"):
        return
    frappe.get_doc(
        {
            "doctype": "AI Chat Settings",
            "core_system_prompt": DEFAULT_CORE_PROMPT,
            "max_provider_calls": 12,
            "max_tool_calls_per_response": 8,
            "retention_days": 90,
            "enabled_extensions": "[]",
        }
    ).insert(ignore_permissions=True)


def after_install() -> None:
    _require_core()
    """Called by Frappe after the app is installed on a site."""
    _ensure_role()
    _ensure_settings()


def after_migrate() -> None:
    """Called by Frappe after every migrate.

    Idempotent, so a site that arrives with tables but no settings row is
    repaired by the next migrate rather than by a support ticket.
    """
    _require_core()
    _ensure_role()
    _ensure_settings()


def _require_core() -> None:
    """Refuse to install without the core, and say which app to install.

    A raised exception here fails the install, which is correct: an extension
    whose tools cannot be discovered is not an extension, it is a directory.
    """
    if CORE_APP in frappe.get_installed_apps():
        return
    frappe.throw(
        f"This extension requires the frappe-mcp core. Install it first: "
        f"bench get-app https://github.com/albannatech/albanna-ai-chat.git "
        f"&& bench --site {{site}} install-app {{CORE_APP}}",
        title="Missing required app",
    )
