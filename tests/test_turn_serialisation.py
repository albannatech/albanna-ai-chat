"""Tests for turn serialisation — the round-trip a resume depends on.

The turn loop imports Frappe, so these tests install a stub. What they verify is
the property the whole resumable design rests on: a turn parked on the reader
can be rebuilt from its conversation, with everything it needs to continue.

A turn that loses its pending calls on the way through the cache is a turn that
re-runs work it already did, or skips work it never did. Both are silent, and
both are found here rather than by a reader whose approval did nothing.
"""

from __future__ import annotations

import sys
import types

import pytest

from albanna_ai_chat.chat.message import ToolCall
from albanna_ai_chat.chat.turn import Turn, TurnState


@pytest.fixture
def store(monkeypatch):
    """A stub Frappe whose database is a dict of conversations."""
    conversations: dict[str, dict] = {}

    module = types.ModuleType("frappe")

    class _DB:
        def set_value(self, doctype, name, values, update_modified=True):
            row = conversations.setdefault(name, {"name": name})
            row.update(values)

        def get_value(self, doctype, name, field):
            row = conversations.get(name)
            if not row:
                return None
            if isinstance(field, (list, tuple)):
                return {f: row.get(f) for f in field}
            return row.get(field)

    module.db = _DB()
    module.local = types.SimpleNamespace(site="test.localhost")
    module.get_all = lambda *a, **kw: []
    module.get_doc = lambda *a, **kw: None
    module.get_single = lambda *a, **kw: None
    module.get_roles = lambda user=None: ()
    module.session = types.SimpleNamespace(user="reader@example.com")
    monkeypatch.setitem(sys.modules, "frappe", module)

    for name in (
        "albanna_ai_chat.services.turn_loop",
        "albanna_ai_chat.services",
        "albanna_ai_chat.services.reach",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    from albanna_ai_chat.services import turn_loop

    return turn_loop, conversations


def a_turn(**kw) -> Turn:
    turn = Turn().start("conv-1")
    for key, value in kw.items():
        setattr(turn, key, value)
    return turn


# --------------------------------------------------------------------------
# The round-trip.
# --------------------------------------------------------------------------


class TestRoundTrip:
    def test_the_state_survives(self, store):
        loop, conversations = store
        turn = a_turn()
        turn.apply("provider_tool_calls")
        loop.save_turn(turn)

        assert loop.load_turn("conv-1").state is TurnState.AWAITING_TOOL

    def test_the_provider_call_count_survives(self, store):
        """A turn that forgets how many round-trips it has made can loop forever."""
        loop, _ = store
        turn = a_turn()
        turn.record_provider_call()
        turn.record_provider_call()
        loop.save_turn(turn)

        assert loop.load_turn("conv-1").provider_calls == 2

    def test_the_pending_calls_survive(self, store):
        """Losing them re-runs work already done, or skips work never done."""
        loop, _ = store
        turn = a_turn()
        turn.request_calls(
            (
                ToolCall(id="c1", name="read_file", arguments={"file": "a"}),
                ToolCall(id="c2", name="edit_file", arguments={"file": "b"}),
            )
        )
        loop.save_turn(turn)

        loaded = loop.load_turn("conv-1")
        assert [c.id for c in loaded.pending_calls] == ["c1", "c2"]
        assert loaded.pending_calls[0].arguments == {"file": "a"}

    def test_the_approval_being_waited_on_survives(self, store):
        """A turn that forgets what it is waiting on cannot be resumed."""
        loop, _ = store
        turn = a_turn()
        turn.request_calls((ToolCall(id="c42", name="write_file"),))
        turn.apply("approval_required")
        loop.save_turn(turn)

        loaded = loop.load_turn("conv-1")
        assert loaded.state is TurnState.AWAITING_APPROVAL
        assert loaded.awaiting_approval_for is not None
        assert loaded.awaiting_approval_for.id == "c42"

    def test_the_pending_question_survives(self, store):
        loop, _ = store
        turn = a_turn()
        turn.pending_question = {"question": "which customer?", "options": []}
        loop.save_turn(turn)

        assert loop.load_turn("conv-1").pending_question["question"] == "which customer?"

    def test_the_error_survives(self, store):
        loop, _ = store
        turn = a_turn()
        turn.error = "the provider refused"
        loop.save_turn(turn)

        assert loop.load_turn("conv-1").error == "the provider refused"

    def test_a_full_round_trip_preserves_everything(self, store):
        loop, _ = store
        turn = a_turn()
        turn.record_provider_call()
        turn.request_calls(
            (
                ToolCall(id="c1", name="read_file"),
                ToolCall(id="c2", name="write_file"),
            )
        )
        # Set explicitly, as `_run_tools` does: with several pending calls the
        # turn must be told *which* one it is waiting on, because the first may
        # be a read that needs no approval at all.
        turn.awaiting_approval_for = turn.pending_calls[1]
        turn.apply("approval_required")
        loop.save_turn(turn)

        loaded = loop.load_turn("conv-1")
        assert loaded.state is turn.state
        assert loaded.provider_calls == turn.provider_calls
        assert [c.id for c in loaded.pending_calls] == ["c1", "c2"]
        assert loaded.awaiting_approval_for.id == "c2"

    def test_the_fallback_records_the_only_pending_call(self, store):
        """With one pending call there is nothing to guess, so the turn records it."""
        loop, _ = store
        turn = a_turn()
        turn.request_calls((ToolCall(id="solo", name="write_file"),))
        turn.apply("approval_required")

        assert turn.awaiting_approval_for.id == "solo"

    def test_the_fallback_refuses_to_guess_among_several(self, store):
        """Guessing would park the turn on the wrong call: the reader approves a
        read, and the write behind it never runs."""
        loop, _ = store
        turn = a_turn()
        turn.request_calls(
            (
                ToolCall(id="c1", name="read_file"),
                ToolCall(id="c2", name="write_file"),
            )
        )
        turn.apply("approval_required")

        assert turn.awaiting_approval_for is None


# --------------------------------------------------------------------------
# The states that are not errors.
# --------------------------------------------------------------------------


class TestDegenerateSnapshots:
    def test_no_snapshot_means_no_turn_running(self, store):
        """A thread whose turns have all finished is a legitimate state."""
        loop, _ = store
        turn = loop.load_turn("never-existed")
        assert turn.state is TurnState.IDLE
        assert turn.conversation == "never-existed"

    def test_a_corrupt_snapshot_loads_idle_rather_than_crashing(self, store):
        """A turn that cannot be read is a turn that starts over, not a 500."""
        loop, conversations = store
        conversations["conv-1"] = {"name": "conv-1", "turn_snapshot": "{not json"}

        turn = loop.load_turn("conv-1")

        assert turn.state is TurnState.IDLE

    def test_an_unknown_state_loads_idle(self, store):
        """A status the runtime does not recognise is a conversation stuck in it."""
        loop, conversations = store
        conversations["conv-1"] = {
            "name": "conv-1",
            "turn_snapshot": '{"state": "teleporting"}',
        }

        assert loop.load_turn("conv-1").state is TurnState.IDLE

    def test_an_empty_snapshot_loads_idle(self, store):
        loop, conversations = store
        conversations["conv-1"] = {"name": "conv-1", "turn_snapshot": ""}
        assert loop.load_turn("conv-1").state is TurnState.IDLE


# --------------------------------------------------------------------------
# What the poll reports.
# --------------------------------------------------------------------------


class TestReport:
    def test_a_running_turn_keeps_the_poll_waiting(self, store):
        loop, _ = store
        turn = a_turn()
        loop.save_turn(turn)
        assert loop._report(loop.load_turn("conv-1"))["status"] == "running"

    def test_a_done_turn_settles_the_poll(self, store):
        loop, _ = store
        turn = a_turn()
        turn.apply("provider_text")
        loop.save_turn(turn)
        assert loop._report(loop.load_turn("conv-1"))["status"] == "ok"

    def test_a_failed_turn_settles_the_poll_with_the_reason(self, store):
        loop, _ = store
        turn = a_turn()
        turn.error = "the provider refused"
        turn.apply("error")
        loop.save_turn(turn)

        payload = loop._report(loop.load_turn("conv-1"))
        assert payload["status"] == "error"
        assert payload["error"] == "the provider refused"

    def test_a_stopped_turn_is_not_a_failure(self, store):
        """Reporting a stop as an error teaches the reader that Stop breaks things."""
        loop, _ = store
        turn = a_turn()
        turn.apply("reader_stopped")
        loop.save_turn(turn)

        payload = loop._report(loop.load_turn("conv-1"))
        assert payload["status"] == "ok"
        assert payload["stopped"] is True

    def test_an_approval_carries_what_the_reader_must_decide_about(self, store):
        loop, _ = store
        turn = a_turn()
        turn.request_calls((ToolCall(id="c9", name="write_file", arguments={"file": "x"}),))
        turn.apply("approval_required")
        loop.save_turn(turn)

        payload = loop._report(loop.load_turn("conv-1"))
        assert payload["status"] == "awaiting_approval"
        assert payload["pending"]["request_id"] == "c9"
        assert payload["pending"]["name"] == "write_file"

    def test_a_question_carries_the_question(self, store):
        loop, _ = store
        turn = a_turn()
        turn.pending_question = {"question": "which one?"}
        turn.apply("provider_question")
        loop.save_turn(turn)

        payload = loop._report(loop.load_turn("conv-1"))
        assert payload["status"] == "awaiting_answer"
        assert payload["question"]["question"] == "which one?"
