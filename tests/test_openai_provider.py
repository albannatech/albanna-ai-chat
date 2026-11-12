"""Tests for the OpenAI provider — the wire format, and every way it fails.

The translation is pure, so these tests run in under a second and touch no
network. What they pin down is the shape the provider actually answers in,
including the two quirks of the real API: tool-call arguments that arrive as
a JSON *string*, and a 200 body that is not what it promised to be.
"""

from __future__ import annotations

import json

import pytest

from albanna_ai_chat.chat.message import Message, ToolCall
from albanna_ai_chat.core.provider import ERROR, REFUSED, ProviderResponse
from albanna_ai_chat.core.tools import READ, ToolSpec
from albanna_ai_chat.providers import http
from albanna_ai_chat.providers.openai_provider import (
    DEFAULT_BASE_URL,
    OpenAIProvider,
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
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
            }
        ]
    }


# --------------------------------------------------------------------------
# to_request — the shape OpenAI answers to.
# --------------------------------------------------------------------------


class TestToRequest:
    def test_the_canonical_wire_form_passes_through(self):
        payload = to_request(a_conversation(), [], "gpt-4o")
        assert payload["model"] == "gpt-4o"
        assert payload["messages"] == [m.to_wire() for m in a_conversation()]

    def test_tools_carry_the_function_envelope(self):
        payload = to_request(a_conversation(), [spec("read_file")], "gpt-4o")
        tool = payload["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "read_file"
        assert tool["function"]["description"]
        assert tool["function"]["parameters"] == spec("read_file").parameters

    def test_a_bounded_answer(self):
        # A model that runs away is bounded by the field, so it is sent even
        # though OpenAI merely accepts it rather than requiring it.
        payload = to_request(a_conversation(), [], "gpt-4o", max_tokens=512)
        assert payload["max_tokens"] == 512


# --------------------------------------------------------------------------
# from_response — the shape OpenAI answers in.
# --------------------------------------------------------------------------


class TestFromResponse:
    def test_a_text_answer(self):
        response = from_response(an_answer_body("Three orders are open."))
        assert response.ok is True
        assert response.text == "Three orders are open."
        assert response.wants_tools is False

    def test_a_tool_call(self):
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": json.dumps({"file": "a.txt"}),
                                },
                            }
                        ],
                    }
                }
            ]
        }
        response = from_response(body)
        assert response.wants_tools is True
        assert response.tool_calls[0].name == "read_file"
        assert response.tool_calls[0].arguments == {"file": "a.txt"}

    def test_a_missing_tool_call_field_is_an_answer_without_tools(self):
        # `tool_calls` is absent or None on a plain answer — both are the
        # same thing, and neither is an error.
        body = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        assert from_response(body).wants_tools is False
        body["choices"][0]["message"]["tool_calls"] = None
        assert from_response(body).wants_tools is False

    def test_no_choices_is_an_error_not_a_crash(self):
        response = from_response({"choices": []})
        assert response.ok is False
        assert response.reason == ERROR

    def test_a_choice_with_no_message_is_an_error(self):
        response = from_response({"choices": [{"finish_reason": "stop"}]})
        assert response.ok is False

    def test_an_unreadable_tool_call_is_an_error_naming_the_problem(self):
        # Two ways a call can be unreadable: arguments that are not valid
        # JSON — which `ToolCall.from_wire` refuses — and a call with no
        # name at all.
        body = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "c",
                                "function": {
                                    "name": "read_file",
                                    "arguments": "{not json",
                                },
                            }
                        ],
                    }
                }
            ]
        }
        response = from_response(body)
        assert response.ok is False
        assert "tool call" in response.error

    def test_a_non_dict_payload_is_an_error(self):
        assert from_response("not a dict").ok is False


# --------------------------------------------------------------------------
# The transport — one HTTP call, and every way it can fail.
# --------------------------------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class TestOpenAIProviderTransport:
    def _provider(self, transport) -> OpenAIProvider:
        return OpenAIProvider("sk-test", "gpt-4o", transport=transport)

    def test_the_request_goes_to_the_completions_endpoint_with_the_key(self):
        seen = {}

        def transport(url, headers=None, data=None, timeout=None):
            seen["url"] = url
            seen["auth"] = headers.get("Authorization")
            return ProviderResponse(), an_answer_body()

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.ok is True
        assert seen["url"] == f"{DEFAULT_BASE_URL}/chat/completions"
        assert seen["auth"] == "Bearer sk-test"

    def test_a_401_is_a_refusal_with_the_providers_own_sentence(self):
        # The mapping from 401 to refusal is http.post's job (tested in
        # TestHttpTransport); what the provider adds is the pass-through —
        # the refusal, including its sentence, reaches the turn loop whole.
        def transport(url, headers=None, data=None, timeout=None):
            return ProviderResponse(
                error=(
                    "The provider refused the request: "
                    "billing is disabled for this project"
                ),
                reason=REFUSED,
            ), None

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.ok is False
        assert response.reason == REFUSED
        assert "billing is disabled" in response.error

    def test_a_429_is_a_refusal_that_names_rate_limiting(self):
        def transport(url, headers=None, data=None, timeout=None):
            return ProviderResponse(
                error="The provider is rate-limiting this site: slow down", reason=REFUSED
            ), None

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.reason == REFUSED
        assert "rate-limiting" in response.error

    def test_a_500_is_an_error_may_be_retried(self):
        def transport(url, headers=None, data=None, timeout=None):
            return ProviderResponse(error="overloaded", reason=ERROR), None

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.reason == ERROR
        assert "overloaded" in response.error

    def test_a_non_json_200_is_an_error(self):
        def transport(url, headers=None, data=None, timeout=None):
            return ProviderResponse(error="not JSON", reason=ERROR), None

        response = self._provider(transport).complete(a_conversation(), [])
        assert response.ok is False
        assert "not JSON" in response.error


class TestHttpTransport:
    """`http.post` itself — the seam the providers sit on.

    The exception mapping lives here, not in the provider classes: a
    provider's transport is one call to this function, and everything that
    can go wrong with the network is turned into a response before the
    provider sees it.
    """

    def _post(self, requests_post, **kwargs):
        return http.post(
            "https://example.test/v1/chat/completions",
            {"Authorization": "Bearer x"},
            {"model": "gpt-4o"},
            transport=requests_post,
            **kwargs,
        )

    def test_a_timeout_is_an_error_not_an_exception(self):
        import requests

        def requests_post(*args, **kwargs):
            raise requests.Timeout()

        response, body = self._post(requests_post)
        assert response.ok is False
        assert response.reason == ERROR
        assert "retried" in response.error
        assert body is None

    def test_a_connection_error_is_an_outage_not_a_refusal(self):
        import requests

        def requests_post(*args, **kwargs):
            raise requests.ConnectionError()

        response, body = self._post(requests_post)
        assert response.reason == ERROR
        assert "reached" in response.error

    def test_a_401_carries_the_providers_own_sentence(self):
        def requests_post(*args, **kwargs):
            return _FakeHTTPResponse(401, {"error": {"message": "bad key"}})

        response, body = self._post(requests_post)
        assert response.reason == REFUSED
        assert "bad key" in response.error

    def test_a_2xx_returns_the_parsed_body(self):
        def requests_post(*args, **kwargs):
            return _FakeHTTPResponse(200, {"choices": []})

        response, body = self._post(requests_post)
        assert response.ok is True
        assert body == {"choices": []}

    def test_the_body_is_sent_as_json_with_the_content_type(self):
        seen = {}

        def requests_post(url, headers=None, data=None, timeout=None):
            seen.update(url=url, headers=headers, data=data)
            return _FakeHTTPResponse(200, {})

        self._post(requests_post)
        assert seen["headers"]["Content-Type"] == "application/json"
        assert json.loads(seen["data"])["model"] == "gpt-4o"

    def test_a_404_page_is_not_rendered_into_a_chat_bubble(self):
        # The generic sentence wins over whatever HTML the 404 carried.
        def requests_post(url, headers=None, data=None, timeout=None):
            return _FakeHTTPResponse(404, "<html>Not Found</html>")

        response, body = self._post(requests_post)
        assert response.ok is False
        assert "404" in response.error
        assert "<html>" not in response.error
