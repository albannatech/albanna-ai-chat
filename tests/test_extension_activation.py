"""Activation — the switch that decides which extensions are live.

The loader imports Frappe, so these tests install a stub.  What they verify is
the gap that a loader without an activation filter leaves open: an app that is
*installed* but not *switched on* must contribute no tools, and there must be
no second path by which its tools reach the model.

``load_registry`` and ``live_registry`` are separate functions rather than one
with a flag, and that separation is what these tests pin down.  A loader whose
default silently includes unactivated extensions is a loader one careless call
site away from exposing tools the operator never switched on.
"""

from __future__ import annotations

import sys
import types

import pytest

from albanna_ai_chat.core.extension_state import (
    ACTIVE,
    INSTALLED_INACTIVE,
    INSTALLED_INCOMPATIBLE,
    NOT_INSTALLED,
)
from albanna_ai_chat.core.file_tools import CORE_TOOLS
from albanna_ai_chat.core.flow import CompensationSpec
from albanna_ai_chat.core.tools import ToolSpec


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


def make_module(name, specs, tiers=None, requires_core=""):
    mod = types.ModuleType(name)
    mod.TOOLS = list(specs)
    mod.TIERS = tiers if tiers is not None else {s.name: s.tier for s in specs}
    if requires_core:
        mod.REQUIRES_CORE = requires_core
    return mod


class Settings:
    """A stand-in for the Single settings row."""

    def __init__(self, enabled=()):
        self._enabled = list(enabled)

    def enabled_extension_names(self):
        return tuple(self._enabled)


@pytest.fixture
def site(monkeypatch):
    """A stub Frappe whose hooks, apps and settings answer whatever the test says."""
    state = {"hooks": {}, "apps": [], "settings": Settings()}

    module = types.ModuleType("frappe")

    def get_hooks(hook, app_name=None, **kw):
        return dict(state["hooks"].get(hook, {}))

    def get_installed_apps():
        return list(state["apps"])

    def get_single(doctype):
        return state["settings"]

    module.get_hooks = get_hooks
    module.get_installed_apps = get_installed_apps
    module.get_single = get_single
    monkeypatch.setitem(sys.modules, "frappe", module)

    for name in ("albanna_ai_chat.services.extensions", "albanna_ai_chat.services"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    from albanna_ai_chat.services import extensions

    return extensions, state


def install(monkeypatch, name, mod):
    monkeypatch.setitem(sys.modules, name, mod)


# --------------------------------------------------------------------------
# activated_apps()
# --------------------------------------------------------------------------


class TestActivatedApps:
    def test_none_activated_means_an_empty_set(self, site):
        extensions, _ = site
        assert extensions.activated_apps() == set()

    def test_the_settings_row_decides(self, site):
        extensions, state = site
        state["settings"] = Settings(["healthcare_mcp"])
        assert extensions.activated_apps() == {"healthcare_mcp"}

    def test_a_missing_settings_row_means_none_are_on(self, site):
        """A site with no settings row must not silently activate everything."""
        extensions, state = site

        def boom(doctype):
            raise RuntimeError("no settings row")

        import frappe

        frappe.get_single = boom
        assert extensions.activated_apps() == set()


# --------------------------------------------------------------------------
# live_registry() — the only loader a turn may call.
# --------------------------------------------------------------------------


class TestLiveRegistry:
    def test_an_installed_but_unactivated_app_contributes_nothing(self, site, monkeypatch):
        extensions, state = site
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]

        registry = extensions.live_registry()

        assert "get_patient" not in registry
        assert set(registry.names()) == set(CORE_TOOLS.names())

    def test_an_activated_app_contributes_its_tools(self, site, monkeypatch):
        extensions, state = site
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]
        state["settings"] = Settings(["healthcare_mcp"])

        registry = extensions.live_registry()

        assert "get_patient" in registry

    def test_activating_one_of_two_leaves_the_other_dark(self, site, monkeypatch):
        """Activation is per app, not per site."""
        extensions, state = site
        install(monkeypatch, "a.tools", make_module("a.tools", [spec("tool_a")]))
        install(monkeypatch, "b.tools", make_module("b.tools", [spec("tool_b")]))
        state["hooks"] = {
            "frappe_mcp_tools": {"a_mcp": "a.tools", "b_mcp": "b.tools"},
        }
        state["apps"] = ["frappe", "a_mcp", "b_mcp"]
        state["settings"] = Settings(["a_mcp"])

        registry = extensions.live_registry()

        assert "tool_a" in registry
        assert "tool_b" not in registry

    def test_the_core_is_always_live(self, site):
        """Activation gates extensions, never the core's own tools."""
        extensions, _ = site
        registry = extensions.live_registry()
        assert set(registry.names()) == set(CORE_TOOLS.names())


# --------------------------------------------------------------------------
# load_registry() — "what is installed and valid", not "what is live".
# --------------------------------------------------------------------------


class TestLoadRegistry:
    def test_it_loads_everything_installed_regardless_of_activation(self, site, monkeypatch):
        """This is the question the Settings surface asks before the operator
        has switched anything on, and it is deliberately not the question a
        turn asks."""
        extensions, state = site
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]

        registry = extensions.load_registry()

        assert "get_patient" in registry

    def test_only_activated_narrows_it_to_the_live_surface(self, site, monkeypatch):
        extensions, state = site
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]

        assert "get_patient" not in extensions.load_registry(only_activated=True)

    def test_the_two_agree_when_everything_is_activated(self, site, monkeypatch):
        extensions, state = site
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]
        state["settings"] = Settings(["healthcare_mcp"])

        assert extensions.load_registry().names() == extensions.live_registry().names()


# --------------------------------------------------------------------------
# extension_states() — what the Settings surface renders.
# --------------------------------------------------------------------------


class TestExtensionStates:
    def test_an_installed_unactivated_app_is_inactive(self, site, monkeypatch):
        extensions, state = site
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]

        status = extensions.extension_states()[0]

        assert status.name == "healthcare_mcp"
        assert status.state == INSTALLED_INACTIVE
        assert status.action == "activate"

    def test_an_activated_app_is_active(self, site, monkeypatch):
        extensions, state = site
        install(monkeypatch, "healthcare_mcp.tools", make_module("healthcare_mcp.tools", [spec("get_patient")]))
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]
        state["settings"] = Settings(["healthcare_mcp"])

        assert extensions.extension_states()[0].state == ACTIVE

    def test_an_app_activated_but_not_installed_is_reported(self, site):
        """It usually means the app was uninstalled without deactivating it,
        and the operator needs to see that rather than have it vanish."""
        extensions, state = site
        state["apps"] = ["frappe"]
        state["settings"] = Settings(["ghost_mcp"])

        status = extensions.extension_states()[0]

        assert status.name == "ghost_mcp"
        assert status.state == NOT_INSTALLED
        assert "install-app ghost_mcp" in status.command

    def test_an_incompatible_app_is_reported_as_such(self, site, monkeypatch):
        """Version compatibility is checked against activation, so it is a
        visible settings row rather than a runtime surprise."""
        extensions, state = site
        install(
            monkeypatch,
            "healthcare_mcp.tools",
            make_module("healthcare_mcp.tools", [spec("get_patient")], requires_core=">=99.0.0"),
        )
        state["hooks"] = {"frappe_mcp_tools": {"healthcare_mcp": "healthcare_mcp.tools"}}
        state["apps"] = ["frappe", "healthcare_mcp"]
        state["settings"] = Settings(["healthcare_mcp"])

        status = extensions.extension_states()[0]

        assert status.state == INSTALLED_INCOMPATIBLE
        assert status.compatible is False
        assert "needs core >=99.0.0" in status.command

    def test_the_core_is_never_reported_as_an_extension(self, site):
        extensions, state = site
        state["apps"] = ["frappe", "albanna_ai_chat"]
        assert extensions.extension_states() == []

    def test_states_are_ordered_by_app_name(self, site, monkeypatch):
        extensions, state = site
        for name in ("zeta_mcp", "alpha_mcp"):
            install(monkeypatch, f"{name}.tools", make_module(f"{name}.tools", [spec(f"t_{name}")]))
        state["hooks"] = {
            "frappe_mcp_tools": {"zeta_mcp": "zeta_mcp.tools", "alpha_mcp": "alpha_mcp.tools"},
        }
        state["apps"] = ["frappe", "zeta_mcp", "alpha_mcp"]

        assert [s.name for s in extensions.extension_states()] == ["alpha_mcp", "zeta_mcp"]


# --------------------------------------------------------------------------
# core_version()
# --------------------------------------------------------------------------


class TestCoreVersion:
    def test_it_reads_the_running_package_version(self, site):
        extensions, _ = site
        import albanna_ai_chat

        assert extensions.core_version() == str(albanna_ai_chat.__version__)

    def test_a_package_with_no_version_is_empty_not_zero(self, site):
        """A version that parses as 0.0.0 sorts as the oldest thing in the room
        and silently wins every 'is an update available' question."""
        extensions, _ = site
        import albanna_ai_chat

        original = albanna_ai_chat.__version__
        del albanna_ai_chat.__version__
        try:
            assert extensions.core_version() == ""
        finally:
            albanna_ai_chat.__version__ = original
