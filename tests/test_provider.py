"""Tests for the provider port — the one seam, and how it refuses.

What these verify is that a site with no provider configured fails *usefully*.
A turn that dies with a stack trace tells the reader nothing they can act on;
"No provider is configured" is a sentence an operator can fix.  The difference
between those two is the whole of this module's job.
"""

from __future__ import annotations

import pytest

from albanna_ai_chat.chat.message import Message
from albanna_ai_chat.core.provider import (
    ERROR,
    NOT_CONFIGURED,
    NullProvider,
    ProviderResponse,
    ScriptedProvider,
)
from albanna_ai_chat.core.tools import READ, ToolSpec


def spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Does the {name} thing.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        tier=READ,
    )


def conversation() -> list[Message]:
    return [Message.system("You are Albanna."), Message.user("what is open?")]


# --------------------------------------------------------------------------
# The null provider.
# --------------------------------------------------------------------------


class TestNullProvider:
    def test_it_refuses_rather_than_raising(self):
        """A refusal is a sentence the reader can be shown; a stack trace is not."""
        response = NullProvider().complete(conversation(), [spec("read_file")])
        assert response.ok is False
        assert response.error

    def test_the_refusal_names_the_setting_that_fixes_it(self):
        response = NullProvider().complete(conversation(), [])
        assert "provider" in response.error.lower()
        assert "Settings" in response.error

    def test_the_reason_is_not_configured(self):
        response = NullProvider().complete(conversation(), [])
        assert response.reason == NOT_CONFIGURED

    def test_a_custom_message_is_used_verbatim(self):
        response = NullProvider("Provider 'acme' has no implementation.").complete([], [])
        assert response.error == "Provider 'acme' has no implementation."

    def test_it_never_asks_for_tools(self):
        """A provider that cannot answer cannot ask for anything."""
        response = NullProvider().complete(conversation(), [spec("read_file")])
        assert response.wants_tools is False


# --------------------------------------------------------------------------
# The scripted provider — for tests.
# --------------------------------------------------------------------------


class TestScriptedProvider:
    def test_it_answers_from_the_script_in_order(self):
        provider = ScriptedProvider(
            [
                ProviderResponse(text="first"),
                ProviderResponse(text="second"),
            ]
        )
        assert provider.complete([], []).text == "first"
        assert provider.complete([], []).text == "second"

    def test_it_records_what_it_was_asked(self):
        """A test must be able to assert on the question, not only the answer."""
        provider = ScriptedProvider([ProviderResponse(text="ok")])
        messages = conversation()
        tools = [spec("read_file")]
        provider.complete(messages, tools)
        assert provider.calls[0]["messages"] == messages
        assert provider.calls[0]["tools"] == tools

    def test_it_refuses_when_the_script_runs_out(self):
        """That is how a test discovers it asked for more turns than it planned."""
        provider = ScriptedProvider([ProviderResponse(text="only one")])
        provider.complete([], [])
        response = provider.complete([], [])
        assert response.ok is False
        assert response.reason == ERROR

    def test_a_callable_entry_receives_the_question(self):
        seen = {}

        def answer(messages, tools):
            seen["count"] = len(messages)
            seen["tools"] = [t.name for t in tools]
            return ProviderResponse(text="computed")

        provider = ScriptedProvider([answer])
        provider.complete(conversation(), [spec("read_file")])
        assert seen["count"] == 2
        assert seen["tools"] == ["read_file"]

    def test_an_empty_script_refuses_immediately(self):
        provider = ScriptedProvider([])
        assert provider.complete([], []).ok is False


# --------------------------------------------------------------------------
# The response shape.
# --------------------------------------------------------------------------


class TestProviderResponse:
    def test_a_text_answer_is_ok_and_asks_for_nothing(self):
        response = ProviderResponse(text="Three orders are open.")
        assert response.ok is True
        assert response.wants_tools is False

    def test_a_tool_call_is_ok_and_asks_for_tools(self):
        from albanna_ai_chat.chat.message import ToolCall

        response = ProviderResponse(tool_calls=(ToolCall(id="c", name="read_file"),))
        assert response.ok is True
        assert response.wants_tools is True

    def test_an_error_is_not_ok(self):
        response = ProviderResponse(error="boom", reason=ERROR)
        assert response.ok is False

    def test_text_and_tool_calls_coexist(self):
        """A model that says "let me look that up" and then calls a tool is
        normal; the runtime keeps the sentence for the transcript."""
        from albanna_ai_chat.chat.message import ToolCall

        response = ProviderResponse(
            text="Let me check.",
            tool_calls=(ToolCall(id="c", name="read_file"),),
        )
        assert response.text == "Let me check."
        assert response.wants_tools is True
