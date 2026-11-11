// The refusal unwrapping, read by plain node.
//
// Ported from `albanna`'s side-chat tests. The module handles the shapes
// Frappe sends, and those shapes are not this app's to redesign — which is
// exactly why it ports unchanged and why the tests come with it.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  failureText,
  lastLine,
  messageText,
  serverMessage,
} from "../../albanna_ai_chat/public/js/lib/errors.mjs";

describe("serverMessage", () => {
  it("reads a rejected request's JSON body", () => {
    const source = {
      responseJSON: { _server_messages: JSON.stringify([{ message: "Not permitted" }]) },
    };
    assert.equal(serverMessage(source), "Not permitted");
  });

  it("reads a response body whose text is JSON", () => {
    const source = {
      responseText: JSON.stringify({ _server_messages: JSON.stringify([{ message: "Denied" }]) }),
    };
    assert.equal(serverMessage(source), "Denied");
  });

  it("reads a traceback's last line", () => {
    const source = { exc: JSON.stringify(["Traceback...", "ValidationError: bad value"]) };
    assert.equal(serverMessage(source), "bad value");
  });

  it("returns empty when the server said nothing", () => {
    assert.equal(serverMessage(null), "");
    assert.equal(serverMessage({}), "");
  });
});

describe("messageText", () => {
  it("unwraps a serialised envelope", () => {
    assert.equal(messageText(JSON.stringify({ message: "hello" })), "hello");
  });

  it("unwraps a list of serialised envelopes", () => {
    assert.equal(messageText([JSON.stringify({ message: "first" })]), "first");
  });

  it("unwraps a plain object", () => {
    assert.equal(messageText({ message: "direct" }), "direct");
  });

  it("returns the string itself when it is not JSON", () => {
    assert.equal(messageText("plain text"), "plain text");
  });

  it("returns empty for nothing", () => {
    assert.equal(messageText(null), "");
    assert.equal(messageText([]), "");
    assert.equal(messageText({}), "");
  });
});

describe("lastLine", () => {
  it("takes the last line and drops the exception class", () => {
    assert.equal(lastLine("a\nb\nValidationError: nope"), "nope");
  });

  it("handles a single line", () => {
    assert.equal(lastLine("PermissionError: no"), "no");
  });

  it("returns empty for nothing", () => {
    assert.equal(lastLine(""), "");
    assert.equal(lastLine(null), "");
  });
});

describe("failureText", () => {
  it("prefers what the failure said", () => {
    assert.equal(failureText(new Error("the reason")), "the reason");
  });

  it("falls back to the caller's sentence", () => {
    // The original was written fifteen times and each copy fell back to the
    // failure itself — `Error` or `[object Object]` — so the sentence could
    // never be read.
    assert.equal(failureText({}, "what to say instead"), "what to say instead");
  });

  it("returns empty when there is nothing at all", () => {
    assert.equal(failureText(null), "");
  });
});
