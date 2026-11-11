/**
 * Tests for the turn transport's pure half — the poll ramp.
 *
 * What these verify is the politeness of the guarantee. The poll exists because
 * Frappe's request model cannot stream a response, so a client whose socket
 * died still gets its answer. But a poll that runs every second and a half
 * forever is a poll spending the reader's requests on nothing, and one that
 * never runs while the socket is quiet is a guarantee that is never exercised.
 *
 * `nextPollDelay` is the whole of that judgment, and it takes `now` as an
 * argument precisely so it can be tested without waiting for it.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  FIRST_POLL_MS,
  SOCKET_ALIVE_WINDOW_MS,
  STATUS_POLL_GROWTH,
  STATUS_POLL_MAX_MS,
  STATUS_POLL_MS,
  STATUS_POLL_MS_WHILE_ALIVE,
  nextPollDelay,
} from "../../albanna_ai_chat/public/js/lib/transport.mjs";

const NOW = 1_000_000;

describe("nextPollDelay — the socket is alive", () => {
  it("slows right down when an event arrived just now", () => {
    const delay = nextPollDelay({ lastEventAt: NOW - 100, idlePolls: 0 }, NOW);
    assert.equal(delay, STATUS_POLL_MS_WHILE_ALIVE);
  });

  it("slows down even after many idle polls, if the socket just spoke", () => {
    // The socket speaking is the stronger signal: the transport is working, so
    // the poll is only there to guarantee what already works.
    const delay = nextPollDelay({ lastEventAt: NOW - 500, idlePolls: 20 }, NOW);
    assert.equal(delay, STATUS_POLL_MS_WHILE_ALIVE);
  });

  it("keeps slowing down until the alive window closes", () => {
    const justInside = NOW - (SOCKET_ALIVE_WINDOW_MS - 1);
    const justOutside = NOW - (SOCKET_ALIVE_WINDOW_MS + 1);
    assert.equal(nextPollDelay({ lastEventAt: justInside, idlePolls: 0 }, NOW), STATUS_POLL_MS_WHILE_ALIVE);
    assert.notEqual(nextPollDelay({ lastEventAt: justOutside, idlePolls: 0 }, NOW), STATUS_POLL_MS_WHILE_ALIVE);
  });
});

describe("nextPollDelay — the socket is quiet", () => {
  it("starts at the base interval", () => {
    assert.equal(nextPollDelay({ lastEventAt: 0, idlePolls: 0 }, NOW), STATUS_POLL_MS);
  });

  it("grows with each idle poll", () => {
    const first = nextPollDelay({ lastEventAt: 0, idlePolls: 0 }, NOW);
    const second = nextPollDelay({ lastEventAt: 0, idlePolls: 1 }, NOW);
    const third = nextPollDelay({ lastEventAt: 0, idlePolls: 2 }, NOW);
    assert.ok(second > first, "the second wait is longer than the first");
    assert.ok(third > second, "the third wait is longer than the second");
  });

  it("grows geometrically, by the declared growth factor", () => {
    // Compared with a tolerance rather than by rounding: the ramp is rounded
    // to whole milliseconds at each step, so the ratio between two rounded
    // values is 1.5999 and not exactly 1.6 — and asserting the exact value
    // would be asserting the rounding, not the growth.
    //
    // The counts are low on purpose. By idlePolls=4 the raw ramp is 9830ms,
    // which the cap pulls down to 9000 — so a ratio measured there is
    // measuring the cap, not the growth.
    const a = nextPollDelay({ lastEventAt: 0, idlePolls: 1 }, NOW);
    const b = nextPollDelay({ lastEventAt: 0, idlePolls: 2 }, NOW);
    assert.ok(
      Math.abs(b / a - STATUS_POLL_GROWTH) < 0.01,
      `expected a ratio near ${STATUS_POLL_GROWTH}, got ${b / a}`,
    );
  });

  it("the cap engages once the raw ramp passes it", () => {
    // Documented rather than left implicit: the ramp is geometric, so it passes
    // the cap after only a few idle polls, and everything after that is flat.
    const underCap = nextPollDelay({ lastEventAt: 0, idlePolls: 3 }, NOW);
    const overCap = nextPollDelay({ lastEventAt: 0, idlePolls: 4 }, NOW);
    assert.ok(underCap < STATUS_POLL_MAX_MS);
    assert.equal(overCap, STATUS_POLL_MAX_MS);
  });

  it("never grows past the cap", () => {
    // A turn that is thinking hard is polled a few times a minute, not every
    // second and a half — and not never again either.
    const delay = nextPollDelay({ lastEventAt: 0, idlePolls: 500 }, NOW);
    assert.equal(delay, STATUS_POLL_MAX_MS);
  });

  it("treats a socket that never spoke the same as a quiet one", () => {
    assert.equal(
      nextPollDelay({ lastEventAt: 0, idlePolls: 2 }, NOW),
      nextPollDelay({ lastEventAt: NOW - 999_999, idlePolls: 2 }, NOW),
    );
  });
});

describe("nextPollDelay — the defaults", () => {
  it("works with no state at all", () => {
    assert.equal(nextPollDelay({}, NOW), STATUS_POLL_MS);
  });

  it("treats a negative idle count as zero rather than shrinking the wait", () => {
    assert.equal(nextPollDelay({ lastEventAt: 0, idlePolls: -5 }, NOW), STATUS_POLL_MS);
  });
});

describe("the constants", () => {
  it("the first poll is eager — sooner than the base interval", () => {
    // The first poll is the one most likely to find an answer already parked,
    // because a turn that finished while the page was loading has nothing left
    // to wait for. So it goes early, and the ramp takes over from there.
    assert.ok(FIRST_POLL_MS < STATUS_POLL_MS);
  });

  it("the alive rate is slower than the slowest ramp", () => {
    assert.ok(STATUS_POLL_MS_WHILE_ALIVE > STATUS_POLL_MAX_MS);
  });

  it("the cap is reachable from the base by the growth factor", () => {
    // If the cap were below the base, the ramp would be capped immediately and
    // the growth factor would be decoration.
    assert.ok(STATUS_POLL_MAX_MS > STATUS_POLL_MS * STATUS_POLL_GROWTH);
  });
});
