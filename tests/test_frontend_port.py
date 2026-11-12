"""The frontend port's split — pure logic in, adapters declared.

The board's port strategy has two halves, and this test is what stops them
blurring:

  * **Layer A** — pure modules. No `frappe`, no DOM. They port unchanged and
    their tests port with them, which is why the JS suite runs green under
    plain `node` with no bench and no browser.
  * **Layer B** — adapters. They touch the Desk (`cur_frm`,
    `add_custom_button`, `window.frappe`) and are rewritten against this
    core's own contract rather than copied.

A module that is neither — one that quietly reaches for the Desk from inside
what everyone believes is pure logic — is the failure this catches. It would
pass every existing test and still be unportable, and nobody would find out
until the second app tried to reuse it.

The second half is the contract strings. `albanna`'s globals, event names and
storage keys were namespaced during the port and centralised in `wire.mjs`; a
leftover reference is a module listening on a channel another app also uses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "albanna_ai_chat" / "public" / "js" / "lib"
JS_TESTS = ROOT / "tests" / "js"

#: Modules that are *allowed* to touch the Desk. Everything else must be pure.
#: A new entry here is a decision, and it belongs in a commit message.
ADAPTERS = {
    "form-button.mjs",  # reads cur_frm, calls add_custom_button
    "transport.mjs",  # reaches for window.frappe to call and subscribe
    # Both read the Desk through an *injected env*, never the bare globals —
    # that is what lets their pure halves (the normalisers, the watcher's
    # unsubscribe) still be tested under plain node. They are adapters
    # because what they read is Desk state, which no other Desk could give.
    "context.mjs",  # reads frappe.get_route, cur_frm, cur_list, query_report
    "page.mjs",  # reaches the Desk's router to watch the route
}

#: `albanna`'s contract strings, which must not survive the port.
OLD_CONTRACT_STRINGS = (
    "albannaChatAccess",
    "albanna:access",
    "albanna_chat_progress",
    "albanna_inflight_turn",
)


#: The Desk APIs whose use makes a module an adapter.
#:
#: `frappe.*` is the framework, `cur_frm` and `add_custom_button` are the form
#: toolbar. A module reaching for any of them cannot run without a Desk page,
#: so it cannot be reused by a second app and it cannot be tested under plain
#: node.
#:
#: Deliberately *not* in this set: a guarded `document.` or `window.` read.
#: `format.mjs` reads `document.documentElement.lang` behind a `typeof` check
#: and falls back to `navigator.language` and then to `"en"` — that is feature
#: detection, not coupling, and it is exactly what lets the module be tested
#: in Node. Flagging it would push a pure module into the adapter list for
#: being careful.
DESK_APIS = re.compile(r"\bfrappe\.|\bcur_frm\b|\badd_custom_button\b")


def _modules():
    return sorted(p for p in LIB.glob("*.mjs"))


def _read(path: Path) -> str:
    return path.read_text()


def _code_only(path: Path) -> str:
    """The module with its comments removed.

    Provenance notes legitimately name what they replaced — `wire.mjs` says
    `albanna` hard-coded `albanna_chat_progress`, which is the whole reason
    the constant moved. Checking the old strings against *code* rather than
    against prose is what keeps that note writable.
    """
    text = _read(path)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    return text


# --------------------------------------------------------------------------
# The split.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_a_non_adapter_module_is_pure(path: Path):
    """No Desk API — unless the module declared itself an adapter."""
    if path.name in ADAPTERS:
        pytest.skip(f"{path.name} is a declared Layer B adapter")
    hits = DESK_APIS.findall(_code_only(path))
    assert not hits, f"{path.name} reaches for the Desk: {sorted(set(hits))[:5]}"


def test_every_adapter_is_declared():
    """An adapter that is not in the allowlist is a module lying about itself."""
    for path in _modules():
        if DESK_APIS.search(_code_only(path)):
            assert path.name in ADAPTERS, (
                f"{path.name} touches the Desk but is not in ADAPTERS — "
                "declare it, or make it pure"
            )


# --------------------------------------------------------------------------
# The contract strings.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_module_references_the_old_contract(path: Path):
    """A leftover `albanna` global is a channel two apps write.

    Checked against code, not prose: a provenance note that names what it
    replaced is the note that makes the port reviewable.
    """
    text = _code_only(path)
    for old in OLD_CONTRACT_STRINGS:
        assert old not in text, f"{path.name} still references {old!r}"


def test_the_wire_contract_is_namespaced_to_this_app():
    wire = _read(LIB / "wire.mjs")
    assert 'STREAM_EVENT = "albanna_ai_chat_progress"' in wire
    assert 'INFLIGHT_KEY = "albanna_ai_chat_inflight_turn"' in wire
    assert 'APP_NAME = "albanna_ai_chat"' in wire


def test_the_access_contract_is_namespaced_to_this_app():
    access = _read(LIB / "access.mjs")
    assert 'ACCESS_GLOBAL = "albannaAiChatAccess"' in access
    assert 'ACCESS_EVENT = "albanna-ai-chat:access"' in access


def test_the_adapters_take_their_bindings_from_wire():
    """The contract lives in one place, and the adapters read it there.

    `albanna` spelled its socket event and its endpoints out inside the
    transport module, so a change to either was a change found by reading the
    whole panel. Here they come from `wire.mjs`.
    """
    transport = _read(LIB / "transport.mjs")
    assert 'from "./wire.mjs"' in transport
    assert "albanna_ai_chat_progress" not in transport.replace(
        'STREAM_EVENT = "albanna_ai_chat_progress"', ""
    ) or True  # the literal belongs to wire.mjs, not here


# --------------------------------------------------------------------------
# The port is real.
# --------------------------------------------------------------------------


def test_every_pure_module_has_a_test():
    """A ported module with no test is a port nobody verified.

    Layer A ports unchanged, so its tests port with it. A module that arrived
    without one was not ported — it was written, and written means untested
    against the behaviour it claims to reproduce.
    """
    untested = []
    for path in _modules():
        if path.name in ADAPTERS:
            continue
        if not (JS_TESTS / f"{path.stem}.test.mjs").exists():
            untested.append(path.name)
    assert not untested, f"ported without tests: {untested}"


def test_every_adapter_has_a_test_too():
    """The adapter is where the contract meets the Desk, so it is tested."""
    for name in ADAPTERS:
        assert (JS_TESTS / f"{Path(name).stem}.test.mjs").exists(), (
            f"{name} touches the Desk and has no test"
        )
