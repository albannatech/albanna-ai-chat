/**
 * Tests for the notices — the sentences the panel says in passing.
 *
 * What these verify is that every notice key has a sentence behind it. A key
 * that renders blank is a panel that goes quiet exactly when it had something to
 * say, and that is the kind of thing nobody notices until a reader reports it.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { noticeKeys, noticeText } from "../../albanna_ai_chat/public/js/lib/notices.mjs";

describe("noticeText", () => {
  it("has a sentence for every key it declares", () => {
    for (const key of noticeKeys()) {
      assert.ok(
        noticeText(key).length > 0,
        `notice key ${key} renders blank — the panel goes quiet when it had something to say`,
      );
    }
  });

  it("returns nothing for an unknown key", () => {
    assert.equal(noticeText("no-such-notice"), "");
  });

  it("returns nothing for no key at all", () => {
    assert.equal(noticeText(""), "");
    assert.equal(noticeText(undefined), "");
  });

  it("names the setting that fixes a missing provider", () => {
    // A notice the reader cannot act on is a notice that will be reported as a
    // bug. This one names where to go.
    assert.ok(noticeText("no-provider").includes("Settings"));
  });

  it("explains a stopped turn rather than only saying it stopped", () => {
    assert.ok(noticeText("stopped").length > 0);
  });

  it("says a dry run saved nothing", () => {
    assert.ok(noticeText("dry-run").toLowerCase().includes("nothing was saved"));
  });
});

describe("noticeKeys", () => {
  it("declares no duplicates", () => {
    const keys = noticeKeys();
    assert.equal(new Set(keys).size, keys.length);
  });

  it("covers the states this core can actually reach", () => {
    // The turn loop reports stopped, failed, exhausted and no-provider; each
    // needs a sentence the panel can show.
    const keys = new Set(noticeKeys());
    for (const expected of ["stopped", "answer-cut-off", "no-provider", "refused"]) {
      assert.ok(keys.has(expected), `no notice for ${expected}`);
    }
  });
});
