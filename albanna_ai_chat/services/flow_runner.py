"""The flow runner — several tool calls, one transaction.

``core/flow_plan.py`` plans; this module runs. A flow is entered when the
model calls a tool whose spec carries a ``flow`` — ``admit_patient`` is the
reference case — and what this module guarantees is the sentence the manifest
makes to the reader: *if any step fails the ones before it are undone, so a
half-finished admission is never left behind.*

The transaction has three rules, and each is the failure mode of the naïve
version:

1. **Every step passes every gate.** A step is run through the same
   ``_run_tool`` a single call takes — the same argument validation, the same
   authority checks, the same backend. A flow is not a bypass; if it were,
   the second tool a model called through it would be the unaudited one.
2. **Compensation runs in reverse.** Steps that completed are undone from the
   last one back, each through its own tool's declared ``undo_with`` — the
   same mechanism a single-step write declares. The *flow's* compensation
   names what undoes the whole; the *steps'* compensations name what undoes
   each. The runner uses the steps', because they are per-call and cannot
   drift from what actually ran.
3. **A failed undo is reported, never hidden.** If an undo call itself
   fails, the result says so plainly: what was done, what was undone, and
   what the operator must clean up by hand. A compensation that quietly
   gives up is worse than no compensation, because it teaches everyone the
   transaction is safe when it is not.

Approval happens *before* this module is reached: the flow tool is a write
(``mutating``), so ``_run_tools`` parks the turn on the reader first, and a
flow that the reader approved runs to completion — including its
compensation, which needs no further approval because it only removes what
this flow itself created.
"""

from __future__ import annotations

import frappe

from albanna_ai_chat.core.flow import FlowSpec
from albanna_ai_chat.core.flow_plan import (
    flow_summary,
    parse_output,
    placeholder_problems,
    step_arguments,
    undo_arguments,
)
from albanna_ai_chat.core.port import Principal, ToolResult
from albanna_ai_chat.core.tools import ToolSpec


def run_flow(
    spec: ToolSpec,
    arguments: dict,
    principal: Principal,
    conversation: str,
    *,
    registry=None,
    run_single=None,
) -> ToolResult:
    """Run *spec*'s flow as one transaction, and account for every step.

    @param spec: the flow tool's spec — ``spec.flow`` must be a ``FlowSpec``
    @param arguments: the model's arguments, already schema-validated
    @param principal: who is asking; every step runs as this principal
    @param conversation: the thread the transcript lines go to
    @param registry: the tool registry to resolve steps against; the live
        one by default. Injectable because a test needs to pin the surface.
    @param run_single: the callable one step runs through — the turn loop's
        ``_run_tool`` by default, which is what makes every step pass every
        gate a single call passes. Injectable for the same reason.
    @returns: the flow's own result — success with a summary, or failure
        with the summary plus the undo account
    """
    flow: FlowSpec = spec.flow

    problems = placeholder_problems(spec, arguments)
    if problems:
        return ToolResult.failure(
            "; ".join(problems),
            error="invalid_flow",
        )

    from albanna_ai_chat.services.extensions import live_registry
    from albanna_ai_chat.services.turn_loop import _run_tool

    registry = registry if registry is not None else live_registry()
    run_one = run_single if run_single is not None else _run_tool
    outputs: dict[int, dict] = {}
    steps: list[tuple[str, bool, str]] = []
    completed: list[tuple[int, ToolSpec, dict]] = []

    for index, step in enumerate(flow.steps):
        step_spec = registry.get(step.tool)
        if step_spec is None:
            # The validator refuses a flow whose steps name unknown tools at
            # install time; a tool *disabled* since is the case that reaches
            # here, and it fails before anything is created.
            return _abort(
                flow,
                steps,
                completed,
                registry,
                principal,
                conversation,
                run_one,
                f"step {step.tool!r} is not available",
                error="tool_unavailable",
            )

        concrete, problem = step_arguments(step, arguments, outputs)
        if problem:
            return _abort(
                flow,
                steps,
                completed,
                registry,
                principal,
                conversation,
                run_one,
                problem,
                error="wiring_failed",
            )

        # An `into` naming a parameter the step's tool never declared is
        # caught here rather than as the step's own schema refusal — same
        # outcome (the flow stops, completed steps are undone), a sentence
        # that names the manifest's mistake instead of the model's.
        declared = set((step_spec.parameters or {}).get("properties") or {})
        if step.into and step.into not in declared:
            return _abort(
                flow,
                steps,
                completed,
                registry,
                principal,
                conversation,
                run_one,
                (
                    f"step {step.tool!r} wires its input into {step.into!r}, "
                    f"which is not a parameter of {step.tool!r}"
                ),
                error="invalid_flow",
            )

        result = run_one(step_spec, concrete, principal, conversation)
        step_output = parse_output(result.content)
        outputs[index] = step_output

        if not result.ok:
            steps.append((step.tool, False, result.content or result.error))
            return _abort(
                flow,
                steps,
                completed,
                registry,
                principal,
                conversation,
                run_one,
                f"step {step.tool!r} failed: {result.content or result.error}",
                error=result.error or "step_failed",
            )

        steps.append((step.tool, True, _step_note(step_spec, step_output)))
        completed.append((index, step_spec, step_output))

    # Every step ran. The flow's own answer carries each step's output, so
    # the model can keep citing the names it created without re-reading.
    import json as _json

    return ToolResult.success(
        _json.dumps(
            {
                "flow": flow.name,
                "steps": {flow.steps[i].tool: outputs[i] for i in outputs},
            },
            default=str,
        ),
        summary=f"Completed {len(completed)} steps of {flow.name}.",
    )


def _step_note(spec: ToolSpec, output: dict) -> str:
    """The short note a completed step contributes to the summary."""
    name = output.get("name") if isinstance(output, dict) else None
    return f"created {name}" if name else ""


def _abort(
    flow: FlowSpec,
    steps: list[tuple[str, bool, str]],
    completed: list[tuple[int, ToolSpec, dict]],
    registry,
    principal: Principal,
    conversation: str,
    run_one,
    reason: str,
    error: str,
) -> ToolResult:
    """Undo what completed, in reverse, and return the account.

    This is the compensation, and it is the part the reader is trusting: a
    flow that fails must not leave its own leavings behind. What it can undo
    it undoes; what it cannot it says so, with the reason, so the operator
    is never left guessing what exists.
    """
    from albanna_ai_chat.services.turn_loop import _run_tool

    undone: list[str] = []
    failed_undo: list[str] = []

    for _index, step_spec, output in reversed(completed):
        compensation = step_spec.compensation
        if compensation is None or compensation.mechanism != "reverse":
            # A step with no declared undo: not silently skipped — named.
            failed_undo.append(
                f"{step_spec.name} was created but declares no undo; "
                "remove it manually if it is not wanted"
            )
            continue

        undo_spec = registry.get(compensation.undo_with[0]) if compensation.undo_with else None
        if undo_spec is None:
            failed_undo.append(
                f"{step_spec.name}'s undo tool "
                f"{compensation.undo_with[0] if compensation.undo_with else '?'} "
                "is not available"
            )
            continue

        undo_args, problem = undo_arguments(undo_spec, output)
        if problem:
            failed_undo.append(f"{step_spec.name}: {problem}")
            continue

        undo_result = run_one(undo_spec, undo_args, principal, conversation)
        if undo_result.ok:
            undone.append(undo_spec.name)
        else:
            failed_undo.append(
                f"{undo_spec.name} failed: {undo_result.content or undo_result.error}"
            )

    summary = flow_summary(
        flow.name,
        steps + [(f"undo: {tool}", True, "") for tool in undone],
    )
    # The reason the flow stopped is part of the account — a summary that
    # lists the steps but not why the flow stopped makes the reader infer.
    summary += f"\n  stopped: {reason}"
    if failed_undo:
        summary += "\n  NOT UNDONE:"
        summary += "".join(f"\n    {line}" for line in failed_undo)

    try:
        frappe.logger("flow_runner").log(
            {
                "flow": flow.name,
                "error": error,
                "undone": undone,
                "failed_undo": failed_undo,
                "conversation": conversation,
            }
        )
    except Exception:  # noqa: BLE001 — an audit line that cannot be written
        # must not turn a half-finished transaction into an exception; the
        # account in the result is the durable record either way.
        pass
    return ToolResult.failure(summary, error=error)
