"""The message model — what a conversation is made of.

Pure: no Frappe, no DOM, no provider SDK.  A ``Message`` is a value object
that can be constructed, compared, serialised to a provider's wire format and
asserted on, all under plain ``pytest``.

Why the wire format lives here and not in the provider
------------------------------------------------------
Every chat provider speaks roughly the same dialect — a list of messages,
each with a role and content, plus tool calls and tool results.  The
*differences* are small and mechanical: one calls the assistant's turn
``assistant`` and another ``model``; one nests tool results under
``tool_call_id`` and another under ``name``.  Keeping the canonical shape
here means each provider adapter is a thin translation rather than a second
model of what a conversation is, and a bug in the translation is a bug in one
small function rather than in the shape of the whole app.

The roles
---------
``SYSTEM``     the assembled prompt — core instructions, then the active
               extension's agent persona, then its task prompts
``USER``       what the reader said
``ASSISTANT``  what the model said, including any tool calls it asked for
``TOOL``       the result of one tool call, addressed back to the model

``TOOL`` is a role and not a field on ``ASSISTANT`` because a turn with three
tool calls has three results, and they arrive in an order the model must be
able to match back to the calls it made.  ``tool_call_id`` is that match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Who is speaking.

    A ``str`` enum so it serialises to JSON without a custom encoder and
    compares equal to its own value — ``Role.USER == "user"`` — which keeps
    the doctype layer and the wire layer from needing a mapping table.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

    @property
    def is_model(self) -> bool:
        """True for the roles the model itself produces."""
        return self in (Role.ASSISTANT, Role.TOOL)


@dataclass(frozen=True)
class ToolCall:
    """One tool the model asked to run.

    ``id`` is the provider's own handle for the call, and it is what lets a
    result be matched back to the request.  ``arguments`` is the parsed JSON
    object — parsed here rather than passed through as a string, because a
    malformed argument payload is a contract violation the validator should
    catch, not a string the handler has to defensively re-parse.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, separators=(",", ":"), default=str),
            },
        }

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> "ToolCall":
        """Parse a provider's tool call.

        Tolerant of the two shapes providers actually emit: the OpenAI nested
        ``{"id":…, "function": {"name":…, "arguments": "…"}}`` and the flatter
        ``{"id":…, "name":…, "arguments": {…}}``.  A provider that emits
        neither is a provider bug, and it raises rather than silently
        producing a call with no name.
        """
        fn = raw.get("function") or {}
        name = fn.get("name") or raw.get("name") or ""
        if not name:
            raise ValueError(f"tool call carries no name: {raw!r}")
        arguments = fn.get("arguments", raw.get("arguments", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as e:
                raise ValueError(f"tool call {name!r} arguments are not valid JSON: {e}") from e
        if not isinstance(arguments, dict):
            raise ValueError(f"tool call {name!r} arguments must be an object, got {type(arguments).__name__}")
        return cls(id=str(raw.get("id") or ""), name=name, arguments=arguments)


@dataclass(frozen=True)
class Message:
    """One message in a conversation."""

    role: Role
    content: str = ""
    #: The tool calls the model asked for, on an ``ASSISTANT`` message.
    tool_calls: tuple[ToolCall, ...] = ()
    #: Which call a ``TOOL`` message answers.
    tool_call_id: str = ""
    #: The tool's name, on a ``TOOL`` message — carried alongside the id
    #: because some providers match on name and some on id, and a provider
    #: that needs the one it was not given is a provider that fails.
    tool_name: str = ""
    #: Provenance of the message, for the transcript: ``"reader"``,
    #: ``"model"``, or the tool's source.
    source: str = ""

    def __post_init__(self) -> None:
        if self.role is Role.TOOL and not self.tool_call_id and not self.tool_name:
            raise ValueError(
                "a TOOL message must name the call it answers — a result with "
                "no address is a result the model cannot match"
            )

    @property
    def is_tool_result(self) -> bool:
        return self.role is Role.TOOL

    def to_wire(self) -> dict[str, Any]:
        """The canonical provider wire form.

        ``content`` is always present, even when empty, because a provider
        that receives an assistant message with tool calls and no ``content``
        key will reject the whole request — and the error names a field the
        caller never set.
        """
        wire: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.tool_calls:
            wire["tool_calls"] = [call.to_wire() for call in self.tool_calls]
        if self.role is Role.TOOL:
            wire["tool_call_id"] = self.tool_call_id
            if self.tool_name:
                wire["name"] = self.tool_name
        return wire

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role=Role.SYSTEM, content=content, source="core")

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role=Role.USER, content=content, source="reader")

    @classmethod
    def assistant(
        cls,
        content: str = "",
        tool_calls: tuple[ToolCall, ...] = (),
    ) -> "Message":
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls, source="model")

    @classmethod
    def tool_result(cls, call: ToolCall, content: str) -> "Message":
        return cls(
            role=Role.TOOL,
            content=content,
            tool_call_id=call.id,
            tool_name=call.name,
            source=call.name,
        )


def to_wire(messages: list[Message] | tuple[Message, ...]) -> list[dict[str, Any]]:
    """A whole conversation, in canonical wire form."""
    return [m.to_wire() for m in messages]


def estimate_tokens(messages: list[Message] | tuple[Message, ...]) -> int:
    """A rough token estimate, for the context-window guard.

    Deliberately crude — roughly four characters per token — because its only
    job is to answer *"is this conversation about to fall off the cliff"*, and
    a precise count that requires a tokenizer per provider is a dependency
    for a question that does not need one.  The guard that uses it errs toward
    trimming early.
    """
    total = 0
    for m in messages:
        total += len(m.content or "") // 4
        for call in m.tool_calls:
            total += len(json.dumps(call.arguments, default=str)) // 4
            total += len(call.name) // 4
    return total
