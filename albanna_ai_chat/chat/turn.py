"""The turn state machine — what a turn *is*, and what happens next.

Pure: no Frappe, no provider SDK, no socket.  A turn is a value object with a
state and a legal set of transitions, and every rule the runtime enforces is
expressed here where it can be tested.

What a turn is
--------------
Not a request that returns an answer.  A turn is a request that *starts* a
turn, a stream of progress events, and eventually an answer — and in between
it may call tools, ask the reader a question, and wait for a write to be
approved.  ``albanna``'s frontend module says it plainly: *"the socket is the
fast path… the poll is the guarantee."*  This module is the state machine both
of those transports drive.

Why a state machine and not a call stack
----------------------------------------
Because a turn *waits*.  It waits for a tool, for an approval, for a reader's
answer — and while it waits, the worker that started it is free to do
something else.  A turn modelled as nested function calls cannot survive that;
a turn modelled as an explicit state can be parked, resumed, and recovered
after a restart.  That is the whole reason this is a reducer and not a loop.

The guard that is not optional
------------------------------
``MAX_PROVIDER_CALLS``.  A turn that calls the provider, gets tool calls, runs
them, calls the provider again, gets more tool calls… is a turn that never
ends, and it ends by exhausting the context window rather than by producing
an answer.  The ceiling is enforced here, in the pure layer, so it cannot be
forgotten by an implementation that was in a hurry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from albanna_ai_chat.chat.message import Message, ToolCall

#: The most provider round-trips one turn may make.
#:
#: Each round-trip appends the tool results to the conversation, so the cost
#: is not only time — it is context.  A turn that needs more than this many
#: round-trips is a turn that should have been a flow, and it is refused
#: rather than allowed to quietly consume the window.
MAX_PROVIDER_CALLS = 12

#: The most tool calls one provider response may ask for.
#:
#: A response asking for fifty tool calls is either a model that has
#: misunderstood the task or a prompt that invited it.  Either way, running
#: all fifty before looking at any of them is how a single bad turn becomes
#: fifty bad writes.
MAX_TOOL_CALLS_PER_RESPONSE = 8


class TurnState(str, Enum):
    """Where a turn is.

    A ``str`` enum so it round-trips through the doctype layer and JSON
    without a mapping table.
    """

    #: No turn is running.
    IDLE = "idle"
    #: A turn is in flight — the provider has been called, or is about to be.
    RUNNING = "running"
    #: The model asked for tools; they are being run.
    AWAITING_TOOL = "awaiting_tool"
    #: A write is waiting for the reader to approve it.
    AWAITING_APPROVAL = "awaiting_approval"
    #: A question is waiting for the reader to answer it.
    AWAITING_ANSWER = "awaiting_answer"
    #: The turn produced its answer.
    DONE = "done"
    #: The turn failed.
    FAILED = "failed"
    #: The reader stopped it.
    STOPPED = "stopped"

    @property
    def is_terminal(self) -> bool:
        """True when no further event will move this turn."""
        return self in (TurnState.DONE, TurnState.FAILED, TurnState.STOPPED)

    @property
    def is_waiting(self) -> bool:
        """True when the turn is parked on the reader.

        This is the property the worker uses to decide it may go and do
        something else: a waiting turn owns no worker.
        """
        return self in (TurnState.AWAITING_APPROVAL, TurnState.AWAITING_ANSWER)


class TurnEvent(str, Enum):
    """What just happened."""

    START = "start"
    PROVIDER_TEXT = "provider_text"
    PROVIDER_TOOL_CALLS = "provider_tool_calls"
    PROVIDER_QUESTION = "provider_question"
    APPROVAL_REQUIRED = "approval_required"
    TOOLS_DONE = "tools_done"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REFUSED = "approval_refused"
    READER_ANSWERED = "reader_answered"
    READER_STOPPED = "reader_stopped"
    ERROR = "error"


class Action(str, Enum):
    """What the runtime should do next."""

    CALL_PROVIDER = "call_provider"
    RUN_TOOLS = "run_tools"
    WAIT_FOR_READER = "wait_for_reader"
    FINISH = "finish"
    FAIL = "fail"
    NOTHING = "nothing"


#: The legal transitions, as data.
#:
#: An event that is not listed for the current state is refused rather than
#: ignored, because a silently-ignored event is how a turn ends up in a state
#: nobody intended and nobody can explain.
_TRANSITIONS: dict[tuple[TurnState, TurnEvent], TurnState] = {
    # A reader's message starts a turn.
    (TurnState.IDLE, TurnEvent.START): TurnState.RUNNING,
    # The provider answered in words.
    (TurnState.RUNNING, TurnEvent.PROVIDER_TEXT): TurnState.DONE,
    # The provider asked for tools.
    (TurnState.RUNNING, TurnEvent.PROVIDER_TOOL_CALLS): TurnState.AWAITING_TOOL,
    # The provider asked the reader something.
    (TurnState.RUNNING, TurnEvent.PROVIDER_QUESTION): TurnState.AWAITING_ANSWER,
    # A tool run needs the reader's approval before it may proceed.
    (TurnState.AWAITING_TOOL, TurnEvent.APPROVAL_REQUIRED): TurnState.AWAITING_APPROVAL,
    # The tools finished; back to the provider with their results.
    (TurnState.AWAITING_TOOL, TurnEvent.TOOLS_DONE): TurnState.RUNNING,
    # The reader approved the write.
    (TurnState.AWAITING_APPROVAL, TurnEvent.APPROVAL_GRANTED): TurnState.RUNNING,
    # The reader refused.  The refusal is fed back to the model as a tool
    # result, so the turn continues rather than dying — a refused write is
    # information, not a failure.
    (TurnState.AWAITING_APPROVAL, TurnEvent.APPROVAL_REFUSED): TurnState.RUNNING,
    # The reader answered the question.
    (TurnState.AWAITING_ANSWER, TurnEvent.READER_ANSWERED): TurnState.RUNNING,
    # The reader stopped the turn, from any live state.
    (TurnState.RUNNING, TurnEvent.READER_STOPPED): TurnState.STOPPED,
    (TurnState.AWAITING_TOOL, TurnEvent.READER_STOPPED): TurnState.STOPPED,
    (TurnState.AWAITING_APPROVAL, TurnEvent.READER_STOPPED): TurnState.STOPPED,
    (TurnState.AWAITING_ANSWER, TurnEvent.READER_STOPPED): TurnState.STOPPED,
    # Anything live may fail.
    (TurnState.RUNNING, TurnEvent.ERROR): TurnState.FAILED,
    (TurnState.AWAITING_TOOL, TurnEvent.ERROR): TurnState.FAILED,
    (TurnState.AWAITING_APPROVAL, TurnEvent.ERROR): TurnState.FAILED,
    (TurnState.AWAITING_ANSWER, TurnEvent.ERROR): TurnState.FAILED,
}


class IllegalTransition(RuntimeError):
    """Raised when an event does not apply to the current state."""


def can_transition(state: TurnState, event: TurnEvent) -> bool:
    """True when *event* is legal from *state*."""
    return (state, event) in _TRANSITIONS


def next_state(state: TurnState, event: TurnEvent) -> TurnState:
    """The state *state* moves to on *event*.

    @raises IllegalTransition: naming the state and the event, so the log
        says what happened rather than only that something did.
    """
    target = _TRANSITIONS.get((state, event))
    if target is None:
        raise IllegalTransition(
            f"turn event {event.value!r} is not legal from state {state.value!r}"
        )
    return target


@dataclass
class Turn:
    """One turn in progress.

    Mutable, because a turn is a thing that *happens* over time rather than a
    value that is computed.  The state machine above is the pure half; this is
    the stateful half that carries what the runtime needs to resume.
    """

    conversation: str = ""
    state: TurnState = TurnState.IDLE
    #: How many provider round-trips this turn has made.
    provider_calls: int = 0
    #: The tool calls the last provider response asked for, not yet run.
    pending_calls: tuple[ToolCall, ...] = ()
    #: The call a write is waiting on approval for.
    awaiting_approval_for: ToolCall | None = None
    #: The question the reader is being asked, as the model phrased it.
    pending_question: dict[str, Any] = field(default_factory=dict)
    #: Why the turn failed, when it did.
    error: str = ""
    #: The messages this turn has produced, in order.
    messages: list[Message] = field(default_factory=list)

    # -- queries ---------------------------------------------------------

    @property
    def is_live(self) -> bool:
        """True when the turn can still move."""
        return not self.state.is_terminal

    @property
    def is_waiting(self) -> bool:
        """True when the turn is parked on the reader and owns no worker."""
        return self.state.is_waiting

    @property
    def exhausted(self) -> bool:
        """True when the turn has used up its provider round-trips."""
        return self.provider_calls >= MAX_PROVIDER_CALLS

    # -- transitions ------------------------------------------------------

    def apply(self, event: TurnEvent) -> "Turn":
        """Move this turn on *event*, and return it.

        @raises IllegalTransition: when the event does not apply.
        """
        if event is TurnEvent.APPROVAL_REQUIRED and self.awaiting_approval_for is None:
            # Record *which* write the reader is being asked about.  A turn
            # that parks without knowing what it waits on cannot be resumed —
            # and a turn that cannot be resumed cannot be recovered after a
            # restart, which is the whole reason this is a reducer.
            if self.pending_calls:
                self.awaiting_approval_for = self.pending_calls[0]
        self.state = next_state(self.state, event)
        return self

    def start(self, conversation: str) -> "Turn":
        self.conversation = conversation
        self.state = TurnState.RUNNING
        self.provider_calls = 0
        return self

    def record_provider_call(self) -> None:
        """Count one provider round-trip.

        Called *before* the call, so a turn that is refused for exhaustion is
        refused before the context window is spent rather than after.
        """
        self.provider_calls += 1

    def request_calls(self, calls: tuple[ToolCall, ...]) -> None:
        """Record the tool calls the provider asked for."""
        if len(calls) > MAX_TOOL_CALLS_PER_RESPONSE:
            raise IllegalTransition(
                f"provider asked for {len(calls)} tool calls in one response; "
                f"the ceiling is {MAX_TOOL_CALLS_PER_RESPONSE}"
            )
        self.pending_calls = tuple(calls)
        self.state = TurnState.AWAITING_TOOL

    def clear_calls(self) -> None:
        self.pending_calls = ()
        self.awaiting_approval_for = None

    # -- the decision the runtime asks for ---------------------------------

    def next_action(self) -> Action:
        """What the runtime should do next, given this turn's state.

        This is the single question the turn loop asks, and answering it here
        rather than in the runtime is what keeps the loop itself trivial —
        and what makes the loop's behaviour testable without a provider, a
        socket or a site.
        """
        if self.state is TurnState.IDLE:
            return Action.NOTHING
        if self.state is TurnState.RUNNING:
            return Action.CALL_PROVIDER
        if self.state is TurnState.AWAITING_TOOL:
            return Action.RUN_TOOLS
        if self.state in (TurnState.AWAITING_APPROVAL, TurnState.AWAITING_ANSWER):
            return Action.WAIT_FOR_READER
        if self.state is TurnState.DONE:
            return Action.FINISH
        if self.state is TurnState.FAILED:
            return Action.FAIL
        return Action.NOTHING  # STOPPED

    def guard(self) -> str | None:
        """Why this turn may not call the provider again, or ``None``.

        A guard rather than an exception, because the answer is fed back to
        the model as the turn's final content — a turn that says *"this needed
        too many steps"* is a turn the reader learns something from, while a
        turn that raises is a turn that shows an error dialog.
        """
        if self.exhausted:
            return (
                f"This turn needed more than {MAX_PROVIDER_CALLS} steps and was "
                "stopped. Break the request into smaller pieces, or use a flow "
                "if it is genuinely one multi-step job."
            )
        return None
