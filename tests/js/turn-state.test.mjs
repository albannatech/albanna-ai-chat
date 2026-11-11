// The turn state machine, read by plain node.
//
// The pattern is ported from `albanna`'s side-chat; the vocabulary is this
// core's own, and the test that matters most is the last one: the eight
// phases here must equal the eight the Python enum declares, because a
// status the runtime does not recognise is a conversation stuck in it.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";

import {
  AWAITING_ANSWER,
  AWAITING_APPROVAL,
  AWAITING_TOOL,
  DONE,
  FAILED,
  IDLE,
  RUNNING,
  STATES,
  STOPPED,
  beginTurn,
  canSend,
  canStop,
  clearTranscript,
  dismiss,
  endTurn,
  failTurn,
  initialState,
  isBusy,
  isWaitingOnReader,
  setActivity,
  setPhase,
  stopTurn,
} from "../../albanna_ai_chat/public/js/lib/turn-state.mjs";
import { PHASES } from "../../albanna_ai_chat/public/js/lib/wire.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));

/** The phases the Python enum declares, read out of the source. */
function pythonPhases() {
  const source = readFileSync(
    join(HERE, "..", "..", "albanna_ai_chat", "chat", "turn.py"),
    "utf8",
  );
  // Bound the slice to the TurnState class body: the next `class` ends it,
  // and without the bound the regex runs on into TurnEvent and the action
  // constants, which are not phases.
  const block = source.slice(source.indexOf("class TurnState"));
  const next = block.indexOf("\nclass ", 1);
  const body = next === -1 ? block : block.slice(0, next);
  return [...body.matchAll(/^\s{4}([A-Z_]+) = "([a-z_]+)"/gm)].map((m) => m[2]);
}

describe("the phases cannot drift from the server", () => {
  it("matches chat/turn.py's TurnState", () => {
    assert.deepEqual(STATES, pythonPhases());
  });

  it("matches the doctype's status options", () => {
    assert.deepEqual(PHASES, STATES);
  });
});

describe("initialState", () => {
  it("starts idle and empty", () => {
    const state = initialState();
    assert.equal(state.phase, IDLE);
    assert.deepEqual(state.messages, []);
    assert.equal(state.error, "");
  });
});

describe("canSend", () => {
  it("is true only when idle", () => {
    const state = initialState();
    assert.equal(canSend(state), true);
    state.phase = RUNNING;
    assert.equal(canSend(state), false);
  });
});

describe("canStop", () => {
  it("is true while work is in flight", () => {
    const state = initialState();
    assert.equal(canStop(state), false);
    state.phase = RUNNING;
    assert.equal(canStop(state), true);
    state.phase = AWAITING_TOOL;
    assert.equal(canStop(state), true);
  });

  it("is false while the reader is the one being waited on", () => {
    // They are the one being waited on; stopping is not theirs to do.
    const state = initialState();
    state.phase = AWAITING_APPROVAL;
    assert.equal(canStop(state), false);
    state.phase = AWAITING_ANSWER;
    assert.equal(canStop(state), false);
  });
});

describe("isBusy", () => {
  it("is false when idle and when finished", () => {
    const state = initialState();
    assert.equal(isBusy(state), false);
    for (const phase of [DONE, FAILED, STOPPED]) {
      state.phase = phase;
      assert.equal(isBusy(state), false, phase);
    }
  });

  it("is true while a turn is in flight", () => {
    const state = initialState();
    for (const phase of [RUNNING, AWAITING_TOOL, AWAITING_APPROVAL, AWAITING_ANSWER]) {
      state.phase = phase;
      assert.equal(isBusy(state), true, phase);
    }
  });
});

describe("isWaitingOnReader", () => {
  it("separates the two kinds of waiting", () => {
    // An approval is a decision about a write; a question is a choice the
    // assistant cannot make. Collapsing them into "busy" is how a reader
    // ends up staring at a spinner when what is wanted is a button.
    const state = initialState();
    state.phase = AWAITING_APPROVAL;
    assert.equal(isWaitingOnReader(state), true);
    state.phase = AWAITING_ANSWER;
    assert.equal(isWaitingOnReader(state), true);
    state.phase = AWAITING_TOOL;
    assert.equal(isWaitingOnReader(state), false);
  });
});

describe("setPhase", () => {
  it("accepts a known phase", () => {
    const state = initialState();
    setPhase(state, AWAITING_TOOL);
    assert.equal(state.phase, AWAITING_TOOL);
  });

  it("refuses an unknown one rather than ignoring it", () => {
    const state = initialState();
    assert.throws(() => setPhase(state, "thinking"), /Unknown turn phase/);
  });
});

describe("beginTurn", () => {
  it("clears the last turn's leftovers and pushes both messages", () => {
    const state = initialState();
    state.error = "previous failure";
    const asked = { role: "user" };
    const answer = { role: "assistant", pending: true };
    const returned = beginTurn(state, "what is open?", asked, answer);

    assert.equal(returned, answer);
    assert.equal(state.phase, RUNNING);
    assert.equal(state.error, "");
    assert.equal(state.asked, "what is open?");
    assert.deepEqual(state.messages, [asked, answer]);
  });
});

describe("endTurn", () => {
  it("clears the pending flag and finishes", () => {
    const state = initialState();
    const answer = { pending: true };
    beginTurn(state, "q", { role: "user" }, answer);
    endTurn(state, answer);
    assert.equal(answer.pending, false);
    assert.equal(state.phase, DONE);
    assert.equal(state.activity, "");
  });
});

describe("failTurn", () => {
  it("records what went wrong", () => {
    const state = initialState();
    const answer = { pending: true };
    beginTurn(state, "q", { role: "user" }, answer);
    failTurn(state, answer, "the provider said no");
    assert.equal(state.phase, FAILED);
    assert.equal(state.error, "the provider said no");
    assert.equal(answer.pending, false);
  });
});

describe("stopTurn", () => {
  it("keeps what arrived and stops the waiting", () => {
    // The work finishes on the server; the waiting stops here. What arrived
    // is kept — it is the truth so far.
    const state = initialState();
    const answer = { pending: true, content: "half an answer" };
    beginTurn(state, "q", { role: "user" }, answer);
    stopTurn(state, answer);
    assert.equal(state.phase, STOPPED);
    assert.equal(answer.pending, false);
    assert.equal(answer.content, "half an answer");
  });
});

describe("clearTranscript", () => {
  it("stops a turn in flight and returns its answer", () => {
    const state = initialState();
    const answer = { pending: true };
    beginTurn(state, "q", { role: "user" }, answer);
    const stopped = clearTranscript(state);
    assert.equal(stopped, answer);
    assert.deepEqual(state.messages, []);
    assert.equal(state.phase, STOPPED);
  });

  it("returns nothing when no turn was running", () => {
    const state = initialState();
    assert.equal(clearTranscript(state), null);
  });
});

describe("dismiss", () => {
  it("clears one channel and leaves the other", () => {
    const state = initialState();
    state.error = "e";
    state.notice = "n";
    dismiss(state, "error");
    assert.equal(state.error, "");
    assert.equal(state.notice, "n");
    dismiss(state, "notice");
    assert.equal(state.notice, "");
  });
});

describe("setActivity", () => {
  it("says what the assistant is doing", () => {
    const state = initialState();
    setActivity(state, "Reading 3 files");
    assert.equal(state.activity, "Reading 3 files");
  });
});
