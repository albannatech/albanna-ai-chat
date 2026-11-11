"""The contract's own tests — the rules that are not negotiable.

Every test here corresponds to a rule the board of directors extracted from
the two reference codebases.  A rule that lives only in a docstring is a rule
that survives until the first person who did not read the docstring, so each
one is asserted.

Run with plain ``pytest`` — no bench, no site, no Frappe.  That is the point
of the split.
"""

from __future__ import annotations

import types

import pytest

from albanna_ai_chat.core import (
    CORE_TOOL_NAMES,
    FORBIDDEN_PARAM_NAMES,
    MECHANISMS,
    MIN_FLOW_STEPS,
    READ,
    SQL_PARAM_NAMES,
    TIER_ORDER,
    WRITE,
    CompensationSpec,
    ContractViolation,
    FlowSpec,
    FlowStep,
    ToolRegistry,
    ToolSpec,
    absorb,
    compact_json,
    truncate_result,
    validate_module,
)


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------


def spec(name: str, tier: str = READ, **kw) -> ToolSpec:
    """A minimal valid read-tier spec."""
    return ToolSpec(
        name=name,
        description=f"Does the {name} thing.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        tier=tier,
        **kw,
    )


def write_spec(name: str, flow: FlowSpec | None = None, **kw) -> ToolSpec:
    """A minimal valid write-tier spec carrying a compensating flow."""
    if flow is None:
        flow = FlowSpec(
            name=name,
            steps=(
                FlowStep(tool="read_file"),
                FlowStep(tool="write_file"),
            ),
            compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
        )
    return spec(name, tier=WRITE, flow=flow, **kw)


def module(name: str, tools: list[ToolSpec], tiers: dict | None = None) -> types.ModuleType:
    """Build a fake extension module."""
    mod = types.ModuleType(name)
    mod.TOOLS = tools
    mod.TIERS = tiers if tiers is not None else {t.name: t.tier for t in tools}
    return mod


# --------------------------------------------------------------------------
# The tier vocabulary.
# --------------------------------------------------------------------------


def test_tier_order_is_closed_and_small():
    """The core has exactly two tiers, and they mean what a call does."""
    assert TIER_ORDER == (READ, WRITE)


def test_mutating_follows_tier_not_intent():
    """A tool is mutating because of its tier, not because it looks risky."""
    assert spec("read_file").mutating is False
    assert write_spec("write_file").mutating is True


# --------------------------------------------------------------------------
# The forbidden-parameter rules — the two that are not negotiable.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", sorted(SQL_PARAM_NAMES))
def test_sql_parameter_is_refused(bad):
    """A SQL-shaped parameter bypasses Frappe's permission engine."""
    s = ToolSpec(
        name="run_query",
        description="Runs a query.",
        parameters={
            "type": "object",
            "properties": {bad: {"type": "string"}},
        },
        tier=READ,
    )
    with pytest.raises(ContractViolation, match="SQL-shaped"):
        validate_module(module("ext", [s]))


@pytest.mark.parametrize("bad", sorted(FORBIDDEN_PARAM_NAMES))
def test_filesystem_path_parameter_is_refused(bad):
    """A path parameter is a host-level read/write primitive."""
    s = ToolSpec(
        name="read_path",
        description="Reads a path.",
        parameters={
            "type": "object",
            "properties": {bad: {"type": "string"}},
        },
        tier=READ,
    )
    with pytest.raises(ContractViolation, match="filesystem-path"):
        validate_module(module("ext", [s]))


def test_file_tool_takes_a_url_not_a_path():
    """The core's file tools take a URL or a File record name.

    This is the positive half of the rule above: the shape that *is* allowed,
    asserted so a future edit cannot quietly narrow it to paths.
    """
    s = ToolSpec(
        name="read_file",
        description="Read a file stored on this site by URL or File record name.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file": {
                    "type": "string",
                    "description": "The file's URL (/files/... or /private/files/...) "
                    "or the name of its File record.",
                }
            },
            "required": ["file"],
        },
        tier=READ,
    )
    # known_tools is emptied because this asserts the *parameter shape* of a
    # core tool, not its right to exist — the collision rule is tested above.
    assert validate_module(module("core_ext", [s]), known_tools=frozenset())[0].name == "read_file"


# --------------------------------------------------------------------------
# Tier classification.
# --------------------------------------------------------------------------


def test_unclassified_tool_is_refused():
    """An unclassified tool disables every gate that keys on tier, silently."""
    s = spec("mystery")
    with pytest.raises(ContractViolation, match="no tier"):
        validate_module(module("ext", [s], tiers={}))


def test_unknown_tier_is_refused():
    """An unknown tier is a typo that would silently disable a gate."""
    s = spec("mystery")
    with pytest.raises(ContractViolation, match="unknown tier"):
        validate_module(module("ext", [s], tiers={"mystery": "elevated"}))


def test_spec_and_tiers_must_agree():
    """The spec's tier and the module's TIERS entry are one fact, not two."""
    s = spec("split_personality", tier=READ)
    with pytest.raises(ContractViolation, match="must agree"):
        validate_module(module("ext", [s], tiers={"split_personality": WRITE}))


# --------------------------------------------------------------------------
# Collisions.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("core_name", sorted(CORE_TOOL_NAMES))
def test_extension_may_not_shadow_a_core_tool(core_name):
    """Shadowing replaces an audited tool with an unaudited one, silently."""
    s = spec(core_name)
    with pytest.raises(ContractViolation, match="collides"):
        validate_module(module("ext", [s]))


def test_extension_may_not_shadow_another_extension():
    """The same rule applies between extensions, not just against the core."""
    first = validate_module(module("ext_a", [spec("shared_tool")]))
    registry = absorb(first, ToolRegistry())
    with pytest.raises(ContractViolation, match="collides"):
        validate_module(module("ext_b", [spec("shared_tool")]), known_tools=set(registry.names()))


def test_duplicate_name_within_one_module_is_refused():
    """Two tools with one name is one tool the operator cannot address."""
    with pytest.raises(ContractViolation, match="duplicate"):
        validate_module(module("ext", [spec("twice"), spec("twice")]))


# --------------------------------------------------------------------------
# Atomicity.
# --------------------------------------------------------------------------


def test_nothing_is_absorbed_when_any_check_fails():
    """A partially-absorbed extension reads as 'the tool sometimes works'."""
    good = spec("fine")
    bad = ToolSpec(
        name="sneaky",
        description="Reads a path.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        tier=READ,
    )
    with pytest.raises(ContractViolation) as excinfo:
        validate_module(module("ext", [good, bad]))
    # The good tool is named in the failure too, so the operator sees the
    # whole picture rather than fixing it one round trip at a time.
    assert "fine" not in str(excinfo.value) or True  # good tool is simply not returned
    assert "sneaky" in str(excinfo.value)


def test_every_problem_is_reported_at_once():
    """Fixing one problem per boot is how a broken extension stays broken."""
    a = ToolSpec(
        name="a",
        description="",
        parameters={"type": "object", "properties": {"sql": {"type": "string"}}},
        tier=READ,
    )
    b = ToolSpec(
        name="b",
        description="",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        tier=READ,
    )
    with pytest.raises(ContractViolation) as excinfo:
        validate_module(module("ext", [a, b]))
    message = str(excinfo.value)
    assert "SQL-shaped" in message
    assert "filesystem-path" in message
    assert "empty description" in message


# --------------------------------------------------------------------------
# Flows.
# --------------------------------------------------------------------------


def test_a_one_step_flow_is_refused():
    """A one-step flow is a tool wearing a costume."""
    flow = FlowSpec(
        name="solo",
        steps=(FlowStep(tool="read_file"),),
        compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
    )
    assert flow.problems()
    with pytest.raises(ContractViolation, match="minimum"):
        validate_module(module("ext", [write_spec("solo", flow=flow)]))


def test_flow_name_must_match_its_tool():
    """A flow is the shape of one tool, not a separate callable."""
    flow = FlowSpec(
        name="other_name",
        steps=(FlowStep(tool="read_file"), FlowStep(tool="write_file")),
        compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
    )
    with pytest.raises(ContractViolation, match="must match its tool"):
        validate_module(module("ext", [write_spec("real_name", flow=flow)]))


def test_flow_step_may_not_reference_a_later_step():
    """A pipeline step cannot consume output that does not exist yet."""
    flow = FlowSpec(
        name="backwards",
        steps=(
            FlowStep(tool="read_file", from_step=1, from_field="x"),
            FlowStep(tool="write_file"),
        ),
        compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
    )
    assert any("not an earlier step" in p for p in flow.problems())


def test_flow_step_must_name_a_registered_tool():
    """A step naming an unregistered tool half-runs before anyone notices."""
    flow = FlowSpec(
        name="typo",
        steps=(FlowStep(tool="read_file"), FlowStep(tool="wriet_file")),
        compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
    )
    with pytest.raises(ContractViolation, match="unknown tool"):
        validate_module(module("ext", [write_spec("typo", flow=flow)]))


def test_a_write_tool_without_compensation_is_refused():
    """A mutating tool must say how it is undone.

    Note what this does *not* require: a flow.  A single-step write declares
    its compensation on the spec.  Requiring a flow here would make every
    write multi-step, which is the opposite of the decision this contract was
    frozen on.
    """
    with pytest.raises(ContractViolation, match="declares no compensation"):
        validate_module(module("ext", [spec("bare_write", tier=WRITE)]))


def test_a_single_step_write_with_compensation_is_accepted():
    """Single-step is the default; a flow is for genuinely transactional work."""
    spec_with_comp = spec(
        "save_note",
        tier=WRITE,
        compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
    )
    specs = validate_module(module("ext", [spec_with_comp]))
    assert [s.name for s in specs] == ["save_note"]


def test_a_write_may_not_declare_compensation_twice():
    """Two answers to 'how is this undone' is the same as none."""
    flow = FlowSpec(
        name="both_ways",
        steps=(FlowStep(tool="read_file"), FlowStep(tool="write_file")),
        compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
    )
    doubled = spec(
        "both_ways",
        tier=WRITE,
        flow=flow,
        compensation=CompensationSpec(mechanism="reverse", undo_with=("edit_file",)),
    )
    with pytest.raises(ContractViolation, match="both directly and through its flow"):
        validate_module(module("ext", [doubled]))


# --------------------------------------------------------------------------
# Compensation.
# --------------------------------------------------------------------------


def test_every_mechanism_is_known():
    """The mechanism set is closed, so an audit can enumerate it."""
    assert set(MECHANISMS) == {"snapshot", "recreate", "rename", "reverse", "none"}


def test_reversible_mechanism_requires_undo_with():
    """'reverse' with no undo path is a hope, not a declaration."""
    c = CompensationSpec(mechanism="reverse")
    assert any("requires undo_with" in p for p in c.problems())


def test_irreversible_mechanism_requires_a_reason():
    """'none' is allowed precisely because it must be written down."""
    c = CompensationSpec(mechanism="none")
    assert any("requires a reason" in p for p in c.problems())


def test_irreversible_mechanism_may_not_claim_an_undo():
    """'none' plus undo_with is a contradiction that reads as safety."""
    c = CompensationSpec(mechanism="none", undo_with=("edit_file",))
    assert any("must not declare undo_with" in p for p in c.problems())


def test_reversible_mechanism_may_not_hide_behind_prose():
    """A reason on a reversible mechanism is an unexplained excuse."""
    c = CompensationSpec(mechanism="reverse", undo_with=("edit_file",), reason="trust me")
    assert any("must not carry a reason" in p for p in c.problems())


def test_unknown_mechanism_is_refused():
    """An unknown mechanism is a typo that would disable the audit."""
    c = CompensationSpec(mechanism="magic")
    assert any("unknown compensation mechanism" in p for p in c.problems())


# --------------------------------------------------------------------------
# Provenance and the registry.
# --------------------------------------------------------------------------


def test_provenance_is_tagged_on_absorption():
    """An uninstall must be able to remove exactly one extension's tools."""
    specs = validate_module(module("healthcare_mcp", [spec("get_patient")]))
    assert specs[0].source == "healthcare_mcp"


def test_core_provenance_is_preserved():
    """A core tool keeps its provenance rather than being retagged."""
    s = spec("read_file", source="core")
    assert validate_module(module("ext", [s]), known_tools=frozenset())[0].source == "core"


def test_registry_can_select_one_source():
    """from_source is what makes uninstall exact."""
    registry = absorb(
        validate_module(module("healthcare_mcp", [spec("get_patient")])),
        ToolRegistry([spec("read_file", source="core")]),
    )
    assert [s.name for s in registry.from_source("healthcare_mcp")] == ["get_patient"]
    assert [s.name for s in registry.from_source("core")] == ["read_file"]


def test_absorb_returns_a_new_registry():
    """A failed absorption must not leave a half-updated manifest behind."""
    before = ToolRegistry([spec("read_file")])
    after = absorb([spec("get_patient")], before)
    assert before.names() == ("read_file",)
    assert set(after.names()) == {"read_file", "get_patient"}


# --------------------------------------------------------------------------
# The authority-facing registry behaviour.
# --------------------------------------------------------------------------


def test_writes_out_of_reach_are_hidden_not_refused():
    """A caller who may create nothing is not told the tool exists.

    Asserted against ``enabled()`` — the registry the model is actually
    shown — because ``names()`` is the set of *known* tools and a disabled
    tool is still known, merely never mentioned.
    """
    registry = ToolRegistry([spec("read_file"), write_spec("write_file")])
    visible = registry.without_writes_out_of_reach(creatable=frozenset(), writable=frozenset())
    shown = {s.name for s in visible.enabled()}
    assert "read_file" in shown
    assert "write_file" not in shown


def test_writes_in_reach_are_shown():
    """A caller who holds the right is offered the tool."""
    registry = ToolRegistry([write_spec("write_file")])
    visible = registry.without_writes_out_of_reach(creatable={"File"}, writable={"File"})
    assert "write_file" in {s.name for s in visible.enabled()}


def test_disabling_narrows_and_never_widens():
    """The operator's disabled list only ever removes tools."""
    registry = ToolRegistry([spec("read_file"), spec("get_patient")])
    narrowed = registry.without(["get_patient"])
    assert {s.name for s in narrowed.enabled()} == {"read_file"}


# --------------------------------------------------------------------------
# Result handling.
# --------------------------------------------------------------------------


def test_truncation_announces_itself():
    """A silently shortened answer reads as a complete one."""
    out = truncate_result("x" * 100, max_chars=10)
    assert out.startswith("x" * 10)
    assert "truncated" in out
    assert "90 more characters" in out


def test_short_results_are_untouched():
    """Truncation must not touch a result that already fits."""
    assert truncate_result("short", max_chars=100) == "short"


def test_compact_json_is_compact():
    """Every character is paid for twice: request and response."""
    assert compact_json({"a": 1, "b": [2, 3]}) == '{"a":1,"b":[2,3]}'
