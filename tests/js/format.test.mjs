// The formatting helpers, read by plain node.
//
// Ported from `albanna`'s side-chat tests, because the module they test was
// portable without a change: nothing in it is bound to this app's contract.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  absoluteTime,
  currentLocale,
  formatBytes,
  formatNumber,
  formatPosition,
  relativeTime,
} from "../../albanna_ai_chat/public/js/lib/format.mjs";

describe("currentLocale", () => {
  it("answers with a locale, whatever the host offers", () => {
    // node 24 has a `navigator`, so this is the host's own answer rather
    // than the "en" fallback — the point is that it never returns nothing.
    const locale = currentLocale();
    assert.equal(typeof locale, "string");
    assert.ok(locale.length > 0);
  });
});

describe("relativeTime", () => {
  it("reads an epoch in seconds", () => {
    const now = Math.floor(Date.now() / 1000);
    const text = relativeTime(now - 120);
    assert.match(text, /minute|دقائق/);
  });

  it("reads a naive server timestamp", () => {
    // The server sends "2026-10-21 03:20:00" with no timezone; the space is
    // replaced so the browser does not read it as local-and-wrong.
    const text = relativeTime("2026-10-21 03:20:00");
    assert.equal(typeof text, "string");
  });

  it("returns empty for nothing", () => {
    assert.equal(relativeTime(null), "");
    assert.equal(relativeTime(""), "");
    assert.equal(relativeTime("not a date"), "");
  });
});

describe("absoluteTime", () => {
  it("formats a readable moment", () => {
    const text = absoluteTime(Math.floor(Date.now() / 1000));
    assert.ok(text.length > 0);
  });

  it("returns empty for an unreadable one", () => {
    assert.equal(absoluteTime("nonsense"), "");
  });
});

describe("formatNumber", () => {
  it("formats a finite number", () => {
    assert.equal(formatNumber(1234), "1,234");
  });

  it("returns empty for what is not a number", () => {
    assert.equal(formatNumber("12"), "");
    assert.equal(formatNumber(NaN), "");
    assert.equal(formatNumber(Infinity), "");
  });
});

describe("formatBytes", () => {
  it("scales through the units", () => {
    assert.equal(formatBytes(0), "0 B");
    assert.equal(formatBytes(512), "512 B");
    assert.equal(formatBytes(2048), "2 KB");
    assert.equal(formatBytes(1024 * 1024 * 1.5), "1.5 MB");
  });

  it("returns empty for a nonsense count", () => {
    assert.equal(formatBytes(-1), "");
    assert.equal(formatBytes("big"), "");
  });
});

describe("formatPosition", () => {
  it("says the position when a file is longer than one read", () => {
    // The read tool pages a long file, so the panel shows where the reader
    // is rather than only how long the file is.
    assert.equal(formatPosition(8000, 20000), "8,000 of 20,000 characters");
  });

  it("says only the length when the whole file was read", () => {
    assert.equal(formatPosition(50, 50), "50 characters");
  });

  it("returns empty when there is no file", () => {
    assert.equal(formatPosition(0, 0), "");
  });
});
