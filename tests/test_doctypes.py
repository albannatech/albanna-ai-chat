"""Tests for the doctype definitions — the Frappe-coupled half, checked
without Frappe.

The doctype JSON is data, so it can be read and asserted on under plain
``pytest``.  That matters because the doctypes mirror the pure layer's
enums — ``TurnState`` and ``Role`` — and a mirror that drifts is a conversation
stuck in a state the runtime does not recognise, or a message with a role the
runtime cannot route.  Both fail here, at build time, rather than at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from albanna_ai_chat.chat.message import Role
from albanna_ai_chat.chat.turn import (
    MAX_PROVIDER_CALLS,
    MAX_TOOL_CALLS_PER_RESPONSE,
    TurnState,
)

DOCTYPE_DIR = (
    Path(__file__).resolve().parent.parent
    / "albanna_ai_chat"
    / "ai_chat"
    / "doctype"
)


def load(doctype: str) -> dict:
    path = DOCTYPE_DIR / doctype / f"{doctype}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def options(doctype: str, fieldname: str) -> tuple[str, ...]:
    """A Select field's options, in the order the JSON declares them."""
    spec = load(doctype)
    for field in spec["fields"]:
        if field["fieldname"] == fieldname:
            return tuple(o for o in (field.get("options") or "").split("\n") if o)
    raise AssertionError(f"{doctype} has no field {fieldname!r}")


def fieldnames(doctype: str) -> set[str]:
    return {f["fieldname"] for f in load(doctype)["fields"]}


# --------------------------------------------------------------------------
# The JSON is valid and complete.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doctype",
    ["ai_chat_conversation", "ai_chat_message", "ai_chat_settings", "ai_chat_log"],
)
def test_every_doctype_json_is_valid(doctype):
    spec = load(doctype)
    assert spec["doctype"] == "DocType"
    assert spec["name"]
    assert spec["module"] == "AI Chat"
    assert isinstance(spec["fields"], list) and spec["fields"]


@pytest.mark.parametrize(
    "doctype",
    ["ai_chat_conversation", "ai_chat_message", "ai_chat_settings", "ai_chat_log"],
)
def test_every_doctype_has_a_python_controller(doctype):
    """A doctype with no controller is a doctype whose rules live nowhere."""
    path = DOCTYPE_DIR / doctype / f"{doctype}.py"
    assert path.exists(), f"{doctype} has no controller"
    assert path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize(
    "doctype",
    ["ai_chat_conversation", "ai_chat_message", "ai_chat_settings", "ai_chat_log"],
)
def test_every_doctype_has_an_init(doctype):
    path = DOCTYPE_DIR / doctype / "__init__.py"
    assert path.exists(), f"{doctype} has no __init__.py"


# --------------------------------------------------------------------------
# The mirrors cannot drift.
# --------------------------------------------------------------------------


def test_conversation_status_mirrors_turn_state():
    """A status the runtime does not recognise is a stuck conversation."""
    declared = set(options("ai_chat_conversation", "status"))
    states = {s.value for s in TurnState}
    assert declared == states, (
        f"missing from the doctype={sorted(states - declared)}, "
        f"not a TurnState={sorted(declared - states)}"
    )


def test_message_role_mirrors_message_role_enum():
    declared = set(options("ai_chat_message", "role"))
    roles = {r.value for r in Role}
    assert declared == roles, (
        f"missing from the doctype={sorted(roles - declared)}, "
        f"not a Role={sorted(declared - roles)}"
    )


def test_settings_limits_mirror_the_pure_ceilings():
    """A setting may lower a ceiling, never raise it past the pure layer's."""
    spec = load("ai_chat_settings")
    defaults = {f["fieldname"]: f.get("default") for f in spec["fields"]}
    assert int(defaults["max_provider_calls"]) == MAX_PROVIDER_CALLS
    assert int(defaults["max_tool_calls_per_response"]) == MAX_TOOL_CALLS_PER_RESPONSE


# --------------------------------------------------------------------------
# The privacy shape.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("doctype", ["ai_chat_conversation", "ai_chat_message"])
def test_private_doctypes_are_if_owner(doctype):
    """Chat history is private to the reader who started it."""
    spec = load(doctype)
    roles = {p["role"] for p in spec["permissions"]}
    assert "Albanna Chat User" in roles
    for perm in spec["permissions"]:
        if perm["role"] == "Albanna Chat User":
            assert perm.get("if_owner") == 1, (
                f"{doctype} grants Albanna Chat User without if_owner — "
                "that widens it for everyone"
            )


def test_settings_is_a_single_and_system_manager_only():
    """One settings row, and only an administrator may change it."""
    spec = load("ai_chat_settings")
    assert spec.get("issingle") == 1
    roles = {p["role"] for p in spec["permissions"]}
    assert roles == {"System Manager"}


def test_the_log_is_not_if_owner():
    """The audit trail is the app's bookkeeping, not the reader's private data."""
    spec = load("ai_chat_log")
    for perm in spec["permissions"]:
        assert perm.get("if_owner") != 1, (
            "AI Chat Log is an audit trail; making it if_owner hides it from "
            "the administrator who needs it for support"
        )


# --------------------------------------------------------------------------
# The fields the runtime depends on.
# --------------------------------------------------------------------------


def test_a_conversation_carries_what_a_turn_needs_to_resume():
    """A turn that cannot be resumed cannot be recovered after a restart."""
    names = fieldnames("ai_chat_conversation")
    assert {"status", "turn_snapshot", "active_extension"} <= names


def test_a_message_carries_the_tool_call_address():
    """A result with no address is a result the model cannot match."""
    names = fieldnames("ai_chat_message")
    assert {"role", "content", "tool_call_id", "tool_name"} <= names


def test_the_log_event_vocabulary_is_closed():
    """A closed vocabulary is what makes the log countable."""
    events = set(options("ai_chat_log", "event"))
    assert "turn_failed" in events
    assert "write_refused" in events
    assert len(events) >= 8
