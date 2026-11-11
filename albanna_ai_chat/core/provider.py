"""The provider port — how the model is asked, without saying which model.

Pure: no Frappe, no SDK, no HTTP client.  A provider is a function from a
conversation and a tool set to a response, and that is the whole of it.

Why a port and not an import
----------------------------
``albanna`` shipped four providers — Anthropic, OpenAI, Ollama and a generic
HTTP one — behind a single ``base.py``.  The lesson generalises: the *shape* of
a model call is stable and small, and the *differences* between providers are
mechanical (auth header, URL, message dialect).  Putting the shape here means a
new provider is one small module rather than a change to the turn loop, and the
turn loop can be tested with a provider that answers deterministically.

What a response carries
-----------------------
``text`` and ``tool_calls``, and never both meaningfully.  A provider that
returns prose *and* asks for tools has given the runtime two instructions, and
the runtime must pick one — so the port says which wins: tool calls are acted
on, and the text is kept as the assistant's message content for the transcript.
A model that says "let me look that up" and then calls a tool is normal; a
runtime that discards the sentence is a transcript that reads as a gap.

The null provider
-----------------
:class:`NullProvider` refuses, and it refuses *loudly and specifically*.  A site
with no provider configured is a site where every turn would otherwise fail
with a stack trace, and the reader would be told nothing they could act on.
"No provider is configured" is a sentence an operator can fix; a 500 is not.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from albanna_ai_chat.chat.message import Message, ToolCall
from albanna_ai_chat.core.tools import ToolSpec

#: The reason a provider could not answer.
NOT_CONFIGURED = "not_configured"
REFUSED = "refused"
ERROR = "error"


@dataclass(frozen=True)
class ProviderResponse:
    """What the model said.

    ``tool_calls`` is acted on; ``text`` is kept as the assistant's message
    content either way, so a turn that calls a tool still has a transcript
    that reads as a sentence rather than a gap.
    """

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    #: Set when the provider could not answer at all.
    error: str = ""
    #: Which kind of failure, from the constants above.
    reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Provider(Protocol):
    """Asks a model for one turn's worth of thinking."""

    def complete(
        self,
        messages: list[Message] | tuple[Message, ...],
        tools: list[ToolSpec] | tuple[ToolSpec, ...],
    ) -> ProviderResponse:
        """Answer, or ask for tools.

        @param messages: the conversation so far, in canonical order
        @param tools: the tools this caller may use, already filtered by the
            authority layer — a provider never sees a tool the caller may not
            use, so it cannot ask for one
        @returns: the model's response
        """
        ...


class NullProvider:
    """The provider that is not configured yet.

    It refuses rather than raising, because a refusal is a sentence the reader
    can be shown and a stack trace is not.  The message names the setting that
    fixes it, so the operator is not left guessing which of a dozen
    configuration fields is the missing one.
    """

    def __init__(self, message: str = "") -> None:
        self._message = message or (
            "No model provider is configured for this site. Set a default "
            "provider and model in Albanna AI Chat Settings."
        )

    def complete(
        self,
        messages: list[Message] | tuple[Message, ...],
        tools: list[ToolSpec] | tuple[ToolSpec, ...],
    ) -> ProviderResponse:
        return ProviderResponse(error=self._message, reason=NOT_CONFIGURED)


class ScriptedProvider:
    """A provider that answers from a script — for tests.

    Each entry is either a :class:`ProviderResponse` or a callable taking the
    messages and tools, so a test can assert on what it was *asked* as well as
    control what it answers.  When the script runs out it refuses, which is how
    a test discovers it asked for more turns than it planned for.
    """

    def __init__(self, script: Iterable[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[Message] | tuple[Message, ...],
        tools: list[ToolSpec] | tuple[ToolSpec, ...],
    ) -> ProviderResponse:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
            }
        )
        if not self._script:
            return ProviderResponse(
                error="ScriptedProvider ran out of scripted responses.",
                reason=ERROR,
            )
        entry = self._script.pop(0)
        if callable(entry):
            return entry(list(messages), list(tools))
        return entry
