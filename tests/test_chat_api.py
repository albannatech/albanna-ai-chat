"""Tests for the chat API's argument coercion.

The API imports Frappe, so these tests install a stub. What they verify is the
one coercion that matters: Frappe hands whitelisted arguments over as *strings*,
and ``bool("false")`` is True. A helper that got that wrong would approve every
write a reader refused — which is not a bug a reader would report, because from
their side the button simply appeared not to work.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def chat_api(monkeypatch):
    """A stub Frappe, and the chat API module imported against it."""
    module = types.ModuleType("frappe")

    # Frappe's translation function. The API imports it at module level, so a
    # stub without it fails on import rather than on the call under test.
    module._ = lambda text, *a, **kw: text

    # The API imports the settings doctype for its default prompt, and that
    # doctype imports Frappe's Document base class. A stub frappe is not a
    # package, so the submodules have to be registered by hand.
    model = types.ModuleType("frappe.model")
    document = types.ModuleType("frappe.model.document")

    class Document:
        pass

    document.Document = Document
    model.document = document
    module.model = model
    monkeypatch.setitem(sys.modules, "frappe.model", model)
    monkeypatch.setitem(sys.modules, "frappe.model.document", document)

    module.local = types.SimpleNamespace(site="test.localhost")
    module.session = types.SimpleNamespace(user="reader@example.com")

    # `frappe.whitelist` is a decorator, and the API applies it at import time.
    def whitelist(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    module.whitelist = whitelist
    module.get_roles = lambda user=None: ()
    module.get_all = lambda *a, **kw: []
    module.get_doc = lambda *a, **kw: None
    module.get_single = lambda *a, **kw: None
    module.db = types.SimpleNamespace(
        set_value=lambda *a, **kw: None,
        get_value=lambda *a, **kw: None,
    )
    module.enqueue = lambda *a, **kw: None
    module.throw = lambda *a, **kw: (_ for _ in ()).throw(Exception(a[0] if a else ""))
    module.PermissionError = PermissionError
    monkeypatch.setitem(sys.modules, "frappe", module)

    for name in (
        "albanna_ai_chat.api.chat",
        "albanna_ai_chat.api",
        "albanna_ai_chat.services.turn_loop",
        "albanna_ai_chat.services",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    from albanna_ai_chat.api import chat

    return chat


class TestTruthy:
    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "off", "", "  "])
    def test_the_strings_that_mean_false(self, chat_api, value):
        """``bool("false")`` is True, which would approve every refused write."""
        assert chat_api._truthy(value) is False

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on"])
    def test_the_strings_that_mean_true(self, chat_api, value):
        assert chat_api._truthy(value) is True

    def test_a_real_boolean_passes_through(self, chat_api):
        assert chat_api._truthy(True) is True
        assert chat_api._truthy(False) is False

    def test_none_is_false(self, chat_api):
        assert chat_api._truthy(None) is False

    def test_an_unrecognised_string_is_false(self, chat_api):
        """An unrecognised answer is not a yes. The safe direction to be wrong in."""
        assert chat_api._truthy("maybe") is False

    def test_whitespace_is_trimmed(self, chat_api):
        assert chat_api._truthy("  true  ") is True
        assert chat_api._truthy("  false  ") is False


class TestMayChat:
    def test_an_administrator_may_always_chat(self, chat_api, monkeypatch):
        monkeypatch.setattr(chat_api.frappe.session, "user", "Administrator")
        assert chat_api._may_chat() is True

    def test_a_reader_with_the_role_may_chat(self, chat_api, monkeypatch):
        monkeypatch.setattr(chat_api.frappe, "get_roles", lambda user=None: ["Albanna Chat User"])
        assert chat_api._may_chat() is True

    def test_a_reader_without_the_role_may_not(self, chat_api, monkeypatch):
        monkeypatch.setattr(chat_api.frappe, "get_roles", lambda user=None: ["Employee"])
        assert chat_api._may_chat() is False

    def test_a_reader_with_no_roles_may_not(self, chat_api, monkeypatch):
        monkeypatch.setattr(chat_api.frappe, "get_roles", lambda user=None: [])
        assert chat_api._may_chat() is False
