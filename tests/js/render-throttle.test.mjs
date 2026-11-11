// The render coalescing, read by plain node with a fake clock.
//
// Ported from `albanna`'s side-chat tests. The module takes its scheduler as
// a parameter precisely so this test needs no timers.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  RENDER_EVERY_MS,
  createRenderThrottle,
} from "../../albanna_ai_chat/public/js/lib/render-throttle.mjs";

/** A scheduler that runs nothing until the test says so. */
function fakeClock() {
  const pending = [];
  return {
    schedule(fn, ms) {
      pending.push({ fn, ms });
      return pending.length;
    },
    get pending() {
      return pending;
    },
    flush() {
      const due = pending.splice(0, pending.length);
      for (const { fn } of due) fn();
      return due.length;
    },
  };
}

describe("createRenderThrottle", () => {
  it("renders once for a batch of tokens", () => {
    // A thousand-token answer was parsed a thousand times; the cost of the
    // last parse was paid a thousand times over by the parses before it.
    const clock = fakeClock();
    let renders = 0;
    const request = createRenderThrottle(() => (renders += 1), clock.schedule);

    for (let i = 0; i < 1000; i += 1) request({ content: "x".repeat(i) });

    assert.equal(renders, 0, "nothing renders until the batch is flushed");
    assert.equal(clock.pending.length, 1, "one render is scheduled, not one per token");
    clock.flush();
    assert.equal(renders, 1);
  });

  it("reads the content at flush time, so the last token wins", () => {
    const clock = fakeClock();
    const message = { content: "" };
    let seen = null;
    const request = createRenderThrottle((m) => (seen = m.content), clock.schedule);

    request(message);
    message.content = "first";
    request(message);
    message.content = "second";
    request(message);
    clock.flush();

    assert.equal(seen, "second");
  });

  it("schedules again after a flush", () => {
    const clock = fakeClock();
    let renders = 0;
    const request = createRenderThrottle(() => (renders += 1), clock.schedule);

    request({});
    clock.flush();
    request({});
    clock.flush();

    assert.equal(renders, 2);
  });

  it("uses the gap it was given", () => {
    const clock = fakeClock();
    const request = createRenderThrottle(() => {}, clock.schedule, 10);
    request({});
    assert.equal(clock.pending[0].ms, 10);
  });

  it("defaults to RENDER_EVERY_MS", () => {
    const clock = fakeClock();
    const request = createRenderThrottle(() => {}, clock.schedule);
    request({});
    assert.equal(clock.pending[0].ms, RENDER_EVERY_MS);
  });

  it("ignores a request with no message", () => {
    const clock = fakeClock();
    let renders = 0;
    const request = createRenderThrottle(() => (renders += 1), clock.schedule);
    request(null);
    clock.flush();
    assert.equal(renders, 0);
  });
});
