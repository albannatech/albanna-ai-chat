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

from albanna_ai_chat.core.extension_state import ExtensionStatus
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


def core_version() -> str:
    """The version of the core that is running.

    Read from the package rather than from a setting, because a setting can
    disagree with the code that is actually loaded — and version compatibility
    is exactly the question where that disagreement hurts.
    """
    try:
        from albanna_ai_chat import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001 — a package with no version is version ""
        return ""


def activated_apps() -> set[str]:
    """The apps the operator has switched on, from the settings row.

    Activation is a *settings* change and nothing else.  An app that is
    installed but absent from this list contributes no tools, and there is no
    second path by which its tools reach the model — which is the whole point
    of keeping activation out of the loader's discovery step.
    """
    try:
        settings = frappe.get_single("AI Chat Settings")
        return set(settings.enabled_extension_names())
    except Exception:  # noqa: BLE001 — a missing settings row means none are on
        return set()


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


def load_registry(
    registry: ToolRegistry | None = None,
    only_activated: bool = False,
) -> ToolRegistry:
    """The core tools plus every valid extension's, absorbed atomically.

    ``only_activated`` defaults to False, and that default is deliberate: this
    function answers *"what is installed and valid"*, which is the question
    the Settings surface asks when it reports on an extension before the
    operator has switched it on.  It is **not** the question a turn asks.

    A turn is offered :func:`live_registry`, which applies activation.  The
    two are separate functions rather than one with a flag because the safe
    path has to be the obvious one — a loader whose default silently includes
    unactivated extensions is a loader one careless call site away from
    exposing tools the operator never switched on.

    @param registry: the registry to extend.  Defaults to the core's own.
    @param only_activated: skip apps the operator has not switched on
    @returns: a new registry; the input is never mutated
    @raises ContractViolation: naming every problem in the offending extension
    """
    base = registry if registry is not None else CORE_TOOLS
    current = base
    activated = activated_apps()

    for app, target in sorted(discover().items()):
        if only_activated and app not in activated:
            continue
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


def live_registry(registry: ToolRegistry | None = None) -> ToolRegistry:
    """The surface a turn is offered: core plus *activated* extensions.

    This is the only loader the turn loop may call.  An app that is installed
    but not switched on in Settings contributes nothing, and there is no second
    path by which its tools reach the model — which is the whole point of
    keeping activation out of :func:`load_registry`'s default.
    """
    return load_registry(registry=registry, only_activated=True)


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


def _requires_core(target: str | None) -> str:
    """The core version range an extension declares it needs.

    Read from the extension's own manifest module, as ``REQUIRES_CORE``.  An
    extension that declares nothing is assumed to need the core it was built
    against — which is the core that is running, so the assumption is safe and
    it is stated in :mod:`albanna_ai_chat.core.extension_state` rather than
    hidden here.
    """
    if not target:
        return ""
    try:
        module = importlib.import_module(target)
    except Exception:  # noqa: BLE001 — an unreadable manifest declares nothing
        return ""
    return str(getattr(module, "REQUIRES_CORE", "") or "")


def _app_version(app: str) -> str:
    """The version of an installed app, or ``""`` when it cannot be read.

    Frappe apps carry ``__version__`` in their package ``__init__``.  A missing
    one is reported as empty rather than guessed, because a version that parses
    as ``0.0.0`` sorts as the oldest thing in the room and silently wins every
    "is an update available" question.
    """
    try:
        module = importlib.import_module(app)
    except Exception:  # noqa: BLE001 — not importable, so no version to report
        return ""
    return str(getattr(module, "__version__", "") or "")


def extension_states() -> list:
    """Every extension this site knows about, as the Settings surface sees it.

    The union of *declared* and *activated*, and deliberately not the union of
    everything installed.  A bench has ``frappe``, ``erpnext``, ``hrms`` and a
    dozen other apps on it that are not extensions and never will be; reporting
    them would bury the two rows an operator came to read.

    An app that is activated but declares nothing is still reported, because
    that usually means it was uninstalled without being deactivated — and the
    operator needs to see the stale entry in order to clear it.
    """
    installed = set(installed_apps())
    activated = activated_apps()
    discovered = discover()
    core = core_version()

    apps = (set(discovered) | activated) - {"albanna_ai_chat"}

    states = []
    for app in sorted(apps):
        states.append(
            ExtensionStatus(
                name=app,
                installed=app in installed,
                activated=app in activated,
                installed_version=_app_version(app),
                # No upstream registry is consulted, so "an update exists" is
                # never claimed.  A report that invents an available version
                # sends an operator to run a command that changes nothing.
                available_version="",
                requires_core=_requires_core(discovered.get(app)),
                core_version=core,
            )
        )
    return states
