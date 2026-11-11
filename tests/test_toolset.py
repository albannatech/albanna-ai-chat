"""The tool set one turn is allowed to use.

The rule under test is one sentence: *Frappe decides, per account, and the
operator's list only ever narrows it.*  Everything here is a consequence of
that sentence, and every test names which consequence.
"""

import pytest

from albanna_ai_chat.core.file_tools import CORE_TOOLS, EDIT_FILE, READ_FILE, WRITE_FILE
from albanna_ai_chat.core.flow import CompensationSpec
from albanna_ai_chat.core.tools import ToolRegistry, ToolSpec
from albanna_ai_chat.core.toolset import Reach, tools_from, visible_tools, without_source
from albanna_ai_chat.core.validate import absorb, validate_module


def spec(name, tier="read", source="core", **kw):
    """A minimal spec.  A write carries compensation, because the validator
    refuses a mutating tool that cannot say how it is undone."""
    if tier == "write" and "compensation" not in kw:
        kw["compensation"] = CompensationSpec(mechanism="reverse", undo_with=(name,))
    return ToolSpec(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        tier=tier,
        source=source,
        **kw,
    )


def module(name, specs):
    """A minimal extension module, as ``validate_module`` expects one.

    ``TOOLS`` is a list of ``ToolSpec`` and ``TIERS`` maps every name to its
    tier — the contract, not a convenience shape.
    """
    import types

    mod = types.ModuleType(name)
    mod.TOOLS = list(specs)
    mod.TIERS = {s.name: s.tier for s in specs}
    return mod


def registry_with(*specs):
    return ToolRegistry(list(specs))


def shown(registry):
    """The tool names the model is actually shown.

    ``name in registry`` answers "is this tool known", which is not the
    question.  A tool switched off by reach or by the operator's list is still
    *in* the registry — it is simply never mentioned to the model, which is
    the whole point of switching it off rather than refusing it at call time.
    """
    return {spec.name for spec in registry.enabled()}


# --------------------------------------------------------------------------
# Reach
# --------------------------------------------------------------------------


class TestReach:
    def test_an_empty_reach_hides_every_write(self):
        registry = registry_with(READ_FILE, WRITE_FILE, EDIT_FILE)
        visible = visible_tools(registry, Reach())
        assert shown(visible) == {"read_file"}

    def test_creatable_alone_shows_only_create_writes(self):
        registry = registry_with(READ_FILE, WRITE_FILE, EDIT_FILE)
        visible = visible_tools(registry, Reach(creatable={"File"}))
        assert shown(visible) == {"read_file", "write_file"}

    def test_writable_alone_shows_only_write_writes(self):
        registry = registry_with(READ_FILE, WRITE_FILE, EDIT_FILE)
        visible = visible_tools(registry, Reach(writable={"File"}))
        assert shown(visible) == {"read_file", "edit_file"}

    def test_reads_are_always_visible(self):
        """A read has no right to hold, so there is nothing to be out of reach of."""
        registry = registry_with(READ_FILE)
        assert shown(visible_tools(registry, Reach())) == {"read_file"}

    def test_reach_compares_by_value(self):
        assert Reach(creatable={"File"}) == Reach(creatable={"File"})
        assert Reach(creatable={"File"}) != Reach(creatable={"Item"})


# --------------------------------------------------------------------------
# The operator's list only ever narrows
# --------------------------------------------------------------------------


class TestDisabledList:
    def test_a_disabled_tool_is_hidden_from_everyone(self):
        registry = registry_with(READ_FILE, WRITE_FILE)
        visible = visible_tools(registry, Reach(creatable={"File"}), disabled=["write_file"])
        assert shown(visible) == {"read_file"}

    def test_the_list_cannot_widen_the_set(self):
        """There is no site-wide switch that can disagree with the permission matrix."""
        registry = registry_with(READ_FILE, WRITE_FILE)
        visible = visible_tools(registry, Reach(), disabled=[])
        assert "write_file" not in shown(visible)

    def test_an_unknown_name_hides_nothing_and_is_not_an_error(self):
        registry = registry_with(READ_FILE)
        visible = visible_tools(registry, Reach(), disabled=["no_such_tool"])
        assert "read_file" in shown(visible)

    def test_empty_strings_in_the_list_are_ignored(self):
        registry = registry_with(READ_FILE)
        visible = visible_tools(registry, Reach(), disabled=["", None, "read_file"])
        assert "read_file" not in shown(visible)


# --------------------------------------------------------------------------
# Extensions are not a special case
# --------------------------------------------------------------------------


class TestExtensionsAreNotSpecial:
    def test_an_extension_write_is_reach_checked_like_a_core_write(self):
        ext = validate_module(
            module(
                "healthcare_mcp",
                [
                    spec(
                        "admit_patient",
                        tier="write",
                        source="healthcare_mcp",
                        doctype_arg="doctype",
                        write_permission="create",
                    )
                ],
            )
        )
        registry = absorb(ext, CORE_TOOLS)

        assert "admit_patient" not in shown(visible_tools(registry, Reach()))
        assert "admit_patient" in shown(visible_tools(registry, Reach(creatable={"Patient"})))

    def test_an_extension_read_is_always_visible(self):
        ext = validate_module(module("healthcare_mcp", [spec("get_patient", source="healthcare_mcp")]))
        registry = absorb(ext, CORE_TOOLS)
        assert "get_patient" in shown(visible_tools(registry, Reach()))

    def test_the_operator_can_disable_an_extension_tool(self):
        ext = validate_module(module("healthcare_mcp", [spec("get_patient", source="healthcare_mcp")]))
        registry = absorb(ext, CORE_TOOLS)
        visible = visible_tools(registry, Reach(), disabled=["get_patient"])
        assert "get_patient" not in shown(visible)


# --------------------------------------------------------------------------
# Uninstall is exact
# --------------------------------------------------------------------------


class TestUninstallIsExact:
    def _registry(self):
        ext = validate_module(
            module(
                "healthcare_mcp",
                [
                    spec("get_patient", source="healthcare_mcp"),
                    spec(
                        "admit_patient",
                        tier="write",
                        source="healthcare_mcp",
                        doctype_arg="doctype",
                    ),
                ],
            )
        )
        return absorb(ext, CORE_TOOLS)

    def test_removing_an_extension_removes_its_tools(self):
        registry = without_source(self._registry(), "healthcare_mcp")
        assert "get_patient" not in registry
        assert "admit_patient" not in registry

    def test_removing_an_extension_leaves_the_core_alone(self):
        registry = without_source(self._registry(), "healthcare_mcp")
        assert set(registry.names()) == set(CORE_TOOLS.names())

    def test_removing_one_extension_leaves_the_others(self):
        base = absorb(
            validate_module(module("crm_mcp", [spec("score_lead", source="crm_mcp")])),
            self._registry(),
        )
        registry = without_source(base, "healthcare_mcp")
        assert "score_lead" in registry
        assert "get_patient" not in registry

    def test_uninstall_removes_rather_than_merely_disables(self):
        """A deactivated extension's tools must not still be in the registry,
        or a later extension with the same name would collide with a tool
        nobody can see."""
        registry = without_source(self._registry(), "healthcare_mcp")
        assert len(registry) == len(CORE_TOOLS)
        assert registry.get("get_patient") is None

    def test_tools_from_selects_by_source(self):
        registry = self._registry()
        assert [s.name for s in tools_from(registry, "healthcare_mcp")] == [
            "get_patient",
            "admit_patient",
        ]
        assert [s.name for s in tools_from(registry, "core")] == list(CORE_TOOLS.names())

    def test_sources_lists_every_contributor(self):
        registry = self._registry()
        assert set(registry.sources()) == {"core", "healthcare_mcp"}
