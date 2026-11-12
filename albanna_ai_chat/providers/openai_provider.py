"""The OpenAI provider — ``chat/completions`` over plain HTTP.

Two halves. :func:`to_request` and :func:`from_response` are pure: canonical
``Message`` objects in, the provider's wire shape out, and back. They import
no Frappe and touch no network, so the wire format is asserted by tests that
run in under a second. :class:`OpenAIProvider` is the transport half, and it
is twenty lines.

The canonical wire form in :mod:`albanna_ai_chat.chat.message` is already
OpenAI-shaped — ``role``/``content``/``tool_calls`` with the nested
``function`` object — so ``to_request`` is mostly assembly rather than
translation, and the interesting half is :func:`from_response`.
"""

from __future__ import annotations

from typing import Any

from albanna_ai_chat.chat.message import Message
from albanna_ai_chat.core.provider import ERROR, ProviderResponse
from albanna_ai_chat.core.tools import ToolSpec
from albanna_ai_chat.providers import http

#: The default ceiling on a single answer, in tokens. Anthropic requires the
#: field and OpenAI merely accepts it; sending it to both keeps one number in
#: one place, and a model that runs away is bounded by it.
DEFAULT_MAX_TOKENS = 4096

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def to_request(
    messages: list[Message] | tuple[Message, ...],
    tools: list[ToolSpec] | tuple[ToolSpec, ...],
    model: str,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """The request body, in OpenAI's shape.

    The canonical wire form is this provider's own shape, so the messages go
    through unchanged; the tools are wrapped in the ``{"type": "function",
    "function": …}`` envelope OpenAI expects.
    """
    return {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [m.to_wire() for m in messages],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in tools
        ],
    }


def from_response(payload: dict[str, Any]) -> ProviderResponse:
    """The model's answer, from OpenAI's response shape.

    Tolerant of the two things the API actually does: an answer with no tool
    calls (``tool_calls`` absent or ``None``), and an argument payload that
    arrived as a JSON *string* — which is how OpenAI carries it, and which
    ``ToolCall.from_wire`` re-parses.
    """
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        return ProviderResponse(
            error="The provider answered with no choices.",
            reason=ERROR,
        )

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ProviderResponse(
            error="The provider answered with a choice that has no message.",
            reason=ERROR,
        )

    from albanna_ai_chat.chat.message import ToolCall

    raw_calls = message.get("tool_calls") or []
    calls = []
    for raw in raw_calls:
        try:
            calls.append(ToolCall.from_wire(raw))
        except (ValueError, KeyError, TypeError) as e:
            return ProviderResponse(
                error=f"The provider returned a tool call that could not be read ({e}).",
                reason=ERROR,
            )

    return ProviderResponse(
        text=str(message.get("content") or ""),
        tool_calls=tuple(calls),
    )


class OpenAIProvider:
    """The transport half — one HTTP call, and every way it can fail."""

    def __init__(
        self,
        key: str,
        model: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        transport=http.post,
    ) -> None:
        self._key = key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._transport = transport

    def complete(
        self,
        messages: list[Message] | tuple[Message, ...],
        tools: list[ToolSpec] | tuple[ToolSpec, ...],
    ) -> ProviderResponse:
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._key}"}
        payload = to_request(
            messages,
            tools,
            self._model,
            max_tokens=self._max_tokens,
        )
        response, body = self._transport(url, headers, payload)
        if response.reason or response.error:
            return response
        return from_response(body)
