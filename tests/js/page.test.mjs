// Tests for the route watcher — the event name, and the unsubscribe.
//
// The bug these hold to account: the widget listened for "route-change",
// an event that never happens. The Desk's router says "change", and six
// of the Desk's own files agree. The page the widget believed it was on
// was frozen at the page it had been opened on, so the assistant was
// asked about the wrong page and the transcript showed the wrong
// conversation.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ROUTE_EVENT, watchRoute } from "../../albanna_ai_chat/public/js/lib/page.mjs";

describe("ROUTE_EVENT", () => {
  it("is the event the Desk's router actually fires", () => {
    assert.equal(ROUTE_EVENT, "change");
  });
});

describe("watchRoute", () => {
  it("subscribes to the router's own event and calls back", () => {
    const seen = [];
    let handler = null;
    const router = {
      on: (event, fn) => {
        seen.push(event);
        handler = fn;
      },
      off: () => {},
    };
    const unwatch = watchRoute(() => {}, { window: { frappe: { router } } });
    assert.deepEqual(seen, [ROUTE_EVENT]);
    assert.equal(typeof unwatch, "function");
    handler();
  });

  it("unwatch removes the subscription", () => {
    const removed = [];
    const router = {
      on: (_event, fn) => removed.push({ on: fn }),
      off: (event, fn) => removed.push({ off: [event, fn] }),
    };
    const unwatch = watchRoute(() => {}, { window: { frappe: { router } } });
    unwatch();
    assert.equal(removed.length, 2);
    assert.deepEqual(removed[1].off, [ROUTE_EVENT, removed[0].on]);
  });

  it("answers a no-op when there is no router at all", () => {
    const unwatch = watchRoute(() => {}, { window: {} });
    assert.doesNotThrow(() => unwatch());
  });

  it("answers a no-op when there is no window either", () => {
    // The panel is loaded on Desk pages, but the tests import this module
    // everywhere — a missing browser is a missing watch, not a crash.
    assert.doesNotThrow(() => watchRoute(() => {}, { window: undefined }));
  });
});
