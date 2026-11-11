"""Tests for the message model — the shape a conversation has before any
provider, socket or site is involved."""

from __future__ import annotations

import pytest

from albanna_ai_chat.chat import (
    Message,
    Role,
    ToolCall,
    estimate_tokens,
    to_wire,
)


# --------------------------------------------------------------------------
# Roles.
# --------------------------------------------------------------------------


def test_roles_serialise_as_their_own_value():
    """A str enum keeps the doctype and wire layers from needing a map."""
    assert Role.USER.value == "user"
    assert Role.USER == "user"
    assert Role.ASSISTANT.is_model is True
    assert Role.USER.is_model is False


# --------------------------------------------------------------------------
# Tool calls.
# --------------------------------------------------------------------------


def test_tool_call_parses_the_nested_provider_shape():
    """OpenAI-shaped: arguments arrive as a JSON *string*."""
    call = ToolCall.from_wire(
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"file": "/files/a.pdf"}'},
        }
    )
    assert call.name == "read_file"
    assert call.arguments == {"file": "/files/a.pdf"}


def test_tool_call_parses_the_flat_shape():
    """Some providers emit arguments already as an object."""
    call = ToolCall.from_wire({"id": "c2", "name": "edit_file", "arguments": {"x": 1}})
    assert call.name == "edit_file"
    assert call.arguments == {"x": 1}


def test_tool_call_with_no_name_is_refused():
    """A call with no name cannot be run, and silently dropping it loses it."""
    with pytest.raises(ValueError, match="no name"):
        ToolCall.from_wire({"id": "c3", "arguments": {}})


def test_tool_call_with_malformed_arguments_is_refused():
    """A malformed payload is a contract violation, not a string to re-parse."""
    with pytest.raises(ValueError, match="not valid JSON"):
        ToolCall.from_wire({"id": "c4", "name": "read_file", "arguments": "{not json"})


def test_tool_call_arguments_must_be_an_object():
    with pytest.raises(ValueError, match="must be an object"):
        ToolCall.from_wire({"id": "c5", "name": "read_file", "arguments": [1, 2]})


def test_empty_arguments_string_becomes_an_empty_object():
    """A provider that sends "" for no arguments is not an error."""
    call = ToolCall.from_wire({"id": "c6", "name": "read_file", "arguments": ""})
    assert call.arguments == {}


def test_tool_call_round_trips_through_the_wire():
    call = ToolCall(id="c7", name="read_file", arguments={"file": "x"})
    wire = call.to_wire()
    assert wire["function"]["name"] == "read_file"
    assert ToolCall.from_wire(wire) == call


# --------------------------------------------------------------------------
# Messages.
# --------------------------------------------------------------------------


def test_a_tool_result_must_name_the_call_it_answers():
    """A result with no address is a result the model cannot match."""
    with pytest.raises(ValueError, match="must name the call"):
        Message(role=Role.TOOL, content="done")


def test_a_tool_result_may_be_addressed_by_name_alone():
    """Some providers match on name rather than id."""
    m = Message(role=Role.TOOL, content="done", tool_name="read_file")
    assert m.is_tool_result


def test_assistant_message_with_tool_calls_still_carries_content():
    """A provider that gets tool_calls and no content key rejects the request."""
    m = Message.assistant(tool_calls=(ToolCall(id="c", name="read_file"),))
    wire = m.to_wire()
    assert "content" in wire
    assert wire["content"] == ""
    assert wire["tool_calls"][0]["function"]["name"] == "read_file"


def test_tool_result_wire_carries_both_id_and_name():
    """A provider that needs the one it was not given is a provider that fails."""
    m = Message.tool_result(ToolCall(id="c8", name="read_file"), "the text")
    wire = m.to_wire()
    assert wire["tool_call_id"] == "c8"
    assert wire["name"] == "read_file"
    assert wire["role"] == "tool"


def test_a_whole_conversation_serialises_in_order():
    msgs = [
        Message.system("You are Albanna."),
        Message.user("what is open?"),
        Message.assistant(tool_calls=(ToolCall(id="c9", name="list_docs"),)),
        Message.tool_result(ToolCall(id="c9", name="list_docs"), "3 orders"),
        Message.assistant("Three orders are open."),
    ]
    wire = to_wire(msgs)
    assert [w["role"] for w in wire] == ["system", "user", "assistant", "tool", "assistant"]


# --------------------------------------------------------------------------
# The context guard.
# --------------------------------------------------------------------------


def test_token_estimate_grows_with_content():
    small = estimate_tokens([Message.user("hi")])
    big = estimate_tokens([Message.user("x" * 4000)])
    assert big > small


def test_token_estimate_counts_tool_arguments():
    """Arguments are part of the context, and they are the expensive part."""
    call = ToolCall(id="c", name="read_file", arguments={"file": "y" * 400})
    with_call = estimate_tokens([Message.assistant(tool_calls=(call,))])
    without = estimate_tokens([Message.assistant()])
    assert with_call > without
