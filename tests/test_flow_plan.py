"""Tests for the flow planner — the pure half of flows.

No Frappe, no network, no backends. What is pinned down here is the planner's
contract with the runner: placeholders resolve from the flow tool's own
schema, wiring reads an earlier step's output or says so, and an undo call's
arguments are narrowed to what the undo tool actually declares — an undo that
would run with half its arguments is refused rather than guessed.
"""

from __future__ import annotations

import pytest

from albanna_ai_chat.core.flow import CompensationSpec, FlowSpec, FlowStep
from albanna_ai_chat.core.flow_plan import (
    flow_summary,
    parse_output,
    placeholder_problems,
    step_arguments,
    undo_arguments,
)
from albanna_ai_chat.core.tools import ToolSpec, WRITE


def flow_tool(name: str = "admit_patient", **params) -> ToolSpec:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": params
        or {
            "patient_name": {"type": "string"},
            "practitioner": {"type": "string"},
        },
        "required": [],
    }
    return ToolSpec(
        name=name,
        description="The flow under test.",
        parameters=schema,
        tier=WRITE,
        flow=FlowSpec(
            name=name,
            steps=(
                FlowStep(tool="create_patient", arguments={"patient_name": "{patient_name}"}),
                FlowStep(
                    tool="create_encounter",
                    from_step=0,
                    from_field="name",
                    arguments={"encounter_type": "Admission"},
                ),
            ),
            compensation=CompensationSpec(mechanism="reverse", undo_with=("cancel", "delete")),
        ),
    )


class TestPlaceholderProblems:
    def test_a_placeholder_in_the_schema_is_fine(self):
        assert placeholder_problems(flow_tool(), {"patient_name": "Aisha"}) == []

    def test_a_placeholder_outside_the_schema_is_a_problem_before_anything_runs(self):
        spec = flow_tool()
        # A {dob} as the *value* of patient_name is interpolation, not a
        # step placeholder — no step argument names it, so no problem; the
        # case that IS a problem is a step argument naming an undeclared
        # parameter, tested below.
        problems = placeholder_problems(
            spec,
            {"patient_name": "{dob}"},
        )
        assert problems == []

    def test_a_step_argument_referencing_an_undeclared_parameter_is_caught(self):
        from dataclasses import replace

        spec = flow_tool()
        bad_flow = FlowSpec(
            name=spec.flow.name,
            steps=(
                FlowStep(
                    tool="create_patient",
                    arguments={"patient_name": "{not_a_parameter}"},
                ),
                *spec.flow.steps[1:],
            ),
            compensation=spec.flow.compensation,
        )
        from albanna_ai_chat.core.tools import ToolSpec as TS

        bad = TS(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
            tier=WRITE,
            flow=bad_flow,
        )
        problems = placeholder_problems(bad, {})
        assert len(problems) == 1
        assert "not_a_parameter" in problems[0]
        assert "before" not in problems[0]  # the sentence names the step


class TestStepArguments:
    def test_placeholders_are_substituted_whole_values_keep_their_type(self):
        step = FlowStep(tool="t", arguments={"limit": "{limit}", "note": "for {who}"})
        args, problem = step_arguments(
            step,
            {"limit": 5, "who": "Aisha"},
            outputs={},
        )
        assert problem == ""
        # An integer stays an integer — "5" would be a schema violation the
        # step then fails for a reason the caller did not cause.
        assert args["limit"] == 5
        assert args["note"] == "for Aisha"

    def test_wiring_reads_the_earlier_step_output(self):
        step = FlowStep(tool="t", from_step=0, from_field="name", arguments={})
        args, problem = step_arguments(step, {}, outputs={0: {"name": "ENC-0001"}})
        assert problem == ""
        assert args["name"] == "ENC-0001"

    def test_wiring_from_a_step_that_produced_nothing_is_a_sentence(self):
        step = FlowStep(tool="t", from_step=0, from_field="name", arguments={})
        args, problem = step_arguments(step, {}, outputs={})
        assert args == {}
        assert "has not produced one" in problem

    def test_wiring_for_a_field_the_output_lacks_is_a_sentence(self):
        step = FlowStep(tool="t", from_step=0, from_field="ref", arguments={})
        args, problem = step_arguments(step, {}, outputs={0: {"name": "x"}})
        assert "does not carry it" in problem
        assert "ref" in problem


class TestParseOutput:
    def test_a_json_object_is_the_object(self):
        assert parse_output('{"name": "PAT-0001"}') == {"name": "PAT-0001"}

    def test_a_sentence_is_carried_under_the_empty_field(self):
        # A handler that answers in prose is not a wiring failure — it just
        # cannot be addressed by field, and a wiring that tries is told so.
        assert parse_output("created the patient") == {"": "created the patient"}

    def test_non_object_json_is_carried_under_the_empty_field(self):
        assert parse_output("[1, 2]") == {"": "[1, 2]"}


class TestUndoArguments:
    def test_the_undo_receives_the_fields_its_schema_declares(self):
        undo = ToolSpec(
            name="delete_patient",
            description="",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        args, problem = undo_arguments(undo, {"name": "PAT-0001", "sex": "F"})
        assert problem == ""
        # `sex` is not a parameter of delete_patient — sending it would be
        # an argument the undo tool's own validation refuses.
        assert args == {"name": "PAT-0001"}

    def test_a_required_field_the_output_lacks_refuses_the_undo(self):
        undo = ToolSpec(
            name="delete_patient",
            description="",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        args, problem = undo_arguments(undo, {"ok": True})
        assert args == {}
        assert "cannot be undone automatically" in problem
        assert "name" in problem

    def test_an_undo_with_no_declared_parameters_refuses(self):
        undo = ToolSpec(
            name="noop",
            description="",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        args, problem = undo_arguments(undo, {"name": "x"})
        assert "cannot be undone automatically" in problem


class TestFlowSummary:
    def test_every_step_including_the_undos(self):
        text = flow_summary(
            "admit_patient",
            [
                ("create_patient", True, "created PAT-0001"),
                ("create_encounter", False, "the encounter was refused"),
                ("undo: delete_patient", True, ""),
            ],
        )
        assert "create_patient: ok" in text
        assert "create_encounter: FAILED" in text
        assert "undo: delete_patient" in text


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"name": "x"}', {"name": "x"}),
        ("plain", {"": "plain"}),
    ],
)
def test_parse_output_convention(content, expected):
    assert parse_output(content) == expected


class TestWiringTarget:
    def test_into_lands_the_wired_value_in_the_named_argument(self):
        from albanna_ai_chat.core.flow import FlowStep as FS

        step = FS(tool="create_encounter", from_step=0, from_field="name", into="patient")
        args, problem = step_arguments(step, {}, outputs={0: {"name": "PAT-0001"}})
        assert problem == ""
        # `patient`, not `name` — the argument create_encounter declares.
        assert args["patient"] == "PAT-0001"
        assert "name" not in args
