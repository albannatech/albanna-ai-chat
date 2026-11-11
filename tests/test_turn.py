"""Tests for the turn state machine.

Every test here is a rule the runtime enforces, expressed without a provider,
a socket or a site.  That is the point of the split: the turn loop's
*behaviour* is decided here, so it can be decided correctly before anything
that could go wrong is wired to it.
"""

from __future__ import annotations

import pytest

from albanna_ai_chat.chat import (
    MAX_PROVIDER_CALLS,
    MAX_TOOL_CALLS_PER_RESPONSE,
    Action,
    IllegalTransition,
    Message,
    Turn,
    TurnEvent,
    TurnState,
    ToolCall,
    can_transition,
    next_state,
)


def call(name: str = "read_file", cid: str = "c1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments={})


def live_turn() -> Turn:
    return Turn().start("conv-1")


# --------------------------------------------------------------------------
# The happy path.
# --------------------------------------------------------------------------


def test_a_turn_starts_running():
    t = Turn().start("conv-1")
    assert t.state is TurnState.RUNNING
    assert t.next_action() is Action.CALL_PROVIDER


def test_a_text_answer_finishes_the_turn():
    t = live_turn().apply(TurnEvent.PROVIDER_TEXT)
    assert t.state is TurnState.DONE
    assert t.next_action() is Action.FINISH


def test_tool_calls_park_the_turn_until_they_are_run():
    t = live_turn()
    t.request_calls((call(),))
    assert t.state is TurnState.AWAITING_TOOL
    assert t.next_action() is Action.RUN_TOOLS


def test_running_the_tools_returns_to_the_provider():
    t = live_turn()
    t.request_calls((call(),))
    t.clear_calls()
    t.apply(TurnEvent.TOOLS_DONE)
    assert t.state is TurnState.RUNNING
    assert t.next_action() is Action.CALL_PROVIDER


def test_a_full_round_trip():
    """Ask, call a tool, answer — the shape of almost every turn."""
    t = live_turn()
    t.request_calls((call(),))
    t.clear_calls()
    t.apply(TurnEvent.TOOLS_DONE)
    t.apply(TurnEvent.PROVIDER_TEXT)
    assert t.state is TurnState.DONE


# --------------------------------------------------------------------------
# Waiting on the reader.
# --------------------------------------------------------------------------


def test_a_question_parks_the_turn_on_the_reader():
    t = live_turn().apply(TurnEvent.PROVIDER_QUESTION)
    assert t.state is TurnState.AWAITING_ANSWER
    assert t.next_action() is Action.WAIT_FOR_READER
    assert t.is_waiting is True


def test_an_answer_resumes_the_turn():
    t = live_turn().apply(TurnEvent.PROVIDER_QUESTION)
    t.apply(TurnEvent.READER_ANSWERED)
    assert t.state is TurnState.RUNNING


def test_a_write_waits_for_approval():
    t = live_turn()
    t.request_calls((call("write_file"),))
    t.apply(TurnEvent.APPROVAL_REQUIRED)
    assert t.state is TurnState.AWAITING_APPROVAL
    assert t.next_action() is Action.WAIT_FOR_READER


def test_approval_resumes_the_turn():
    t = live_turn()
    t.request_calls((call("write_file"),))
    t.apply(TurnEvent.APPROVAL_REQUIRED)
    t.apply(TurnEvent.APPROVAL_GRANTED)
    assert t.state is TurnState.RUNNING


def test_a_refusal_is_information_not_a_failure():
    """A refused write is fed back to the model; the turn continues."""
    t = live_turn()
    t.request_calls((call("write_file"),))
    t.apply(TurnEvent.APPROVAL_REQUIRED)
    t.apply(TurnEvent.APPROVAL_REFUSED)
    assert t.state is TurnState.RUNNING
    assert t.is_live is True


# --------------------------------------------------------------------------
# Stopping and failing.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        TurnState.RUNNING,
        TurnState.AWAITING_TOOL,
        TurnState.AWAITING_APPROVAL,
        TurnState.AWAITING_ANSWER,
    ],
)
def test_the_reader_may_stop_from_any_live_state(state):
    """A stop that only works from some states is a stop that sometimes hangs."""
    assert can_transition(state, TurnEvent.READER_STOPPED)
    assert next_state(state, TurnEvent.READER_STOPPED) is TurnState.STOPPED


def test_a_stopped_turn_is_terminal():
    t = live_turn().apply(TurnEvent.READER_STOPPED)
    assert t.state.is_terminal is True
    assert t.is_live is False


def test_an_error_fails_the_turn_from_any_live_state():
    t = live_turn().apply(TurnEvent.ERROR)
    assert t.state is TurnState.FAILED
    assert t.next_action() is Action.FAIL


def test_a_terminal_turn_does_not_move_again():
    """A finished turn must not accept more events."""
    t = live_turn().apply(TurnEvent.PROVIDER_TEXT)
    with pytest.raises(IllegalTransition):
        t.apply(TurnEvent.START)


# --------------------------------------------------------------------------
# Illegal transitions are refused, not ignored.
# --------------------------------------------------------------------------


def test_an_idle_turn_cannot_answered_a_question():
    """A silently-ignored event is how a turn ends up somewhere nobody meant."""
    with pytest.raises(IllegalTransition, match="not legal"):
        next_state(TurnState.IDLE, TurnEvent.READER_ANSWERED)


def test_a_done_turn_cannot_run_tools():
    with pytest.raises(IllegalTransition):
        next_state(TurnState.DONE, TurnEvent.TOOLS_DONE)


def test_the_error_names_the_state_and_the_event():
    """The log must say what happened, not only that something did."""
    with pytest.raises(IllegalTransition, match="reader_answered.*idle|idle.*reader_answered"):
        next_state(TurnState.IDLE, TurnEvent.READER_ANSWERED)


# --------------------------------------------------------------------------
# The guards.
# --------------------------------------------------------------------------


def test_too_many_tool_calls_in_one_response_is_refused():
    """Fifty calls in one turn is fifty writes before anybody looks."""
    t = live_turn()
    with pytest.raises(IllegalTransition, match="ceiling"):
        t.request_calls(tuple(call(f"t{i}", f"c{i}") for i in range(MAX_TOOL_CALLS_PER_RESPONSE + 1)))


def test_the_provider_call_ceiling_is_enforced():
    """A turn that never ends ends by exhausting the context window."""
    t = live_turn()
    for _ in range(MAX_PROVIDER_CALLS):
        t.record_provider_call()
    assert t.exhausted is True
    assert t.guard() is not None
    assert "smaller pieces" in t.guard()


def test_a_turn_under_the_ceiling_has_no_guard():
    t = live_turn()
    t.record_provider_call()
    assert t.guard() is None


def test_the_guard_is_a_sentence_the_reader_learns_from():
    """A guard that raises shows an error dialog; one that explains teaches."""
    t = live_turn()
    for _ in range(MAX_PROVIDER_CALLS):
        t.record_provider_call()
    guard = t.guard()
    assert "flow" in guard


# --------------------------------------------------------------------------
# Resumability — the reason this is a reducer and not a call stack.
# --------------------------------------------------------------------------


def test_a_waiting_turn_owns_no_worker():
    """This is the property that lets a parked turn free its worker."""
    t = live_turn().apply(TurnEvent.PROVIDER_QUESTION)
    assert t.is_waiting is True
    t.apply(TurnEvent.READER_ANSWERED)
    assert t.is_waiting is False


def test_a_turn_carries_what_it_needs_to_resume():
    """A turn that cannot be resumed cannot be recovered after a restart."""
    t = live_turn()
    t.request_calls((call("write_file", "c42"),))
    t.apply(TurnEvent.APPROVAL_REQUIRED)
    assert t.awaiting_approval_for is not None
    assert t.awaiting_approval_for.id == "c42"
    assert t.pending_question == {}


def test_a_turn_records_its_messages_in_order():
    t = live_turn()
    t.messages.append(Message.user("hello"))
    t.messages.append(Message.assistant("hi"))
    assert [m.role.value for m in t.messages] == ["user", "assistant"]
