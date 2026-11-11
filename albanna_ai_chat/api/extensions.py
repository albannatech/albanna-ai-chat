"""The Settings surface's API — what the operator can see and do.

Whitelisted, System Manager only.  Every method answers one of the questions
the Settings screen has to answer: what is installed, what is activated, is it
compatible, and what should I do next.

What this API deliberately does *not* do
----------------------------------------
Install an app.  ``bench install-app`` is a bench operation — it writes to
``sites/apps.txt``, runs patches, migrates the schema — and no doctype method
can do it.  :func:`activate` and :func:`deactivate` change the *activation*
list, which is the only thing a Settings screen legitimately owns.

That distinction is the whole reason
:mod:`albanna_ai_chat.core.extension_state` exists as a pure module: the rules
about what is live are decided somewhere a test can reach, not in a template.
An app that is not installed is reported as such, with the bench command that
will install it, rather than being offered a button that cannot work.

Activation is also refused for an *incompatible* extension.  That check
belongs here rather than at call time, because an extension whose declared
core version range excludes the running core is a visible settings row — not a
runtime surprise on the first tool call.
"""

from __future__ import annotations

import frappe
from frappe import _

from albanna_ai_chat.core.extension_state import (
    INSTALLED_INCOMPATIBLE,
    NOT_INSTALLED,
)


def _require_system_manager() -> None:
    """Only an administrator may change the extension surface.

    A check here rather than in a template, because a whitelisted method that
    trusts its caller is a whitelisted method that grants whatever the caller
    asks for.
    """
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only a System Manager may manage extensions."), frappe.PermissionError)


def _settings():
    return frappe.get_single("AI Chat Settings")


@frappe.whitelist()
def get_report() -> dict:
    """Everything the Settings screen renders, in one call.

    Two lists, because they answer different questions: ``extensions`` is the
    state of every app the site knows about, and ``tools`` is what each
    *activated* one actually contributed.  An operator reading the first is
    deciding what to switch on; an operator reading the second is checking
    what the assistant can already do.
    """
    _require_system_manager()
    from albanna_ai_chat.services.extensions import (
        extension_states,
        load_registry,
    )

    states = extension_states()
    registry = live_registry()

    return {
        "core_version": _core_version(),
        "extensions": [
            {
                "app": s.name,
                "state": s.state,
                "action": s.action,
                "command": s.command,
                "summary": s.summary,
                "installed": s.installed,
                "activated": s.activated,
                "compatible": s.compatible,
                "installed_version": s.installed_version,
                "requires_core": s.requires_core,
                "reason": s.reason,
            }
            for s in states
        ],
        "tools": [
            {
                "name": spec.name,
                "tier": spec.tier,
                "source": spec.source,
                "description": spec.description,
                "is_flow": spec.is_flow,
            }
            for spec in registry.all()
        ],
    }


def _core_version() -> str:
    from albanna_ai_chat.services.extensions import core_version

    return core_version()


@frappe.whitelist()
def get_tools() -> list[dict]:
    """The live tool surface — what a turn is actually offered.

    Useful for support: it answers *"what can the assistant do on this site
    right now"* without reading the code, and it reflects activation, so an
    installed-but-inactive extension's tools are absent rather than merely
    greyed out.
    """
    _require_system_manager()
    from albanna_ai_chat.services.extensions import live_registry

    registry = live_registry()
    return [
        {
            "name": spec.name,
            "tier": spec.tier,
            "source": spec.source,
            "description": spec.description,
            "is_flow": spec.is_flow,
        }
        for spec in registry.all()
    ]


@frappe.whitelist()
def activate(app: str) -> dict:
    """Switch an extension on.

    Refuses when the app is not installed, and when it is installed but
    incompatible with the running core.  Both refusals name the command that
    fixes them, because a Settings screen that says only "no" leaves the
    operator with nowhere to go.
    """
    _require_system_manager()
    app = str(app or "").strip()
    if not app:
        frappe.throw(_("An app name is required."), title=_("Missing app name"))

    from albanna_ai_chat.services.extensions import extension_states

    status = next((s for s in extension_states() if s.name == app), None)
    if status is None or status.state == NOT_INSTALLED:
        frappe.throw(
            _("{0} is not installed on this site. Install it first with: {1}").format(
                app,
                f"bench get-app https://github.com/albannatech/{app}.git "
                f"&& bench --site {frappe.local.site} install-app {app}",
            ),
            title=_("Not installed"),
        )
    if status.state == INSTALLED_INCOMPATIBLE:
        frappe.throw(
            _("{0} needs core {1} but {2} is running. Upgrade the core or the "
              "extension, then activate.").format(
                app, status.requires_core or "(unstated)", status.core_version or "(unknown)"
            ),
            title=_("Incompatible"),
        )

    settings = _settings()
    enabled = list(settings.enabled_extension_names())
    if app not in enabled:
        enabled.append(app)
        settings.enabled_extensions = frappe.as_json(enabled)
        settings.save(ignore_permissions=True)

    return {"app": app, "activated": True, "enabled": enabled}


@frappe.whitelist()
def deactivate(app: str) -> dict:
    """Switch an extension off.

    Always allowed, even for an app that is not installed — deactivating
    something that was uninstalled is how the operator cleans up the stale
    entry, and refusing would leave them no way to do it.
    """
    _require_system_manager()
    app = str(app or "").strip()
    if not app:
        frappe.throw(_("An app name is required."), title=_("Missing app name"))

    settings = _settings()
    enabled = [a for a in settings.enabled_extension_names() if a != app]
    settings.enabled_extensions = frappe.as_json(enabled)
    settings.save(ignore_permissions=True)

    return {"app": app, "activated": False, "enabled": enabled}


@frappe.whitelist()
def reload_extensions() -> dict:
    """Re-validate every extension and report what loaded.

    The escape hatch for the case nothing else can know about: an extension
    whose module changed on disk.  It re-runs the full validation, so a
    contract violation surfaces here rather than on the next chat turn.
    """
    _require_system_manager()
    from albanna_ai_chat.services.extensions import live_registry

    registry = live_registry()
    return {
        "loaded": {
            source: [spec.name for spec in registry.from_source(source)]
            for source in registry.sources()
            if source != "core"
        },
        "tool_count": len(registry),
    }
