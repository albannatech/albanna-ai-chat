"""The core's own tools, and the port they run behind.

These tests assert the two things that must not drift: that the three file
tools obey every rule the validator enforces on extensions, and that the port
expresses a call without being able to make one.

Run with plain ``pytest`` — no bench, no site, no Frappe.
"""

from __future__ import annotations

import pytest

from albanna_ai_chat.core import (
    CORE_TOOL_NAMES,
    CORE_TOOLS,
    EDIT_FILE,
    FORBIDDEN_PARAM_NAMES,
    READ,
    READ_FILE,
    SQL_PARAM_NAMES,
    WRITE,
    WRITE_FILE,
    Principal,
    ToolContext,
    ToolResult,
    validate_module,
)


def _declared_params(spec) -> set[str]:
    props = spec.parameters.get("properties") or {}
    return {str(n).lower() for n in props}


# --------------------------------------------------------------------------
# The surface is exactly three tools.
# --------------------------------------------------------------------------


def test_the_core_ships_exactly_three_tools():
    assert CORE_TOOLS.names() == ("read_file", "write_file", "edit_file")


def test_core_tool_names_matches_the_registry():
    """The blocklist and the registry are two truths that must be one.

    ``CORE_TOOL_NAMES`` is what the validator refuses to let an extension
    shadow.  If it drifts from ``CORE_TOOLS``, an extension can shadow a core
    tool under a name the validator believes is free.
    """
    assert set(CORE_TOOL_NAMES) == set(CORE_TOOLS.names())


def test_every_core_tool_records_its_provenance():
    for spec in CORE_TOOLS.all():
        assert spec.source == "core", f"{spec.name} does not say it is core"


# --------------------------------------------------------------------------
# The rules the validator enforces on extensions apply to the core too.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("spec", CORE_TOOLS.all(), ids=lambda s: s.name)
def test_no_core_tool_declares_a_forbidden_parameter(spec):
    hits = _declared_params(spec) & FORBIDDEN_PARAM_NAMES
    assert not hits, f"{spec.name} declares forbidden parameter(s): {sorted(hits)}"


@pytest.mark.parametrize("spec", CORE_TOOLS.all(), ids=lambda s: s.name)
def test_no_core_tool_declares_a_sql_parameter(spec):
    hits = _declared_params(spec) & SQL_PARAM_NAMES
    assert not hits, f"{spec.name} declares SQL parameter(s): {sorted(hits)}"


@pytest.mark.parametrize("spec", CORE_TOOLS.all(), ids=lambda s: s.name)
def test_every_core_tool_declares_an_object_schema(spec):
    assert spec.parameters.get("type") == "object"
    assert spec.parameters.get("additionalProperties") is False


@pytest.mark.parametrize("spec", CORE_TOOLS.all(), ids=lambda s: s.name)
def test_every_core_tool_has_a_model_facing_description(spec):
    """The description is the only thing the model reads before calling.

    An empty or placeholder description is a tool the model cannot choose
    correctly, which is worse than a tool that does not exist.
    """
    assert spec.description.strip()
    assert len(spec.description) > 40


def test_the_core_tools_pass_the_extension_validator():
    """The core is held to the contract it enforces on everyone else.

    If the core's own tools could not pass ``validate_module``, the validator
    would be enforcing a rule the core exempts itself from — which is how a
    blocklist quietly stops meaning anything.
    """
    import types

    module = types.ModuleType("core_self_check")
    module.TOOLS = CORE_TOOLS.all()
    module.TIERS = {spec.name: spec.tier for spec in CORE_TOOLS.all()}
    specs = validate_module(module, known_tools=set())
    assert [s.name for s in specs] == list(CORE_TOOLS.names())


# --------------------------------------------------------------------------
# Tiers and what each write is authorised against.
# --------------------------------------------------------------------------


def test_read_file_is_a_read():
    assert READ_FILE.tier == READ
    assert not READ_FILE.mutating


def test_write_file_is_a_write_authorised_against_create():
    assert WRITE_FILE.tier == WRITE
    assert WRITE_FILE.mutating
    assert WRITE_FILE.write_permission == "create"


def test_edit_file_is_a_write_authorised_against_write():
    assert EDIT_FILE.tier == WRITE
    assert EDIT_FILE.mutating
    assert EDIT_FILE.write_permission == "write"


def test_no_core_tool_is_authorised_against_delete():
    """There is no delete_file in the core, and that is the decision.

    Deletion is the one file operation with no undo the core can offer.  An
    extension that wants one must declare it with a compensation entry.
    """
    for spec in CORE_TOOLS.all():
        assert spec.write_permission != "delete"


# --------------------------------------------------------------------------
# Compensation: every write says how it is undone.
# --------------------------------------------------------------------------


def test_every_core_write_declares_compensation():
    """The core is held to the rule it enforces on extensions."""
    for spec in CORE_TOOLS.all():
        if spec.mutating:
            assert spec.compensation is not None, f"{spec.name} declares no compensation"
            assert spec.compensation.problems() == [], f"{spec.name} compensation is incomplete"


def test_no_core_tool_declares_compensation_twice():
    """A flow and a direct compensation is two answers to one question."""
    for spec in CORE_TOOLS.all():
        assert not (spec.flow is not None and spec.compensation is not None)


def test_write_file_is_honest_about_having_no_undo():
    """``none`` is allowed precisely because it must be written down.

    The core ships no delete_file, so creating a file has no tool-level undo.
    Saying so is the correct declaration; pretending otherwise is not.
    """
    assert WRITE_FILE.compensation is not None
    assert WRITE_FILE.compensation.mechanism == "none"
    assert WRITE_FILE.compensation.reason.strip()
    assert WRITE_FILE.compensation.undo_with == ()


def test_edit_file_is_undone_by_editing_back():
    """Swapping old_string and new_string restores the file exactly."""
    assert EDIT_FILE.compensation is not None
    assert EDIT_FILE.compensation.mechanism == "reverse"
    assert EDIT_FILE.compensation.undo_with == ("edit_file",)
    assert EDIT_FILE.compensation.reason == ""


# --------------------------------------------------------------------------
# Reach: a caller who may do nothing is not told the tool exists.
# --------------------------------------------------------------------------


def _shown(registry) -> set[str]:
    """The names the model is actually shown.

    Asserted against ``enabled()`` rather than ``in`` — the registry keeps a
    disabled spec so the name stays occupied for collision checks, but the
    model-facing surface is the enabled set.  A disabled tool is not merely
    refused at call time; it is never mentioned.
    """
    return {s.name for s in registry.enabled()}


def test_a_caller_who_may_create_nothing_is_not_shown_write_file():
    registry = CORE_TOOLS.without_writes_out_of_reach(
        creatable=set(), writable=set()
    )
    assert _shown(registry) == {"read_file"}


def test_a_caller_who_may_only_create_is_shown_write_file_but_not_edit_file():
    registry = CORE_TOOLS.without_writes_out_of_reach(
        creatable={"File"}, writable=set()
    )
    assert _shown(registry) == {"read_file", "write_file"}


def test_a_caller_who_may_write_is_shown_both_writes():
    """Each write is gated on its own right, not on 'being a write'.

    ``write_file`` is authorised against ``create`` and ``edit_file``
    against ``write``.  Holding one does not imply the other, which is the
    point: a person who may change a file but not add one is offered the
    edit and not the create.
    """
    registry = CORE_TOOLS.without_writes_out_of_reach(
        creatable={"File"}, writable={"File"}
    )
    assert _shown(registry) == {"read_file", "write_file", "edit_file"}


def test_holding_write_alone_shows_only_the_edit():
    registry = CORE_TOOLS.without_writes_out_of_reach(
        creatable=set(), writable={"File"}
    )
    assert _shown(registry) == {"read_file", "edit_file"}


def test_disabling_a_tool_removes_it_from_the_manifest_entirely():
    """A disabled tool is not merely refused — it is never mentioned."""
    registry = CORE_TOOLS.without(["read_file"])
    assert _shown(registry) == {"write_file", "edit_file"}


# --------------------------------------------------------------------------
# Provenance: an uninstall is exact.
# --------------------------------------------------------------------------


def test_from_source_returns_exactly_the_core_tools():
    assert [s.name for s in CORE_TOOLS.from_source("core")] == list(
        CORE_TOOLS.names()
    )


def test_from_source_returns_nothing_for_an_unknown_extension():
    assert CORE_TOOLS.from_source("healthcare") == []


# --------------------------------------------------------------------------
# The port expresses a call without being able to make one.
# --------------------------------------------------------------------------


def test_a_successful_result_says_so():
    result = ToolResult.success("three files", data=[1, 2, 3], summary="Read 3 files")
    assert result.ok
    assert not result.denied
    assert result.summary == "Read 3 files"


def test_a_refusal_is_not_a_failure():
    """The model must be able to tell a refusal from a break.

    The correct response to a refusal is to tell the reader they lack the
    right — not to retry, and not to report an error.
    """
    result = ToolResult.refusal("You may not write files.", "no create permission")
    assert not result.ok
    assert result.denied
    assert result.error == "no create permission"


def test_a_declined_approval_is_distinct_from_a_failure():
    result = ToolResult(ok=False, content="declined", approved=False)
    assert not result.ok
    assert not result.denied
    assert result.approved is False


def test_a_write_that_did_not_wait_has_no_approval_state():
    result = ToolResult.success("written")
    assert result.approved is None


def test_a_dry_run_result_says_nothing_was_saved():
    result = ToolResult(ok=True, content="would write", dry_run=True)
    assert result.dry_run


def test_the_context_carries_the_principal_and_the_site():
    context = ToolContext(
        principal=Principal(user="a@example.com", roles=("Albanna User",)),
        site="albanna.localhost",
        request_id="req-1",
        conversation="CONV-0001",
    )
    assert context.principal.user == "a@example.com"
    assert context.principal.has_role("Albanna User")
    assert not context.principal.has_role("System Manager")
    assert context.site == "albanna.localhost"
    assert context.conversation == "CONV-0001"


def test_the_conversation_is_not_a_model_facing_parameter():
    """The model never fills the conversation in — it is not in any schema."""
    for spec in CORE_TOOLS.all():
        assert "conversation" not in _declared_params(spec)
