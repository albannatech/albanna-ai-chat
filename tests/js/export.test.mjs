// Tests for the export — which messages are sayable, in whose voice.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  conversationToMarkdown,
  exportFilename,
} from "../../albanna_ai_chat/public/js/lib/export.mjs";

const SPEAKERS = { reader: "You", assistant: "Assistant" };

describe("conversationToMarkdown", () => {
  it("one line per message, the speaker in bold, a blank line between turns", () => {
    const md = conversationToMarkdown(
      [
        { role: "user", content: "How many orders are open?" },
        { role: "assistant", content: "Three." },
      ],
      SPEAKERS,
    );
    assert.equal(md, "**You:** How many orders are open?\n\n**Assistant:**\n\nThree.\n");
  });

  it("tool rows are skipped — plumbing, not speech", () => {
    const md = conversationToMarkdown(
      [
        { role: "user", content: "hi" },
        { role: "tool", content: "Read 3 files" },
        { role: "assistant", content: "here" },
      ],
      SPEAKERS,
    );
    assert.ok(!md.includes("Read 3 files"));
    assert.ok(md.includes("**You:** hi"));
  });

  it("a message with no content still gets its speaker line", () => {
    // The file shows the shape of the conversation rather than silently
    // dropping turns — and the trailing blank block is trimmed, so the
    // file ends with exactly one newline.
    const md = conversationToMarkdown(
      [{ role: "assistant", content: "" }],
      SPEAKERS,
    );
    assert.equal(md, "**Assistant:**\n");
  });

  it("ends with exactly one newline", () => {
    const md = conversationToMarkdown([], SPEAKERS);
    assert.equal(md, "\n");
    assert.ok(!md.endsWith("\n\n"));
  });

  it("tolerates a hole in the transcript", () => {
    const md = conversationToMarkdown(
      [null, { role: "user", content: "hi" }],
      SPEAKERS,
    );
    assert.ok(md.includes("hi"));
  });
});

describe("exportFilename", () => {
  it("sortable and unambiguous", () => {
    const when = new Date(2026, 10, 12, 9, 5).getTime();
    assert.equal(exportFilename(when), "albanna-ai-chat-conversation-20261112-0905.md");
  });

  it("pads both halves", () => {
    const when = new Date(2026, 0, 3, 1, 2).getTime();
    assert.equal(exportFilename(when), "albanna-ai-chat-conversation-20260103-0102.md");
  });
});
