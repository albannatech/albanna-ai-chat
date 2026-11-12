"""Tests for the Anthropic provider — the structural translation.

Anthropic's shape differs from the canonical one structurally, and each of
the three differences is a request the API rejects outright if missed: the
system message lifted to the top level, tool results re-parented as *user*
messages carrying ``tool_result`` blocks, and the required ``max_tokens``.
These tests are the assertion that all three are handled — and the
documentation of why each line exists.
"""

from __future__ import annotations

import pytest

from albanna_ai_chat.chat.message import Message, ToolCall
from albanna_ai_chat.core.provider import ERROR, REFUSED, ProviderResponse
from albanna_ai_chat.core.tools import READ, ToolSpec
from albanna_ai_chat.providers.anthropic_provider import (
    AnthropicProvider,
    from_response,
    to_request,
)


def spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Does the {name} thing.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        tier=READ,
    )


def a_conversation() -> list[Message]:
    return [Message.system("You are Albanna."), Message.user("what is open?")]


def an_answer_body(text: str = "Three orders are open.") -> dict:
    return {"content": [{"type": "text", "text": text}]}


# --------------------------------------------------------------------------
# to_request — the shape Anthropic answers to.
# --------------------------------------------------------------------------


class TestToRequest:
    def test_the_system_message_is_lifted_to_the_top_level(self):
        # A `system` role inside `messages` is a 400 error, so it is sent as
        # the `system` parameter and nowhere else.
        payload = to_request(a_conversation(), [], "claude-sonnet-4-5")
        assert payload["system"] == "You are Albanna."
        roles = [m["role"] for m in payload["messages"]]
        assert "system" not in roles

    def test_max_tokens_is_required_and_always_sent(self):
        payload = to_request(a_conversation(), [], "claude-sonnet-4-5")
        assert payload["max_tokens"] > 0

    def test_a_user_message_is_a_text_block(self):
        payload = to_request(a_conversation(), [], "claude-sonnet-4-5")
        entry = payload["messages"][0]
        assert entry["role"] == "user"
        assert entry["content"] == [{"type": "text", "text": "what is open?"}]

    def test_tools_carry_an_input_schema(self):
        payload = to_request(a_conversation(), [spec("read_file")], "claude-sonnet-4-5")
        tool = payload["tools"][0]
        assert tool["name"] == "read_file"
        assert tool["description"] == spec("read_file").description
        assert tool["input_schema"] == spec("read_file").parameters

    def test_a_tool_result_is_a_user_message_with_a_tool_result_block(self):
        # The canonical form gives a result `role: tool`; Anthropic has no
        # tool role, so the result is re-parented and addressed back by id.
        call = ToolCall(id="call_1", name="read_file", arguments={"file": "a"})
        conversation = [
            *a_conversation(),
            Message.assistant(tool_calls=(call,)),
            Message.tool_result(call, "the file's text"),
        ]
        payload = to_request(conversation, [], "claude-sonnet-4-5")

        result_entry = payload["messages"][-1]
        assert result_entry["role"] == "user"
        block = result_entry["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "call_1"
        assert block["content"] == "the file's text"

    def test_an_assistant_tool_call_is_a_tool_use_block(self):
        call = ToolCall(id="call_1", name="read_file", arguments={"file": "a"})
        conversation = [
            *a_conversation(),
            Message.assistant(content="Let me check.", tool_calls=(call,)),
        ]
        payload = to_request(conversation, [], "claude-sonnet-4-5")

        entry = payload["messages"][-1]
        assert entry["role"] == "assistant"
        kinds = [b["type"] for b in entry["content"]]
        assert kinds == ["text", "tool_use"]
        tool_use = entry["content"][1]
        assert tool_use["id"] == "call_1"
        assert tool_use["input"] == {"file": "a"}

    def test_an_empty_assistant_turn_still_carries_a_block(self):
        # An assistant turn that paused without saying anything is a real
        # shape, not a malformed one — but an empty content list is refused.
        conversation = [*a_conversation(), Message.assistant(content="")]
        payload = to_request(conversation, [], "claude-sonnet-4-5")
        entry = payload["messages"][-1]
        assert entry["content"] == [{"type": "text", "text": ""}]

    def test_several_system_messages_are_joined(self):
        conversation = [
            Message.system("First rule."),
            Message.user("hi"),
            Message.system("Second rule."),
        ]
        payload = to_request(conversation, [], "claude-sonnet-4-5")
        assert payload["system"] == "First rule.\n\nSecond rule."


# --------------------------------------------------------------------------
# from_response — the shape Anthropic answers in.
# --------------------------------------------------------------------------


class TestFromResponse:
    def test_a_text_answer(self):
        response = from_response(an_answer_body("Three orders are open."))
        assert response.ok is True
        assert response.text == "Three orders are open."

    def test_a_tool_use_block(self):
        body = {
            "content": [
                {"type": "text", "text": "Let me check."},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "read_file",
                    "input": {"file": "a.txt"},
                },
            ]
        }
        response = from_response(body)
        assert response.wants_tools is True
        assert response.text == "Let me check."
        assert response.tool_calls[0].id == "call_1"

    def test_no_content_is_an_error_not_a_crash(self):
        assert from_response({}).ok is False
        assert from_response({}).reason == ERROR

    def test_unknown_block_kinds_are_skipped_not_fatal(self):
        # The API adds block kinds over time; a kind this module has never
        # heard of is not a turn that dies.
        body = {
            "content": [
                {"type": "text", "text": "hi"},
                {"type": "thinking", "thinking": "hmm"},
            ]
        }
        response = from_response(body)
        assert response.text == "hi"

    def test_a_non_dict_payload_is_an_error(self):
        assert from_response("not a dict").ok is False


# --------------------------------------------------------------------------
# The transport.
# --------------------------------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class TestAnthropicProviderTransport:
    def _provider(self, transport) -> AnthropicProvider:
        return AnthropicProvider("sk-ant-test", "claude-sonnet-4-5", transport=transport)

    def test_the_request_carries_the_anthropic_headers(self):
        seen = {}

        def transport(url, headers=None, data=None, timeout=None):
            seen["url"] = url
            seen["headers"] = headers
            return ProviderResponse(), an_answer_body()

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.ok is True
        assert seen["url"].endswith("/v1/messages")
        assert seen["headers"]["x-api-key"] == "sk-ant-test"
        assert "anthropic-version" in seen["headers"]

    def test_an_http_error_comes_back_as_a_refusal(self):
        def transport(url, headers=None, data=None, timeout=None):
            return ProviderResponse(
                error="The provider refused the request: invalid x-api-key",
                reason=REFUSED,
            ), None

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.ok is False
        assert "invalid x-api-key" in response.error

    def test_a_successful_body_is_translated(self):
        def transport(url, headers=None, data=None, timeout=None):
            return ProviderResponse(), an_answer_body("Two orders.")

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.text == "Two orders."
