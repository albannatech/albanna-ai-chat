"""Tests for the flow runner — the transaction, and its compensation.

The runner is exercised through its injected seams (``registry`` and
``run_single``), so no test touches a backend, a network, or a site. What is
pinned down is the guarantee the manifest makes to the reader: *if any step
fails the ones before it are undone, so a half-finished admission is never
left behind* — and, when an undo itself fails, the account that says so
plainly rather than hiding it.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

# --------------------------------------------------------------------------
# The frappe binding.
#
# flow_runner binds `frappe` at import. On a host with no bench, a stub is
# installed first; on this host the real frappe may already be in
# sys.modules, and the runner's audit line is written under a try/except —
# an audit line that cannot be written must not turn a half-finished
# transaction into an exception.
# --------------------------------------------------------------------------

if "frappe" not in sys.modules:

    class _StubLogger:
        def log(self, *args, **kwargs):
            pass

    _stub = types.ModuleType("frappe")
    _stub.logger = lambda *a, **k: _StubLogger()
    sys.modules["frappe"] = _stub

from albanna_ai_chat.core.flow import CompensationSpec, FlowSpec, FlowStep
from albanna_ai_chat.core.port import Principal, ToolResult
from albanna_ai_chat.core.tools import ToolRegistry, ToolSpec, WRITE
from albanna_ai_chat.services.flow_runner import run_flow

PRINCIPAL = Principal(user="test@example.com", roles=())


def spec_for(
    name: str,
    parameters: dict,
    compensation: CompensationSpec | None = None,
    flow: FlowSpec | None = None,
) -> ToolSpec:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": parameters,
        "required": [],
    }
    return ToolSpec(
        name=name,
        description=f"The {name} tool.",
        parameters=schema,
        tier=WRITE,
        write_permission="create",
        compensation=compensation,
        flow=flow,
    )


# The healthcare-shaped flow: create the patient, wire the encounter to the
# patient the first step made, then assign the practitioner.
ADMIT_FLOW = FlowSpec(
    name="admit_patient",
    steps=(
        FlowStep(
            tool="create_patient",
            arguments={"patient_name": "{patient_name}"},
        ),
        FlowStep(
            tool="create_encounter",
            from_step=0,
            from_field="name",
            into="patient",
            arguments={"encounter_type": "{encounter_type}"},
        ),
        FlowStep(
            tool="assign_practitioner",
            from_step=1,
            from_field="name",
            into="encounter",
            arguments={"practitioner": "{practitioner}"},
        ),
    ),
    compensation=CompensationSpec(
        mechanism="reverse",
        undo_with=("cancel_encounter", "delete_patient"),
    ),
)

CREATE_PATIENT = spec_for(
    "create_patient",
    {"patient_name": {"type": "string"}},
    compensation=CompensationSpec(mechanism="reverse", undo_with=("delete_patient",)),
)
CREATE_ENCOUNTER = spec_for(
    "create_encounter",
    {"patient": {"type": "string"}, "encounter_type": {"type": "string"}},
    compensation=CompensationSpec(mechanism="reverse", undo_with=("cancel_encounter",)),
)
ASSIGN = spec_for(
    "assign_practitioner",
    {"encounter": {"type": "string"}, "practitioner": {"type": "string"}},
    compensation=CompensationSpec(mechanism="reverse", undo_with=("unassign_practitioner",)),
)
DELETE_PATIENT = spec_for("delete_patient", {"name": {"type": "string"}})
CANCEL_ENCOUNTER = spec_for("cancel_encounter", {"name": {"type": "string"}})
ADMIT = spec_for(
    "admit_patient",
    {"patient_name": {"type": "string"}, "practitioner": {"type": "string"}, "encounter_type": {"type": "string"}},
    flow=ADMIT_FLOW,
)

REGISTRY = ToolRegistry(
    [
        CREATE_PATIENT,
        CREATE_ENCOUNTER,
        ASSIGN,
        DELETE_PATIENT,
        CANCEL_ENCOUNTER,
        ADMIT,
    ]
)


class Harness:
    """The recorded executor — what ran, in what order, with what arguments."""

    def __init__(self, fail_at: str | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.fail_at = fail_at

    def run_single(self, spec: ToolSpec, arguments: dict, principal, conversation):
        self.calls.append((spec.name, dict(arguments)))
        if spec.name == self.fail_at:
            return ToolResult.failure(
                f"{spec.name} was refused by the site.",
                error="refused",
            )
        # Create-style handlers answer with the created document's name —
        # the convention the wiring between steps depends on.
        prefix = {
            "create_patient": "PAT",
            "create_encounter": "ENC",
            "assign_practitioner": "ASG",
        }.get(spec.name)
        if prefix:
            return ToolResult.success(json.dumps({"name": f"{prefix}-0001"}))
        return ToolResult.success("done")

    def count(self, name: str) -> int:
        return sum(1 for tool, _args in self.calls if tool == name)


@pytest.fixture()
def undo_args_narrowed():
    """The undo tools' schemas carry only `name` — as the real ones do."""
    return REGISTRY


class TestHappyPath:
    def test_three_steps_run_in_order_and_the_flow_succeeds(self):
        h = Harness()
        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=h.run_single,
        )
        assert result.ok is True
        assert [tool for tool, _ in h.calls] == [
            "create_patient",
            "create_encounter",
            "assign_practitioner",
        ]
        assert json.loads(result.content)["flow"] == "admit_patient"

    def test_the_wiring_carries_the_created_names_forward(self):
        h = Harness()
        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=h.run_single,
        )
        assert result.ok is True
        # The wiring lands the earlier step's output in the argument `into`
        # names — a parameter the step's tool declares, because a closed
        # schema refuses anything else: the encounter's `patient` is the
        # patient step 0 created, and the assignment's `encounter` is the
        # encounter step 1 created.
        assert h.calls[1][1]["patient"] == "PAT-0001"
        assert h.calls[2][1]["encounter"] == "ENC-0001"
        # The model can cite what was created without re-reading.
        steps = json.loads(result.content)["steps"]
        assert steps["create_patient"]["name"] == "PAT-0001"

    def test_placeholders_are_substituted_from_the_callers_arguments(self):
        h = Harness()
        run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=h.run_single,
        )
        assert h.calls[0][1] == {"patient_name": "Aisha"}


class TestCompensation:
    def test_a_failing_step_undoes_the_completed_ones_in_reverse(self):
        h = Harness(fail_at="assign_practitioner")
        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=h.run_single,
        )
        assert result.ok is False
        # The undo order is the reverse of completion: cancel the encounter
        # first, then delete the patient.
        undos = [tool for tool, _ in h.calls if tool in ("cancel_encounter", "delete_patient")]
        assert undos == ["cancel_encounter", "delete_patient"]
        # The undos are addressed to what this flow created, not guessed.
        delete_args = next(args for tool, args in h.calls if tool == "delete_patient")
        assert delete_args == {"name": "PAT-0001"}

    def test_the_account_names_the_failure_and_the_undos(self):
        h = Harness(fail_at="create_encounter")
        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=h.run_single,
        )
        assert "create_encounter: FAILED" in result.content
        assert "undo: delete_patient" in result.content
        assert "NOT UNDONE" not in result.content

    def test_an_undo_that_fails_is_reported_never_hidden(self):
        h = Harness()
        h.fail_at = "cancel_encounter"

        # The undo itself fails: the account must say what the operator
        # must clean up, because a compensation that quietly gives up is
        # worse than none.
        def run_single(spec, arguments, principal, conversation):
            return h.run_single(spec, arguments, principal, conversation)

        original = h.run_single

        def failing_undo(spec, arguments, principal, conversation):
            if spec.name == "cancel_encounter":
                h.calls.append((spec.name, dict(arguments)))
                return ToolResult.failure("the encounter is locked", error="locked")
            return original(spec, arguments, principal, conversation)

        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=failing_undo,
        )
        # assign succeeds, encounter succeeds, assignment succeeds; nothing
        # fails mid-flow in this scenario — force a failure to reach undo:
        h2 = Harness(fail_at="assign_practitioner")

        def failing_undo_2(spec, arguments, principal, conversation):
            if spec.name == "cancel_encounter":
                h2.calls.append((spec.name, dict(arguments)))
                return ToolResult.failure("the encounter is locked", error="locked")
            return h2.run_single(spec, arguments, principal, conversation)

        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=failing_undo_2,
        )
        assert result.ok is False
        assert "NOT UNDONE" in result.content
        assert "cancel_encounter failed: the encounter is locked" in result.content

    def test_a_step_with_no_declared_undo_is_named_not_silently_skipped(self):
        no_undo = spec_for("create_note", {"text": {"type": "string"}})
        flow = FlowSpec(
            name="note_flow",
            steps=(
                FlowStep(tool="create_note", arguments={"text": "hi"}),
                FlowStep(tool="create_patient", arguments={"patient_name": "A"}),
            ),
            compensation=CompensationSpec(mechanism="reverse", undo_with=("delete_patient",)),
        )
        caller = spec_for("note_flow", {}, flow=flow)
        registry = ToolRegistry([no_undo, CREATE_PATIENT, DELETE_PATIENT, caller])
        h = Harness(fail_at="create_patient")

        result = run_flow(
            caller,
            {},
            PRINCIPAL,
            "conv-1",
            registry=registry,
            run_single=h.run_single,
        )
        assert result.ok is False
        assert "create_note" in result.content
        assert "declares no undo" in result.content

    def test_a_failing_first_step_runs_no_undo(self):
        h = Harness(fail_at="create_patient")
        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=h.run_single,
        )
        assert result.ok is False
        # Nothing completed, so there is nothing to undo — and no undo call
        # runs "just in case", because an undo of nothing is a write.
        assert h.count("delete_patient") == 0
        assert h.count("cancel_encounter") == 0


class TestGates:
    def test_an_unresolvable_placeholder_refuses_before_anything_runs(self):
        from dataclasses import dataclass

        bad_step = FlowStep(tool="create_patient", arguments={"patient_name": "{nope}"})
        flow = FlowSpec(
            name="admit_patient",
            steps=(bad_step, FlowStep(tool="create_encounter", from_step=0, from_field="name", arguments={})),
            compensation=CompensationSpec(mechanism="reverse", undo_with=("delete_patient",)),
        )
        bad = ToolSpec(
            name="admit_patient",
            description="",
            parameters={"type": "object", "properties": {}, "required": []},
            tier=WRITE,
            flow=flow,
        )
        h = Harness()
        result = run_flow(
            bad,
            {},
            PRINCIPAL,
            "conv-1",
            registry=REGISTRY,
            run_single=h.run_single,
        )
        assert result.ok is False
        assert result.error == "invalid_flow"
        assert h.calls == []

    def test_a_disabled_step_tool_fails_before_later_steps_run(self):
        empty = ToolRegistry([])  # nothing registered at all
        h = Harness()
        result = run_flow(
            ADMIT,
            {"patient_name": "Aisha", "encounter_type": "Admission", "practitioner": "Dr. Ahmed"},
            PRINCIPAL,
            "conv-1",
            registry=empty,
            run_single=h.run_single,
        )
        assert result.ok is False
        assert "not available" in result.content
        assert h.calls == []


class TestTurnLoopDispatch:
    def test_the_turn_loop_sends_a_flow_to_the_runner(self):
        # The wiring between the turn loop and the runner is one branch, and
        # it is asserted as source, the way this repo asserts contract lines
        # that cannot be exercised without a site: a branch nobody exercises
        # and nobody asserts is a branch that rots.
        import inspect

        from albanna_ai_chat.services import turn_loop

        source = inspect.getsource(turn_loop._run_tool)
        assert "spec.flow is not None" in source
        assert "run_flow" in source
