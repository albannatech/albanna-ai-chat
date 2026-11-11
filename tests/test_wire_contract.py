"""The wire contract, checked from both sides.

`wire.mjs` is the one place the frontend's assumptions about the server live.
That centralisation is only worth something if the two sides cannot drift, and
a JS file cannot read a Python enum — so this test reads both.

What drifts, and what it costs
------------------------------
* **PHASES** mirrors `chat.turn.TurnState`. A phase the server emits and the
  widget does not know is a turn the panel cannot render: it sits in
  "running" forever, the Stop button works, and nothing says why.
* **ROLES** mirrors `AI Chat Message.role`'s options. A role the runtime does
  not recognise is a message the panel cannot place in the transcript.
* **ENDPOINTS** mirrors the whitelisted functions in `api/chat.py`. An
  endpoint the server does not serve is a button that does nothing, and the
  failure is a 404 in a console nobody opens.

Each is asserted rather than documented, because a list that lives in two
languages is a list that disagrees the first time one side is edited.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WIRE = ROOT / "albanna_ai_chat" / "public" / "js" / "lib" / "wire.mjs"
API_CHAT = ROOT / "albanna_ai_chat" / "api" / "chat.py"
MESSAGE_DOCTYPE = (
    ROOT / "albanna_ai_chat" / "ai_chat" / "doctype" / "ai_chat_message" / "ai_chat_message.json"
)


def _js_const(name: str) -> list[str]:
    """A `export const NAME = [...]` array of strings, read out of wire.mjs."""
    text = WIRE.read_text()
    match = re.search(rf"export const {name} = \[(.*?)\];", text, re.DOTALL)
    assert match, f"{name} not found in wire.mjs"
    return re.findall(r'"([^"]+)"', match.group(1))


def _js_endpoints() -> dict[str, str]:
    """The ENDPOINTS object, as name -> resolved dotted path.

    The values are template literals (`` `${APP_NAME}.api.chat.access` ``), so
    `${APP_NAME}` is substituted with the constant's own value — which is the
    point of writing them that way, and the reason a naive read gets it wrong.
    """
    text = WIRE.read_text()
    app_match = re.search(r'export const APP_NAME = "([^"]+)"', text)
    assert app_match, "APP_NAME not found in wire.mjs"
    app_name = app_match.group(1)

    match = re.search(r"export const ENDPOINTS = \{(.*?)\n\};", text, re.DOTALL)
    assert match, "ENDPOINTS not found in wire.mjs"
    found = re.findall(r"(\w+):\s*`([^`]+)`", match.group(1))
    return {name: path.replace("${APP_NAME}", app_name) for name, path in found}


# --------------------------------------------------------------------------
# Phases.
# --------------------------------------------------------------------------


def test_js_phases_match_the_python_turn_state():
    from albanna_ai_chat.chat.turn import TurnState

    js_phases = _js_const("PHASES")
    py_phases = [state.value for state in TurnState]
    assert js_phases == py_phases, (
        f"wire.mjs PHASES {js_phases} != TurnState {py_phases} — "
        "a phase the server emits and the widget does not know is a turn "
        "the panel cannot render"
    )


def test_js_phases_are_unique():
    phases = _js_const("PHASES")
    assert len(phases) == len(set(phases)), "a phase declared twice"


# --------------------------------------------------------------------------
# Roles.
# --------------------------------------------------------------------------


def test_js_roles_match_the_doctype_options():
    doctype = json.loads(MESSAGE_DOCTYPE.read_text())
    options = None
    for field in doctype.get("fields", []):
        if field.get("fieldname") == "role":
            options = field.get("options", "")
            break
    assert options is not None, "AI Chat Message has no `role` field"

    py_roles = [line.strip() for line in options.splitlines() if line.strip()]
    js_roles = _js_const("ROLES")
    assert js_roles == py_roles, (
        f"wire.mjs ROLES {js_roles} != doctype options {py_roles} — "
        "a role the runtime does not recognise is a message the panel "
        "cannot place in the transcript"
    )


# --------------------------------------------------------------------------
# Endpoints.
# --------------------------------------------------------------------------


def test_every_js_endpoint_is_served_by_the_api():
    """An endpoint the server does not serve is a button that does nothing."""
    source = API_CHAT.read_text()
    served = set(re.findall(r"^def (\w+)\(", source, re.MULTILINE))

    for name, dotted in _js_endpoints().items():
        module, _, function = dotted.rpartition(".")
        assert module == "albanna_ai_chat.api.chat", (
            f"endpoint {name} points at {module}, not albanna_ai_chat.api.chat"
        )
        assert function in served, (
            f"endpoint {name} -> {function} is not defined in api/chat.py"
        )


def test_every_whitelisted_api_function_is_declared_in_wire():
    """The other direction: a served endpoint the widget cannot reach.

    Less harmful than the reverse — it is dead code rather than a dead
    button — but it is still a contract that says one thing and does
    another, and it is free to check.
    """
    source = API_CHAT.read_text()
    declared = set(_js_endpoints().values())

    for match in re.finditer(r"@frappe\.whitelist\(\)\s*\ndef (\w+)\(", source):
        function = match.group(1)
        dotted = f"albanna_ai_chat.api.chat.{function}"
        assert dotted in declared, (
            f"{function} is whitelisted but not declared in wire.mjs ENDPOINTS"
        )
