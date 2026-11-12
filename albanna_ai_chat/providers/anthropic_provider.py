"""The Anthropic provider — ``/v1/messages`` over plain HTTP.

Two halves. :func:`to_request` and :func:`from_response` are pure — canonical
``Message`` objects in, Anthropic's wire shape out, and back — and they are
where this provider earns its module: Anthropic's shape differs from the
canonical one *structurally*, not just cosmetically.

The three differences, each of which is a request Anthropic rejects outright
if missed:

* **System messages go at the top level.** A ``system`` role inside
  ``messages`` is a 400 error, so the system message is lifted out into the
  ``system`` parameter and the rest are sent without it.
* **Everything in ``messages`` is a content block, not a string.** A tool
  call is a ``tool_use`` block on the assistant message; a tool result is a
  ``tool_result`` block on a *user* message — a result the runtime sends with
  ``role: tool`` has to be re-parented, because Anthropic has no tool role.
* **``max_tokens`` is required.** Omit it and the request is refused before
  the model is ever consulted.

:class:`AnthropicProvider` is the transport half, and it is twenty lines.
"""

from __future__ import annotations

from typing import Any

from albanna_ai_chat.chat.message import Message, Role
from albanna_ai_chat.core.provider import ERROR, ProviderResponse
from albanna_ai_chat.core.tools import ToolSpec
from albanna_ai_chat.providers import http

DEFAULT_MAX_TOKENS = 4096
DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


def to_request(
    messages: list[Message] | tuple[Message, ...],
    tools: list[ToolSpec] | tuple[ToolSpec, ...],
    model: str,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """The request body, in Anthropic's shape."""
    system = "\n\n".join(m.content for m in messages if m.role is Role.SYSTEM)
    conversation = [m for m in messages if m.role is not Role.SYSTEM]

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [_message_to_anthropic(m) for m in conversation],
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.parameters,
            }
            for spec in tools
        ]
    return payload


def _message_to_anthropic(message: Message) -> dict[str, Any]:
    """One canonical message, as an Anthropic ``messages`` entry.

    The tool result is the part that cannot be passed through: the canonical
    form gives it ``role: tool`` and Anthropic has no such role — a result is
    a *user* message carrying a ``tool_result`` block, addressed back to the
    model by the call's id.
    """
    if message.role is Role.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
            ],
        }

    role = "assistant" if message.role is Role.ASSISTANT else "user"
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    if message.role is Role.ASSISTANT:
        blocks.extend(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": call.arguments,
            }
            for call in message.tool_calls
        )
    # A message with neither text nor calls is an empty entry, which
    # Anthropic refuses — so it is sent as one empty text block, which it
    # accepts. An assistant turn that paused without saying anything is a
    # real shape, not a malformed one.
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    return {"role": role, "content": blocks}


def from_response(payload: dict[str, Any]) -> ProviderResponse:
    """The model's answer, from Anthropic's response shape."""
    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, list):
        return ProviderResponse(
            error="The provider answered with no content blocks.",
            reason=ERROR,
        )

    from albanna_ai_chat.chat.message import ToolCall

    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            text_parts.append(str(block.get("text") or ""))
        elif kind == "tool_use":
            try:
                calls.append(
                    ToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=dict(block.get("input") or {}),
                    )
                )
            except (ValueError, TypeError) as e:
                return ProviderResponse(
                    error=f"The provider returned a tool call that could not be read ({e}).",
                    reason=ERROR,
                )

    return ProviderResponse(text="\n".join(text_parts), tool_calls=tuple(calls))


class AnthropicProvider:
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
        url = f"{self._base_url}/v1/messages"
        headers = {
            "x-api-key": self._key,
            "anthropic-version": API_VERSION,
        }
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
