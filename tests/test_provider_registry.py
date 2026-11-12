"""Tests for the provider registry — a configured name becomes a provider.

The registry imports Frappe, so it runs against a stub ``frappe`` installed
into ``sys.modules``, the same discipline ``test_file_backend.py`` applies.
The stub answers the two questions the registry asks: *what does the site's
config say* and *what is configured in Settings* — and everything it cannot
answer becomes a refusal naming the line that fixes it, which is exactly
what these tests assert.
"""

from __future__ import annotations

import sys
import types

import pytest


# --------------------------------------------------------------------------
# The stub
# --------------------------------------------------------------------------


_IMPORTED: dict = {}


@pytest.fixture()
def frappe_stub(monkeypatch):
    """A ``frappe`` module with site config and Settings, both writable.

    The registry is imported *after* the stub is installed — the real bench
    ``frappe`` is importable on this host, so a module-level import would
    bind it and the stub would never be consulted.
    """
    module = types.ModuleType("frappe")
    state = {"site_config": {}, "settings": None}
    module.get_site_config = lambda: state["site_config"]

    def get_single(doctype):
        if state["settings"] is None:
            raise Exception("no settings row exists yet")
        return state["settings"]

    module.get_single = get_single
    monkeypatch.setitem(sys.modules, "frappe", module)
    sys.modules.pop("albanna_ai_chat.providers.registry", None)

    import importlib

    _IMPORTED["registry"] = importlib.import_module("albanna_ai_chat.providers.registry")
    yield module
    sys.modules.pop("albanna_ai_chat.providers.registry", None)


from albanna_ai_chat.core.provider import NullProvider  # noqa: E402


class Settings:
    def __init__(self, provider="", model=""):
        self.default_provider = provider
        self.default_model = model


def provider_for(provider: str, model: str):
    """The registry's ``provider_for``, from the module the fixture imported.

    Requires the ``frappe_stub`` fixture: without it there is no stub and no
    freshly-imported registry to call.
    """
    registry = _IMPORTED.get("registry")
    assert registry is not None, "the frappe_stub fixture is required"
    return registry.provider_for(provider, model)


def site_config_key(provider: str) -> str:
    return f"ai_chat_{provider}_key"


# --------------------------------------------------------------------------
# The refusals — every way a site can be unconfigured.
# --------------------------------------------------------------------------


class TestRefusals:
    def test_no_setting_at_all_is_a_null_provider_with_a_sentence(self, frappe_stub):
        response = provider_for("", "")
        assert isinstance(response, NullProvider)
        assert "Settings" in response._message

    def test_an_unknown_provider_names_what_is_installed(self, frappe_stub):
        response = provider_for("claude-official", "claude-sonnet-4-5")
        assert isinstance(response, NullProvider)
        assert "claude-official" in response._message
        assert "openai" in response._message and "anthropic" in response._message

    def test_a_provider_without_a_model_refuses(self, frappe_stub):
        # A guessed model is a bill the operator did not authorise, so an
        # empty model refuses even when the provider and key are known.
        response = provider_for("openai", "")
        assert isinstance(response, NullProvider)
        assert "model" in response._message

    def test_a_provider_without_a_key_names_the_site_config_line(self, frappe_stub):
        response = provider_for("openai", "gpt-4o")
        assert isinstance(response, NullProvider)
        assert site_config_key("openai") in response._message
        assert "site_config.json" in response._message


# --------------------------------------------------------------------------
# The happy path — a configured name builds the right provider.
# --------------------------------------------------------------------------


class TestConstruction:
    def test_openai_is_built_with_the_key_and_model(self, frappe_stub):
        frappe_stub.get_site_config()["ai_chat_openai_key"] = "sk-test"
        provider = provider_for("openai", "gpt-4o")
        assert provider.__class__.__name__ == "OpenAIProvider"
        assert provider._key == "sk-test"
        assert provider._model == "gpt-4o"

    def test_anthropic_is_built_the_same_way(self, frappe_stub):
        frappe_stub.get_site_config()["ai_chat_anthropic_key"] = "sk-ant"
        provider = provider_for("anthropic", "claude-sonnet-4-5")
        assert provider.__class__.__name__ == "AnthropicProvider"
        assert provider._key == "sk-ant"

    def test_a_base_url_override_is_passed_through(self, frappe_stub):
        frappe_stub.get_site_config()["ai_chat_openai_key"] = "sk-test"
        frappe_stub.get_site_config()["ai_chat_openai_base_url"] = "https://proxy.internal/v1"
        provider = provider_for("openai", "gpt-4o")
        assert provider._base_url == "https://proxy.internal/v1"


# --------------------------------------------------------------------------
# The site config line — the one place a key may live.
# --------------------------------------------------------------------------


class TestSiteConfigKey:
    def test_the_line_is_spelled_from_the_registry_name(self):
        assert site_config_key("openai") == "ai_chat_openai_key"
        assert site_config_key("anthropic") == "ai_chat_anthropic_key"
