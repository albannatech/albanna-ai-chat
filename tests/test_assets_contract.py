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


# --------------------------------------------------------------------------
# The panel bundle.
#
# The panel is a *second* bundle, fetched on the first click rather than loaded
# with the page — a global hook is paid on every Desk page load, so the
# framework itself must not be in it. That makes it a second entry point, a
# second source file, and a second set of names that can drift from the first.
# --------------------------------------------------------------------------

PANEL_VUE = PUBLIC / "js" / "panel" / "SideChat.vue"


def test_the_panel_is_a_separate_build_entry():
    """A panel loaded with the page is a framework paid on every page load."""
    names = _build_entry_names()
    assert "albanna-ai-chat-panel" in names, "the panel has no build entry"


def test_the_panel_entry_is_a_vue_component():
    text = BUILD.read_text()
    assert ".vue" in text, "no build entry points at a .vue source"
    assert PANEL_VUE.exists(), "the panel component is missing"


def test_the_build_can_compile_vue():
    """esbuild has no `.vue` loader; the pipeline has to supply one."""
    text = BUILD.read_text()
    assert "compiler-sfc" in text, "the build does not compile single-file components"
    assert "vuePlugin" in text, "the Vue plugin is not wired into the build"
    package = (ROOT / "package.json").read_text()
    assert '"vue"' in package, "vue is not a declared devDependency"


def test_the_panel_carries_no_style_block():
    """Every rule lives in the one CSS bundle both directions emit from.

    A `<style>` block in a component would need its own extraction pass in the
    build and its own output file — a second place to look for a rule.

    Matched at the start of a line, because an SFC block is a top-level block
    and the word also appears in this file's own prose about the decision.
    """
    source = PANEL_VUE.read_text()
    blocks = re.findall(r"^<style[\s>]", source, flags=re.MULTILINE)
    assert not blocks, "the panel carries a <style> block; styles belong in the CSS bundle"


def test_the_panel_is_a_view_over_the_lib_modules():
    """The whole point of the port: the component holds no logic of its own."""
    source = PANEL_VUE.read_text()
    imports = re.findall(r'from\s+"(\.\./lib/[^"]+)"', source)
    assert len(imports) >= 8, f"the panel imports only {len(imports)} lib modules"
    for path in imports:
        target = (PANEL_VUE.parent / path).resolve()
        assert target.exists(), f"the panel imports a module that does not exist: {path}"


def test_every_class_the_panel_uses_is_answered_by_the_stylesheet():
    """A class with no rule is a component that renders unstyled.

    This is the drift guard for the decision to keep styles out of the
    components: naming a class in the template and forgetting the stylesheet is
    exactly the failure that decision makes possible, and nothing else in the
    repo notices it.
    """
    source = PANEL_VUE.read_text()
    css = (PUBLIC / "css" / "albanna-ai-chat.css").read_text()

    used = set()
    for match in re.finditer(r'class="([^"]+)"', source):
        for name in match.group(1).split():
            # A Vue binding is not a literal class name.
            if "{" in name or "$" in name:
                continue
            used.add(name)
    # The dynamic per-role class is built in the template; check its prefix.
    used.add("albanna-ai-chat-turn--user")

    missing = sorted(name for name in used if f".{name}" not in css)
    assert not missing, f"classes used by the panel with no rule in the stylesheet: {missing}"


# --------------------------------------------------------------------------
# The launcher resolves the panel from assets.json — and that is one fact
# written down twice, once by the build and once by `lib/wire.mjs`. Two
# copies of one fact drift, and the drift is silent: the launcher looks a key
# up that the build never wrote, the panel 404s on every Desk page, and
# nothing on the page says why.
# --------------------------------------------------------------------------

WIRE = PUBLIC / "js" / "lib" / "wire.mjs"


def test_the_builds_assets_keys_agree_with_the_wire_keys():
    """Every bundle the build registers, `wire.mjs` names under the same key."""
    import albanna_ai_chat.public  # noqa: F401 — package exists

    build_text = BUILD.read_text()
    # The entry names are the only source of the assets.json keys.
    entry_names = set(re.findall(r'name:\s*"([^"]+)"', build_text))
    wire_text = WIRE.read_text()

    assert "albanna-ai-chat" in entry_names
    assert "albanna-ai-chat-panel" in entry_names, "the panel has no build entry"

    # `PANEL_BUNDLE_KEY` must be spelled from the bundle base, not from
    # APP_NAME — the underscore/hyphen split is the drift this test exists
    # for, and it was caught by it once already.
    assert '`${BUNDLE_BASE}-panel.bundle.js`' in wire_text, (
        "PANEL_BUNDLE_KEY is not derived from BUNDLE_BASE"
    )
    assert 'BUNDLE_BASE = "albanna-ai-chat"' in wire_text, (
        "BUNDLE_BASE does not name the build's bundle base"
    )


def test_the_launcher_never_hardcodes_a_panel_url():
    """A URL spelled in code is right until the first rebuild changes the hash.

    After that the panel 404s on every Desk page, silently, forever. The URL
    must come from `frappe.boot.assets_json`, which Frappe refreshes on every
    page load.
    """
    entry = (PUBLIC / "js" / "albanna-ai-chat.mjs").read_text()
    # No literal dist path, and the resolution goes through boot's assets map.
    assert "/dist/" not in entry, "the launcher spells a dist path — it will go stale"
    assert "assets_json" in entry, "the launcher does not read the assets map"
    assert "panelBundleUrl" in entry


def test_the_panel_bundle_is_an_iife_the_launcher_can_inject():
    """An ESM script injected without `type="module"` does not execute at all.

    The panel is fetched by injecting a classic `<script>` tag, so the bundle
    must be an IIFE that registers its mount function on the global named in
    `lib/wire.mjs` — which is what makes the two bundles able to talk.
    """
    build_text = BUILD.read_text()
    assert 'iife: true' in build_text, "the panel entry is not built as an IIFE"
    assert 'entry.iife ? "iife" : "esm"' in build_text, (
        "the build does not honour the per-entry format"
    )

    mount = (PUBLIC / "js" / "panel" / "mount.mjs").read_text()
    wire_text = WIRE.read_text()
    match = re.search(r'ALBANNA_PANEL_GLOBAL\s*=\s*"([^"]+)"', wire_text)
    assert match, "wire.mjs does not name the mount global"
    assert match.group(1) in mount, (
        "the mount shim registers a global that does not match wire.mjs"
    )


def test_the_launcher_asks_the_server_instead_of_guessing_visibility():
    """A reader who may not chat gets no widget at all — not a disabled one.

    The old `shouldRender()` stub answered yes unconditionally, which is the
    answer the *server* is supposed to give, because only it knows the
    reader's roles.
    """
    entry = (PUBLIC / "js" / "albanna-ai-chat.mjs").read_text()
    assert "shouldRender" not in entry, "the visibility stub is still in the launcher"
    assert "ENDPOINTS.access" in entry, "the launcher does not ask the server"
    assert "publishAccess" in entry, "the launcher does not publish the answer"
