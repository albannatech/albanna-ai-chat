"""The extension validator — the guard that makes an open surface safe.

An extension mechanism is a promise that *anyone* can add tools.  This module
is what makes that promise keepable.  It is deliberately modelled on
``erpnext-mcp``'s ``extensions.register_tools``: validate the whole contract,
and absorb nothing when any part of it fails.

Why atomic
----------
A partially-absorbed extension is worse than a rejected one.  Half the tools
are live, half are not, the model sees a surface that does not match what the
operator installed, and the failure presents as *"the tool sometimes works"*
— which is the hardest class of bug to reproduce and the easiest to blame on
the framework.  So: every check runs, every problem is collected, and the
module is absorbed only when the list is empty.

Why loud
--------
A broken *contract* is a developer bug and crashes at startup on purpose.  A
broken *import* is an environment problem — a missing optional dependency —
and only earns a loud warning plus a skip, so the core surface stays
available.  ``erpnext-mcp`` draws exactly this line and it is the right one:
the first is a mistake that must be fixed before ship, the second is a
machine that must keep running.

The rules, and where each one comes from
----------------------------------------
tier classified .............. an unclassified tool disables every gate that
                             keys on tier, silently
no SQL parameter ............ a raw SELECT bypasses Frappe's permission
                             engine entirely (``albanna`` ADR 0005's exclusion)
no filesystem path .......... a path parameter is a host-level read/write
                             (``albanna``'s ``read_file`` takes a URL or a
                             File record *name*, never a path)
no core-name collision ...... an extension shadowing ``read_file`` replaces a
                             core tool with something nobody audited
flow >= 2 steps ............. a one-step flow is a tool wearing a costume
flow steps resolve .......... a step naming an unregistered tool half-runs
                             before anyone notices
write declares compensation . every destructive action says how it is undone,
                             or why it cannot (``erpnext-mcp``'s
                             ``tool-compensation.json`` rule, test-enforced)
"""

from __future__ import annotations

import sys
import types
from typing import Any

from albanna_ai_chat.core.flow import (
    FlowSpec,
    validate_flow_steps_resolve,
)
from albanna_ai_chat.core.tools import (
    CORE_TOOL_NAMES,
    FORBIDDEN_PARAM_NAMES,
    SQL_PARAM_NAMES,
    TIER_ORDER,
    ToolRegistry,
    ToolSpec,
)

#: The attribute an extension module exposes its tools through.
TOOLS_ATTR = "TOOLS"

#: The attribute an extension module classifies its tools through.
TIERS_ATTR = "TIERS"

#: The most tools one extension may declare.  A ceiling exists so a typo that
#: generates tools in a loop cannot exhaust the manifest.
MAX_TOOLS = 256


class ContractViolation(RuntimeError):
    """Raised when an extension's contract is broken.

    Subclasses ``RuntimeError`` so existing ``except RuntimeError`` handlers
    around extension loading keep working, while still being catchable on its
    own by anything that wants to distinguish a contract bug from a genuine
    runtime failure.
    """


def _param_names(parameters: Any) -> set[str]:
    """The declared parameter names of a tool's schema, lowercased."""
    if not isinstance(parameters, dict):
        return set()
    props = parameters.get("properties")
    if not isinstance(props, dict):
        return set()
    return {str(name).lower() for name in props}


def validate_module(
    module: Any,
    known_tools: set[str] | frozenset[str] | None = None,
) -> list[ToolSpec]:
    """Validate one extension module and return its specs.

    The module must expose ``TOOLS`` — a list of :class:`ToolSpec` — and
    ``TIERS`` — a dict mapping every tool name to a tier in
    :data:`~albanna_ai_chat.core.tools.TIER_ORDER`.

    On any violation a :class:`ContractViolation` naming *every* problem is
    raised and nothing is returned.  On success the validated specs are
    returned for the caller to absorb.

    @param module: the imported extension module
    @param known_tools: tool names already registered, for collision checks.
        Defaults to the core tool names.
    @returns: the validated specs, in declaration order
    @raises ContractViolation: naming every problem found
    """
    known = set(known_tools) if known_tools is not None else set(CORE_TOOL_NAMES)
    name = getattr(module, "__name__", repr(module))
    problems: list[str] = []

    tools = getattr(module, TOOLS_ATTR, None)
    if not isinstance(tools, list):
        raise ContractViolation(
            f"extension module {name!r} must expose {TOOLS_ATTR} as a list of ToolSpec"
        )
    if len(tools) > MAX_TOOLS:
        raise ContractViolation(
            f"extension module {name!r} declares {len(tools)} tools; "
            f"the ceiling is {MAX_TOOLS}"
        )

    tiers = getattr(module, TIERS_ATTR, None)
    if not isinstance(tiers, dict):
        raise ContractViolation(
            f"extension module {name!r} must expose {TIERS_ATTR} as a dict of "
            "tool name -> tier"
        )

    # Provenance: every tool this module declares is tagged with the module's
    # own name unless it already carries one, so an uninstall can remove
    # exactly this extension's tools.
    source = str(name).split(".")[-1]

    seen: set[str] = set()
    valid: list[ToolSpec] = []

    for index, spec in enumerate(tools):
        if not isinstance(spec, ToolSpec):
            problems.append(f"{TOOLS_ATTR}[{index}] must be a ToolSpec, got {type(spec).__name__}")
            continue

        label = spec.name or f"{TOOLS_ATTR}[{index}]"

        # --- identity -------------------------------------------------
        if not spec.name or not spec.name.isidentifier():
            problems.append(f"tool at {TOOLS_ATTR}[{index}] has no valid name")
            continue
        if spec.name in seen:
            problems.append(f"duplicate tool name in {TOOLS_ATTR}: {spec.name}")
        seen.add(spec.name)

        # --- collision -------------------------------------------------
        # An extension may not shadow a core tool, nor a tool another
        # extension has already registered.  Shadowing replaces an audited
        # tool with an unaudited one, under the same name, and nothing on
        # the surface says so.
        if spec.name in known:
            problems.append(
                f"tool {spec.name!r} collides with an already-registered tool — "
                "extensions must not shadow core or other extension tools"
            )

        # --- description ----------------------------------------------
        if not isinstance(spec.description, str) or not spec.description.strip():
            problems.append(f"tool {spec.name!r} has an empty description")

        # --- parameters -----------------------------------------------
        if not isinstance(spec.parameters, dict):
            problems.append(f"tool {spec.name!r} parameters must be a dict")
        else:
            if spec.parameters.get("type") != "object":
                problems.append(
                    f"tool {spec.name!r} parameters must declare \"type\": \"object\""
                )
            declared = _param_names(spec.parameters)

            sql_hits = sorted(declared & SQL_PARAM_NAMES)
            if sql_hits:
                problems.append(
                    f"tool {spec.name!r} declares SQL-shaped parameter(s) "
                    f"{', '.join(sql_hits)} — a raw query bypasses Frappe's "
                    "permission engine and is never a tool parameter"
                )

            path_hits = sorted(declared & FORBIDDEN_PARAM_NAMES)
            if path_hits:
                problems.append(
                    f"tool {spec.name!r} declares filesystem-path parameter(s) "
                    f"{', '.join(path_hits)} — file tools take a URL or a File "
                    "record name resolved through Frappe, never a server path"
                )

        # --- tier ------------------------------------------------------
        tier = tiers.get(spec.name)
        if tier is None:
            problems.append(
                f"tool {spec.name!r} has no tier — classify it in module {TIERS_ATTR}"
            )
        elif tier not in TIER_ORDER:
            problems.append(
                f"tool {spec.name!r} has unknown tier {tier!r} "
                f"(valid: {', '.join(TIER_ORDER)})"
            )
        elif tier != spec.tier:
            problems.append(
                f"tool {spec.name!r} is tier {spec.tier!r} on the spec but "
                f"{tier!r} in {TIERS_ATTR} — the two must agree"
            )

        # --- write tools must say how they are undone -------------------
        if spec.mutating and spec.flow is None:
            problems.append(
                f"write tool {spec.name!r} declares no flow — a mutating tool "
                "must carry a FlowSpec whose compensation states how it is undone"
            )

        # --- flow -------------------------------------------------------
        if spec.flow is not None:
            if not isinstance(spec.flow, FlowSpec):
                problems.append(
                    f"tool {spec.name!r} flow must be a FlowSpec, got "
                    f"{type(spec.flow).__name__}"
                )
            else:
                if spec.flow.name != spec.name:
                    problems.append(
                        f"tool {spec.name!r} carries flow named "
                        f"{spec.flow.name!r} — a flow's name must match its tool"
                    )
                problems.extend(spec.flow.problems())

        valid.append(spec)

    # --- flow steps must resolve against the whole declared set ----------
    # Checked after the loop so a step may name a tool declared later in the
    # same module — declaration order is not dependency order.
    declared = {spec.name for spec in valid}
    for spec in valid:
        if isinstance(spec.flow, FlowSpec):
            problems.extend(validate_flow_steps_resolve(spec.flow, declared | known))

    if problems:
        raise ContractViolation(
            f"Extension contract violation in module {name!r}: " + "; ".join(problems)
        )

    # Tag provenance last, so a module that fails validation leaves no trace.
    # An empty source inherits the module's own name; an explicit one (a core
    # tool saying "core") is believed.
    return [
        ToolSpec(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
            tier=spec.tier,
            required_roles=spec.required_roles,
            doctype_arg=spec.doctype_arg,
            write_permission=spec.write_permission,
            max_result_chars=spec.max_result_chars,
            enabled=spec.enabled,
            source=spec.source or source,
            flow=spec.flow,
        )
        for spec in valid
    ]


def load_module(module: Any, known_tools: set[str] | frozenset[str] | None = None):
    """Validate and absorb one module, distinguishing bug from environment.

    A :class:`ContractViolation` propagates — it is a developer mistake and
    must stop the boot.  An ``ImportError`` (or anything raised while
    *importing* the module, rather than validating it) is an environment
    problem: it earns a loud stderr line and the extension is skipped, so a
    missing optional dependency cannot take the core surface down with it.

    @returns: ``(specs, loaded)`` — the absorbed specs, and whether the
        module was loaded at all.
    """
    try:
        specs = validate_module(module, known_tools)
    except ContractViolation:
        raise
    except Exception as e:  # noqa: BLE001 — environment problem, skip loudly
        print(
            f"[albanna-ai-chat] extension "
            f"{getattr(module, '__name__', module)!r} failed to load — skipped: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        return [], False
    return specs, True


def absorb(specs: list[ToolSpec], registry: ToolRegistry) -> ToolRegistry:
    """Return a new registry with *specs* appended.

    A new registry rather than a mutation, so a failed absorption cannot
    leave a half-updated manifest behind for the next caller to read.
    """
    return ToolRegistry(list(registry.all()) + list(specs))
