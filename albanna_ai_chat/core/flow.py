"""Flows and compensation — the multi-step, transactional half of the contract.

A flow is *several tool calls with a transaction of its own*.  That sentence
is borrowed verbatim from ``albanna``'s manifest, where it appears as the
reason ``run_flow`` was deliberately left out: *"it is a good tool and the
wrong first one: its failure modes belong to a later release, once the
single-step write path has proven itself."*

This module is that later release, and it keeps the warning attached.

What a flow is
--------------
An ordered set of steps, each naming a tool and the arguments it receives,
with a declared compensation — what happens when step three of four fails.
A flow that cannot say how it is undone is not a transaction, it is a
sequence with a hope.

What a flow is not
------------------
* **Not universal.**  A tool is single-step by default.  It becomes a flow
  when the operation is genuinely multi-step and transactional —
  ``quotation_to_invoice`` spans documents and money; ``get_doctype_meta``
  never will be.  ``erpnext-mcp`` ships 451 tools and eleven flows, which is
  the ratio the reference actually chose.
* **Not a namespace.**  A flow with one step is a tool wearing a costume,
  and the validator refuses it.
* **Not a bypass.**  Every step is a tool, and every tool passes the same
  gates whether or not it is reached through a flow.

The compensation inventory
--------------------------
``erpnext-mcp`` maintains ``config/tool-compensation.json`` with a rule worth
copying exactly: *every destructive tool must declare how it is undone, or
why it cannot be*, and a test fails the build when the declaration is missing
or has drifted.  The mechanisms are a closed set:

``snapshot``  put the row(s) back from a ``snapshot_docs`` capture
``recreate``  re-create the object with another tool
``rename``    the action is a rename, so renaming back restores it
``reverse``   a counterpart tool performs the inverse operation
``none``      no supported undo — and this one *must* carry a reason

``none`` is the honest answer for an irreversible action, and it is allowed
precisely because it must be written down.  A mechanism of ``none`` with no
reason is a refusal, not a declaration.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

#: The closed set of compensation mechanisms.
MECHANISMS: tuple[str, ...] = ("snapshot", "recreate", "rename", "reverse", "none")

#: The fewest steps a flow may declare.  One step is a tool, not a flow.
MIN_FLOW_STEPS = 2

#: The most steps a flow may declare.  A flow longer than this is two flows
#: with a shared name, and it will be debugged as one thing.
MAX_FLOW_STEPS = 24


@dataclass(frozen=True)
class FlowStep:
    """One step of a flow.

    ``tool`` names a tool that must exist in the same registry — a step that
    names a tool nobody registered is a contract violation, caught at
    validation rather than at the moment the flow half-runs.

    ``arguments`` are the literal arguments for this step.  A step that needs
    the *output* of an earlier step declares that with ``from_step`` and
    ``from_field``, which is what makes a flow a pipeline rather than a
    script with constants in it.
    """

    tool: str
    arguments: dict = field(default_factory=dict)
    #: The index of an earlier step whose output this step consumes.
    from_step: int | None = None
    #: The field of that output to take.
    from_field: str = ""
    #: The argument of *this step's tool* that the wired output is injected
    #: into. Required in practice: a step tool's schema is closed
    #: (``additionalProperties: False``), so an argument the schema does not
    #: declare is a call the step's own validation refuses — the wiring has
    #: to land in a parameter the tool declared, or not land at all.
    into: str = ""
    #: When true, a failure of this step does not abort the flow — it is
    #: recorded and the flow continues.  Defaults to false because a step
    #: that may fail silently is a step nobody notices failing.
    optional: bool = False


@dataclass(frozen=True)
class CompensationSpec:
    """How a flow is undone when a step fails.

    ``mechanism`` is one of :data:`MECHANISMS`.  ``undo_with`` names the
    tools that perform the undo, and is required for every mechanism except
    ``none``.  ``reason`` is required for ``none`` and forbidden otherwise —
    an irreversible action must say why it is irreversible, and a reversible
    one must not hide behind prose.
    """

    mechanism: str
    undo_with: tuple[str, ...] = ()
    reason: str = ""

    def problems(self) -> list[str]:
        """Every way this declaration is incomplete.  Empty means valid."""
        issues: list[str] = []
        if self.mechanism not in MECHANISMS:
            issues.append(
                f"unknown compensation mechanism {self.mechanism!r} "
                f"(valid: {', '.join(MECHANISMS)})"
            )
            return issues
        if self.mechanism == "none":
            if not self.reason.strip():
                issues.append(
                    "mechanism 'none' requires a reason — an irreversible "
                    "action must say why it cannot be undone"
                )
            if self.undo_with:
                issues.append("mechanism 'none' must not declare undo_with")
        else:
            if not self.undo_with:
                issues.append(
                    f"mechanism {self.mechanism!r} requires undo_with naming "
                    "the tools that perform the undo"
                )
            if self.reason.strip():
                issues.append(
                    f"mechanism {self.mechanism!r} must not carry a reason — "
                    "only 'none' explains itself"
                )
        return issues


@dataclass(frozen=True)
class FlowSpec:
    """A declared multi-step flow.

    ``name`` matches the tool name it is attached to: a flow is not a
    separate callable, it is the *shape* of one tool.  That is what keeps the
    model's surface unchanged — the model sees one tool, and the runtime
    knows that tool is several calls with a transaction.
    """

    name: str
    steps: tuple[FlowStep, ...]
    compensation: CompensationSpec
    description: str = ""

    def problems(self) -> list[str]:
        """Every way this flow is invalid.  Empty means valid."""
        issues: list[str] = []
        if not self.name or not self.name.isidentifier():
            issues.append(f"flow name {self.name!r} is not a valid identifier")
        if len(self.steps) < MIN_FLOW_STEPS:
            issues.append(
                f"flow {self.name!r} declares {len(self.steps)} step(s); "
                f"the minimum is {MIN_FLOW_STEPS} — a one-step flow is a tool"
            )
        if len(self.steps) > MAX_FLOW_STEPS:
            issues.append(
                f"flow {self.name!r} declares {len(self.steps)} steps; "
                f"the maximum is {MAX_FLOW_STEPS} — split it"
            )
        seen: set[str] = set()
        for index, step in enumerate(self.steps):
            if not step.tool:
                issues.append(f"flow {self.name!r} step {index} names no tool")
            if step.tool in seen:
                issues.append(f"flow {self.name!r} repeats tool {step.tool!r}")
            seen.add(step.tool)
            if step.from_step is not None:
                if not 0 <= step.from_step < index:
                    issues.append(
                        f"flow {self.name!r} step {index} consumes output from "
                        f"step {step.from_step}, which is not an earlier step"
                    )
                if not step.from_field:
                    issues.append(
                        f"flow {self.name!r} step {index} declares from_step "
                        "without from_field"
                    )
                if not step.into:
                    issues.append(
                        f"flow {self.name!r} step {index} declares from_step "
                        "without into — the wired value has to land in an "
                        "argument the step's tool declares, and without "
                        "into it lands under the field's own name, which a "
                        "closed schema refuses"
                    )
        issues.extend(self.compensation.problems())
        return issues


def validate_flow_steps_resolve(flow: FlowSpec, known_tools: Iterable[str]) -> list[str]:
    """Check that every step of *flow* names a tool that exists.

    A step naming an unregistered tool is the failure that hurts most: the
    flow validates, installs, and then half-runs before anybody discovers the
    typo.  Catching it here costs nothing.
    """
    known = set(known_tools)
    return [
        f"flow {flow.name!r} step names unknown tool {step.tool!r}"
        for step in flow.steps
        if step.tool and step.tool not in known
    ]
