"""``discover()`` keys by app name, and every consumer depends on it.

This is a regression test for a bug that only appears on a real site.  The
Frappe-free suite validates manifests, and a manifest is not a hook — so
nothing here could catch a loader that keyed its discovery by the hook's
*value* instead of the *app*.

The bug had three consequences, all silent:

* ``extension_states()`` compared a module path against a list of app names,
  so every extension was reported as **not installed**;
* ``load_registry()`` tagged every spec with ``"…​.manifest"`` instead of the
  app, so an uninstall removed **nothing**;
* ``only_activated`` compared a module path against app names, so an
  **unactivated** extension's tools reached the model.

All three come from one wrong key, which is why the test asserts the key
rather than any one of the symptoms.
"""

import sys
import types

import pytest

from albanna_ai_chat.services import extensions


class FakeHooks:
    """Stands in for ``frappe.get_hooks``.

    Frappe returns a flat list for most hooks and a dict for a few; both
    shapes are exercised, because the loader has to survive either.
    """

    def __init__(self, value):
        self.value = value

    def __call__(self, hook, app_name=None):
        return self.value


@pytest.fixture
def patch_hooks(monkeypatch):
    def _install(value):
        monkeypatch.setattr(extensions.frappe, "get_hooks", FakeHooks(value))

    return _install


# ---------------------------------------------------------------------------
# The key is the app name
# ---------------------------------------------------------------------------


def test_a_list_of_hook_values_is_keyed_by_app(patch_hooks):
    patch_hooks(["healthcare_mcp.tools.manifest"])
    assert extensions.discover() == {"healthcare_mcp": "healthcare_mcp.tools.manifest"}


def test_a_dict_of_hooks_is_keyed_by_the_dict_key(patch_hooks):
    # Frappe returns {app: value} for some hooks, and the key *is* the app —
    # even when the value's first segment is something else entirely.
    patch_hooks({"a_mcp": "a.tools"})
    assert extensions.discover() == {"a_mcp": "a.tools"}


def test_a_list_of_hook_values_is_keyed_by_the_first_segment(patch_hooks):
    # A flat list carries no app name, so it is taken from the value.
    patch_hooks(["healthcare_mcp.tools.manifest"])
    assert extensions.discover() == {"healthcare_mcp": "healthcare_mcp.tools.manifest"}


def test_the_key_is_the_first_dotted_segment(patch_hooks):
    patch_hooks(["a.b.c.d"])
    assert list(extensions.discover()) == ["a"]


def test_no_hooks_means_no_extensions(patch_hooks):
    patch_hooks([])
    assert extensions.discover() == {}


def test_an_empty_value_is_dropped(patch_hooks):
    patch_hooks(["", "healthcare_mcp.tools.manifest"])
    assert extensions.discover() == {"healthcare_mcp": "healthcare_mcp.tools.manifest"}


# ---------------------------------------------------------------------------
# The consumers get an app name they can compare
# ---------------------------------------------------------------------------


def test_the_key_is_comparable_against_installed_apps(patch_hooks, monkeypatch):
    # The symptom that surfaced this: installed=False for an installed app.
    patch_hooks(["healthcare_mcp.tools.manifest"])
    monkeypatch.setattr(extensions, "installed_apps", lambda: ["frappe", "healthcare_mcp"])
    discovered = extensions.discover()
    assert set(discovered) <= set(extensions.installed_apps())


def test_the_key_is_comparable_against_activated_apps(patch_hooks, monkeypatch):
    # The other symptom: only_activated could not filter, because it compared
    # a module path against app names.
    patch_hooks(["healthcare_mcp.tools.manifest"])
    monkeypatch.setattr(extensions, "activated_apps", lambda: {"healthcare_mcp"})
    discovered = extensions.discover()
    assert set(discovered) <= extensions.activated_apps()


def test_provenance_is_the_app_not_the_module(patch_hooks):
    # The third symptom: a spec tagged "…​.manifest" is a spec an uninstall
    # cannot find.
    patch_hooks(["healthcare_mcp.tools.manifest"])
    app, target = next(iter(extensions.discover().items()))
    assert app == "healthcare_mcp"
    assert target == "healthcare_mcp.tools.manifest"
    assert "." not in app
