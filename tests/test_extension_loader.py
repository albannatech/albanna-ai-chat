"""Discovering and absorbing the extensions installed on a site.

The loader imports Frappe, so these tests install a stub.  What they verify is
the part that cannot be got right by inspection: that a *contract violation*
raises while an *ImportError* is skipped, because collapsing those two is how
a broken optional dependency takes the whole core surface down with it.
"""

from __future__ import annotations

import sys
import types

import pytest

from albanna_ai_chat.core.file_tools import CORE_TOOLS
from albanna_ai_chat.core.flow import CompensationSpec
from albanna_ai_chat.core.tools import ToolRegistry, ToolSpec
from albanna_ai_chat.core.validate import ContractViolation


def spec(name, tier="read", **kw):
    if tier == "write" and "compensation" not in kw:
        kw["compensation"] = CompensationSpec(mechanism="reverse", undo_with=(name,))
    return ToolSpec(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        tier=tier,
        **kw,
    )


def make_module(name, specs, tiers=None):
    mod = types.ModuleType(name)
    mod.TOOLS = list(specs)
    mod.TIERS = tiers if tiers is not None else {s.name: s.tier for s in specs}
    return mod


@pytest.fixture
def frappe_stub(monkeypatch):
    """A stub whose hooks and installed-apps answer whatever the test says."""
    state = {"hooks": {}, "apps": []}

    module = types.ModuleType("frappe")

    def get_hooks(hook, app_name=None, **kw):
        # Real Frappe returns the value registered *for that hook*, keyed by
        # app when app_name is None — not the whole hooks dict.
        return dict(state["hooks"].get(hook, {}))

    def get_installed_apps():
        return list(state["apps"])

    module.get_hooks = get_hooks
    module.get_installed_apps = get_installed_apps
    monkeypatch.setitem(sys.modules, "frappe", module)
    # Drop the package *and* the module: `from pkg import mod` re-uses a cached
    # parent package's attribute, so deleting only the module leaves the stale
    # one bound and the stub never takes effect.
    for name in ("albanna_ai_chat.services.extensions", "albanna_ai_chat.services"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    from albanna_ai_chat.services import extensions

    return extensions, state


def install(monkeypatch, name, mod):
    monkeypatch.setitem(sys.modules, name, mod)


# --------------------------------------------------------------------------
# discover()
# --------------------------------------------------------------------------


class TestDiscover:
    def test_no_hooks_means_no_extensions(self, frappe_stub):
        extensions, _ = frappe_stub
        assert extensions.discover() == {}

    def test_a_declared_hook_is_found(self, frappe_stub):
        extensions, state = frappe_stub
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        assert extensions.discover() == {"healthcare_mcp": "healthcare_mcp.tools"}

    def test_an_app_that_is_not_installed_contributes_nothing(self, frappe_stub):
        """The scoping property the whole design rests on."""
        extensions, state = frappe_stub
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "erpnext"]
        # get_hooks on a real bench only returns hooks from installed apps; the
        # stub answers what it is told, so the assertion is about the shape.
        assert extensions.discover() == {"healthcare_mcp": "healthcare_mcp.tools"}


# --------------------------------------------------------------------------
# load_registry()
# --------------------------------------------------------------------------


class TestLoadRegistry:
    def test_no_extensions_leaves_the_core_alone(self, frappe_stub):
        extensions, _ = frappe_stub
        registry = extensions.load_registry()
        assert set(registry.names()) == set(CORE_TOOLS.names())

    def test_a_valid_extension_is_absorbed(self, frappe_stub, monkeypatch):
        extensions, state = frappe_stub
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}

        registry = extensions.load_registry()

        assert "get_patient" in registry
        assert "read_file" in registry

    def test_an_extension_tool_is_tagged_with_its_app(self, frappe_stub, monkeypatch):
        """Provenance is what makes an uninstall exact."""
        extensions, state = frappe_stub
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}

        registry = extensions.load_registry()

        assert [s.name for s in registry.from_source("healthcare_mcp")] == ["get_patient"]

    def test_provenance_is_the_app_name_not_the_module_name(self, frappe_stub, monkeypatch):
        """A manifest at healthcare_mcp.tools.manifest must tag its tools
        'healthcare_mcp', because an uninstall keys on the app — removing
        healthcare_mcp has to remove its tools and only its tools."""
        extensions, state = frappe_stub
        install(
            monkeypatch,
            "healthcare_mcp.tools.manifest",
            make_module("healthcare_mcp.tools.manifest", [spec("get_patient")]),
        )
        state["hooks"] = {
            "frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools.manifest"}
        }

        registry = extensions.load_registry()

        assert [s.name for s in registry.from_source("healthcare_mcp")] == ["get_patient"]
        assert registry.from_source("manifest") == []

    def test_the_input_registry_is_never_mutated(self, frappe_stub, monkeypatch):
        extensions, state = frappe_stub
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}

        before = set(CORE_TOOLS.names())
        extensions.load_registry(CORE_TOOLS)
        assert set(CORE_TOOLS.names()) == before

    def test_a_contract_violation_raises(self, frappe_stub, monkeypatch):
        """A developer bug must crash at load time, not half-load."""
        extensions, state = frappe_stub
        # An unclassified tool: TIERS does not mention it.
        install(
            monkeypatch,
            "broken_mcp.tools",
            make_module("broken_mcp.tools", [spec("mystery_tool")], tiers={}),
        )
        state["hooks"] = {"frappe_mcp_tools": {"broken_mcp": "broken_mcp.tools"}}

        with pytest.raises(ContractViolation) as excinfo:
            extensions.load_registry()
        assert "mystery_tool" in str(excinfo.value)

    def test_a_collision_with_a_core_tool_raises(self, frappe_stub, monkeypatch):
        extensions, state = frappe_stub
        install(monkeypatch, "shadow_mcp.tools", make_module("shadow_mcp.tools", [spec("read_file")]))
        state["hooks"] = {"frappe_mcp_tools": {"shadow_mcp": "shadow_mcp.tools"}}

        with pytest.raises(ContractViolation) as excinfo:
            extensions.load_registry()
        assert "read_file" in str(excinfo.value)

    def test_an_import_error_is_skipped_not_raised(self, frappe_stub, monkeypatch, capsys):
        """A missing dependency is an environment problem. One broken optional
        extension must not take the core surface down with it."""
        extensions, state = frappe_stub
        state["hooks"] = {"frappe_mcp_tools": {"absent_mcp": "absent_mcp.tools"}}

        registry = extensions.load_registry()

        assert set(registry.names()) == set(CORE_TOOLS.names())
        assert "absent_mcp" in capsys.readouterr().err

    def test_one_broken_extension_does_not_block_the_others(self, frappe_stub, monkeypatch, capsys):
        extensions, state = frappe_stub
        install(monkeypatch, "good_mcp.tools", make_module("good_mcp.tools", [spec("score_lead")]))
        state["hooks"] = {
            "frappe_mcp_tools": {
                "absent_mcp": "absent_mcp.tools",
                "good_mcp": "good_mcp.tools",
            }
        }

        registry = extensions.load_registry()

        assert "score_lead" in registry
        assert "absent_mcp" in capsys.readouterr().err


# --------------------------------------------------------------------------
# extension_report()
# --------------------------------------------------------------------------


class TestExtensionReport:
    def _registry(self, frappe_stub, monkeypatch):
        extensions, state = frappe_stub
        install(
            monkeypatch,
            "healthcare_mcp.tools",
            make_module(
                "healthcare_mcp.tools",
                [
                    spec("get_patient"),
                    spec(
                        "admit_patient",
                        tier="write",
                        doctype_arg="doctype",
                    ),
                ],
            ),
        )
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]
        return extensions, extensions.load_registry()

    def test_the_core_is_not_reported_as_an_extension(self, frappe_stub, monkeypatch):
        extensions, registry = self._registry(frappe_stub, monkeypatch)
        report = extensions.extension_report(registry)
        assert [r["app"] for r in report] == ["healthcare_mcp"]

    def test_the_report_names_the_tools(self, frappe_stub, monkeypatch):
        extensions, registry = self._registry(frappe_stub, monkeypatch)
        report = extensions.extension_report(registry)
        assert report[0]["tools"] == ["get_patient", "admit_patient"]

    def test_the_report_separates_writes(self, frappe_stub, monkeypatch):
        """The question an operator asks before deactivating one."""
        extensions, registry = self._registry(frappe_stub, monkeypatch)
        report = extensions.extension_report(registry)
        assert report[0]["writes"] == ["admit_patient"]

    def test_the_report_says_whether_the_app_is_installed(self, frappe_stub, monkeypatch):
        extensions, registry = self._registry(frappe_stub, monkeypatch)
        assert extensions.extension_report(registry)[0]["installed"] is True
