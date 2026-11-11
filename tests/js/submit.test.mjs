/**
 * Tests for the composer's rules — what may be sent, and why not.
 *
 * What these verify is that every refusal says what to do about it. A refusal the
 * reader cannot act on is a refusal that fails, and the reader concludes the app
 * is broken.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DEFAULT_QUESTION_LENGTH,
  REASONS,
  refusalText,
  submitDecision,
} from "../../albanna_ai_chat/public/js/lib/submit.mjs";

describe("submitDecision — the happy path", () => {
  it("sends a trimmed question", () => {
    const result = submitDecision({ modelValue: "  what is open?  ", canChat: true });
    assert.equal(result.ok, true);
    assert.equal(result.question, "what is open?");
    assert.equal(result.reason, "");
  });

  it("reports the trimmed length", () => {
    // Leading whitespace is not part of the question, and a reader who pasted with
    // an indent should not be charged for it.
    const result = submitDecision({ modelValue: "   hi   ", canChat: true });
    assert.equal(result.length, 2);
  });

  it("sends an empty question when a file is attached", () => {
    const result = submitDecision({ modelValue: "", files: [{}], canChat: true });
    assert.equal(result.ok, true);
  });
});

describe("submitDecision — the refusals", () => {
  it("refuses while a turn is running", () => {
    const result = submitDecision({ modelValue: "hi", busy: true, canChat: true });
    assert.equal(result.ok, false);
    assert.equal(result.reason, REASONS.BUSY);
  });

  it("refuses when the reader may not chat", () => {
    const result = submitDecision({ modelValue: "hi", canChat: false });
    assert.equal(result.ok, false);
    assert.equal(result.reason, REASONS.NO_CHAT);
  });

  it("refuses an empty question with no attachment", () => {
    const result = submitDecision({ modelValue: "   ", canChat: true });
    assert.equal(result.ok, false);
    assert.equal(result.reason, REASONS.EMPTY);
  });

  it("refuses a question over the ceiling, with its length", () => {
    // A refusal the reader cannot act on is a refusal that fails.
    const result = submitDecision({
      modelValue: "x".repeat(50),
      maxLength: 10,
      canChat: true,
    });
    assert.equal(result.ok, false);
    assert.equal(result.reason, REASONS.TOO_LONG);
    assert.equal(result.length, 50);
  });

  it("accepts a question exactly at the ceiling", () => {
    const result = submitDecision({
      modelValue: "x".repeat(10),
      maxLength: 10,
      canChat: true,
    });
    assert.equal(result.ok, true);
  });

  it("uses the site's ceiling when it published one", () => {
    const result = submitDecision({
      modelValue: "x".repeat(20),
      maxLength: 100,
      canChat: true,
    });
    assert.equal(result.ok, true);
  });

  it("falls back to the default ceiling when the site published none", () => {
    const result = submitDecision({
      modelValue: "x".repeat(DEFAULT_QUESTION_LENGTH + 1),
      canChat: true,
    });
    assert.equal(result.reason, REASONS.TOO_LONG);
  });

  it("ignores a ceiling of zero rather than refusing everything", () => {
    const result = submitDecision({ modelValue: "hi", maxLength: 0, canChat: true });
    assert.equal(result.ok, true);
  });

  it("refuses when the reader's access is unknown", () => {
    // No input at all means `canChat` was never answered, and an unanswered
    // question is not a yes. The safe direction to be wrong in.
    const result = submitDecision();
    assert.equal(result.ok, false);
    assert.equal(result.reason, REASONS.NO_CHAT);
  });
});

describe("refusalText", () => {
  it("says what to do about each refusal", () => {
    for (const reason of Object.values(REASONS)) {
      assert.ok(refusalText(reason).length > 0, `no sentence for ${reason}`);
    }
  });

  it("names both lengths for the too-long case", () => {
    const text = refusalText(REASONS.TOO_LONG, 50, 10);
    assert.ok(text.includes("50"));
    assert.ok(text.includes("10"));
  });

  it("returns nothing when the question may go", () => {
    assert.equal(refusalText(""), "");
  });
});
