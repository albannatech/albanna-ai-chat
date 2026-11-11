/**
 * Tests for the access decision — the shared answer two bundles need.
 *
 * What these verify is the failure the module exists to prevent: a reader who
 * may not chat being given a button that does nothing. That happens when the
 * launcher's answer and the button's assumption are two different answers, so
 * every test here is about the two agreeing.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ACCESS_EVENT,
  ACCESS_GLOBAL,
  chatAllowed,
  onAccessDecision,
  publishAccess,
} from "../../albanna_ai_chat/public/js/lib/access.mjs";

/** A fake page: a window that is an object and a document that records events. */
function fakeEnv() {
  const listeners = {};
  return {
    window: {},
    document: {
      dispatchEvent(event) {
        (listeners[event.type] || []).forEach((fn) => fn(event));
      },
      addEventListener(type, fn) {
        (listeners[type] = listeners[type] || []).push(fn);
      },
      removeEventListener(type, fn) {
        listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
      },
    },
    fired: listeners,
  };
}

describe("publishAccess", () => {
  it("records the decision on the window", () => {
    const env = fakeEnv();
    const decision = publishAccess({ visible: true, chat_access: true }, env);
    assert.equal(env.window[ACCESS_GLOBAL].visible, true);
    assert.equal(decision.chat_access, true);
  });

  it("publishes a refusal too, so the button is not left waiting", () => {
    // A silent failure leaves the button waiting for an answer that never
    // comes, which is the same dead button again.
    const env = fakeEnv();
    publishAccess({ visible: false, chat_access: false }, env);
    assert.equal(chatAllowed(env), false);
  });

  it("treats a missing answer as a refusal, not as a yes", () => {
    const env = fakeEnv();
    publishAccess(null, env);
    assert.equal(chatAllowed(env), false);
  });

  it("announces the decision on the document", () => {
    const env = fakeEnv();
    let heard = null;
    onAccessDecision((d) => {
      heard = d;
    }, env);
    publishAccess({ visible: true, chat_access: true }, env);
    assert.deepEqual(heard, { visible: true, chat_access: true });
  });

  it("coerces truthy-but-not-true to a refusal", () => {
    // `visible: "yes"` is not `visible: true`, and a widget that renders for a
    // reader the server did not grant is the bug this whole module prevents.
    const env = fakeEnv();
    publishAccess({ visible: "yes", chat_access: 1 }, env);
    assert.equal(chatAllowed(env), false);
  });
});

describe("chatAllowed", () => {
  it("answers no until the launcher has published", () => {
    // "Not yet" and "no" are the same answer for a button.
    const env = fakeEnv();
    assert.equal(chatAllowed(env), false);
  });

  it("answers yes once the launcher has granted", () => {
    const env = fakeEnv();
    publishAccess({ visible: true, chat_access: true }, env);
    assert.equal(chatAllowed(env), true);
  });

  it("answers no when the widget is hidden even if chat is allowed", () => {
    const env = fakeEnv();
    publishAccess({ visible: false, chat_access: true }, env);
    assert.equal(chatAllowed(env), false);
  });
});

describe("onAccessDecision", () => {
  it("hears an answer published after the form was drawn", () => {
    const env = fakeEnv();
    let heard = null;
    onAccessDecision((d) => {
      heard = d;
    }, env);
    publishAccess({ visible: true, chat_access: true }, env);
    assert.equal(heard.visible, true);
  });

  it("stops listening once the returned function is called", () => {
    const env = fakeEnv();
    let calls = 0;
    const stop = onAccessDecision(() => {
      calls += 1;
    }, env);
    publishAccess({ visible: true, chat_access: true }, env);
    stop();
    publishAccess({ visible: true, chat_access: true }, env);
    assert.equal(calls, 1);
  });

  it("returns a no-op when the document cannot listen", () => {
    const stop = onAccessDecision(() => {}, { window: {}, document: null });
    assert.doesNotThrow(() => stop());
  });
});
