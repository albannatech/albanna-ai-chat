"""Discovering, validating and absorbing the extensions installed on a site.

This is the Frappe half of the seam.  ``core/validate.py`` says what a valid
extension looks like; this module finds the ones that exist on *this* site and
hands them over.

Two kinds of failure, treated differently on purpose
----------------------------------------------------
A **contract violation** is a developer bug: an unclassified tool, a
collision, a SQL-shaped parameter.  It raises, and it raises at load time,
because an extension that half-loads reads to a user as *"the tool sometimes
works"* — the hardest bug there is to reproduce.

An **ImportError** is an environment problem: the app is installed but its
dependencies are not.  That is logged loudly to stderr and the extension is
skipped, so one broken optional dependency cannot take the core surface down
with it.  The distinction is the whole of the failure design, and it is the
same one ``erpnext-mcp`` arrived at independently.

Per site, not per venv
----------------------
``frappe.get_hooks`` resolves from the apps installed on the current site.
That is what makes an extension's tools exist here and nowhere else, and it
is why this module never touches ``importlib.metadata``.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import replace

import frappe

from albanna_ai_chat.core.file_tools import CORE_TOOLS
from albanna_ai_chat.core.tools import ToolRegistry
from albanna_ai_chat.core.validate import ContractViolation, absorb, load_module

#: The hook an extension app implements.  Duplicated from ``hooks.py`` because
#: ``hooks.py`` may import Frappe and ``core/`` may not; a test asserts the two
#: strings agree so the duplication cannot drift.
EXTENSION_HOOK = "frappe_mcp_tools"


def installed_apps() -> list[str]:
    """The apps installed on this site, in Frappe's own order."""
    try:
        return list(frappe.get_installed_apps())
    except Exception:  # noqa: BLE001 — no site, no apps
        return []


def discover() -> dict[str, str]:
    """Every extension hook declared on this site, as ``app -> dotted path``.

    An app that is not installed contributes nothing, which is the scoping
    property the whole design rests on.
    """
    hooks = frappe.get_hooks(EXTENSION_HOOK, app_name=None) or {}
    if isinstance(hooks, dict):
        # Frappe returns {app: value} when app_name is None.
        return {str(app): str(value) for app, value in hooks.items() if value}
    # A single value is a list of one.
    values = [str(v) for v in hooks if v]
    return {value: value for value in values}


def load_registry(registry: ToolRegistry | None = None) -> ToolRegistry:
    """The core tools plus every valid extension's, absorbed atomically.

    @param registry: the registry to extend.  Defaults to the core's own.
    @returns: a new registry; the input is never mutated
    @raises ContractViolation: naming every problem in the offending extension
    """
    base = registry if registry is not None else CORE_TOOLS
    current = base

    for app, target in sorted(discover().items()):
        module = _import_target(target)
        if module is None:
            continue
        # load_module validates atomically, tags every spec with the module's
        # own name (which is what makes an uninstall exact), and reports
        # whether the module loaded at all.
        specs, loaded = load_module(module, known_tools=set(current.names()))
        if not loaded:
            continue
        # Provenance is the *app* name, not the module's.  A manifest at
        # ``healthcare_mcp.tools.manifest`` would otherwise tag its tools
        # ``"manifest"``, and an uninstall keys on the app — removing
        # ``healthcare_mcp`` must remove its tools and only its tools.
        tagged = [replace(spec, source=app) for spec in specs]
        current = absorb(tagged, current)

    return current


def _import_target(target: str):
    """Import an extension's manifest module, or ``None`` if it cannot be had.

    A missing dependency is an environment problem and is reported to stderr
    rather than raised, so the core surface stays available.
    """
    try:
        return importlib.import_module(target)
    except Exception as exc:  # noqa: BLE001 — any import failure is skippable
        print(
            f"[albanna-ai-chat] extension {target!r} failed to import — skipped: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None


def extension_report(registry: ToolRegistry) -> list[dict]:
    """What each installed extension contributed, for the Settings surface.

    Read-only.  It answers *which* app added *which* tools, which is the
    question an operator asks before deactivating one.
    """
    report: list[dict] = []
    for source in registry.sources():
        if source == "core":
            continue
        specs = registry.from_source(source)
        report.append(
            {
                "app": source,
                "installed": source in installed_apps(),
                "tools": [spec.name for spec in specs],
                "writes": [spec.name for spec in specs if spec.mutating],
            }
        )
    return report
