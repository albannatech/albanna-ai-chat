"""The Desk asset contract — the rule whose failure is invisible.

``app_include_js = ["albanna-ai-chat.bundle.js"]`` is not a path.  Frappe
resolves it through ``bundled_asset()`` (frappe/utils/jinja_globals.py), which
requires two things of the name:

  * it contains ``.bundle.``
  * it does not start with ``/assets``

Break either and the lookup falls through to the literal string, the request
goes to the site root, the file is not there, the browser logs a 404, and
nothing on the page says so.  The feature is simply absent — on every page,
for every user, forever.  That is the failure mode these tests exist to
prevent, and it is why the rule is asserted rather than documented.

The second half is drift: the names in ``hooks.py`` and the entries in
``build.mjs`` are two lists that must agree.  A bundle the build does not
produce is a name that resolves to nothing.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "albanna_ai_chat" / "hooks.py"
BUILD = ROOT / "build.mjs"
PUBLIC = ROOT / "albanna_ai_chat" / "public"


def _load_hooks():
    spec = importlib.util.spec_from_file_location("_aac_hooks", HOOKS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hooks = _load_hooks()


# --------------------------------------------------------------------------
# The names Frappe is given.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("attr", ["app_include_js", "app_include_css"])
def test_every_declared_asset_carries_the_bundle_marker(attr):
    """Without ``.bundle.`` the hashed URL is never resolved."""
    for name in getattr(hooks, attr) or []:
        assert ".bundle." in name, f"{attr} entry {name!r} lacks '.bundle.'"


@pytest.mark.parametrize("attr", ["app_include_js", "app_include_css"])
def test_no_declared_asset_is_an_absolute_assets_path(attr):
    """A path starting with ``/assets`` skips the lookup entirely."""
    for name in getattr(hooks, attr) or []:
        assert not name.startswith("/assets"), (
            f"{attr} entry {name!r} starts with /assets — it bypasses "
            "bundled_asset() and is served from a URL that never changes"
        )


def test_the_app_declares_at_least_one_script_and_one_stylesheet():
    assert hooks.app_include_js, "no Desk script declared"
    assert hooks.app_include_css, "no Desk stylesheet declared"


# --------------------------------------------------------------------------
# The build produces what the names promise.
# --------------------------------------------------------------------------


def _build_entry_names() -> set[str]:
    """The bundle base names ``build.mjs`` declares, e.g. ``albanna-ai-chat``."""
    text = BUILD.read_text()
    return set(re.findall(r'name:\s*"([^"]+)"', text))


def test_every_declared_asset_has_a_build_entry():
    """A name the build does not produce resolves to nothing.

    This is the drift check: ``hooks.py`` and ``build.mjs`` are two lists that
    must agree, and nothing else in the repo notices when they stop.
    """
    declared = set()
    for attr in ("app_include_js", "app_include_css"):
        for name in getattr(hooks, attr) or []:
            declared.add(name.split(".bundle.")[0])
    built = _build_entry_names()
    missing = declared - built
    assert not missing, f"declared in hooks.py but not built: {sorted(missing)}"


def test_every_build_entry_has_a_source_file():
    """An entry with no source is a build that fails on a fresh clone."""
    text = BUILD.read_text()
    for match in re.finditer(r'from:\s*"([^"]+)"', text):
        source = PUBLIC / match.group(1)
        assert source.exists(), f"build entry source missing: {match.group(1)}"


def test_the_build_script_exists_and_is_the_documented_one():
    assert BUILD.exists(), "build.mjs missing — the pipeline was never written down"
    package = ROOT / "package.json"
    assert package.exists(), "package.json missing"
    assert "esbuild" in package.read_text(), "esbuild is not a declared devDependency"


# --------------------------------------------------------------------------
# The RTL twin.
#
# ``bundled_asset()`` prefixes ``rtl_`` for right-to-left users and looks that
# up in the merged assets.json + assets-rtl.json.  A missing entry falls
# through to the literal string and the stylesheet 404s — for Arabic users,
# who are the primary audience.
# --------------------------------------------------------------------------


def test_the_build_emits_an_rtl_twin_for_css():
    text = BUILD.read_text()
    assert "rtl_" in text, "the build does not emit an RTL stylesheet twin"
    assert "assets-rtl.json" in text, "the build does not register the RTL twin"


def test_the_stylesheet_uses_logical_properties():
    """One file serving both directions is what makes the RTL twin a copy.

    If the source used physical properties (``left``, ``margin-left``) the RTL
    twin would need a flipping pass, and a copy would be wrong in a way no
    test here could catch.
    """
    css = (PUBLIC / "css" / "albanna-ai-chat.css").read_text()
    physical = re.findall(r"(?<![-\w])(?:margin|padding|border)-(?:left|right)\s*:", css)
    assert not physical, f"physical properties found: {physical[:5]}"
