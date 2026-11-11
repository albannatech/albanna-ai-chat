/**
 * Tests for write safety — which writes cannot be undone, and what it costs.
 *
 * What these verify is the distinction the card exists to draw: a file whose text
 * was replaced can be replaced back, and a file that was created in error cannot be
 * removed from here. A card that warns about a recoverable write is a card the
 * reader learns to read past, and then the warning means nothing when a genuinely
 * irreversible one arrives.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CONSEQUENCES,
  DESTRUCTIVE_TOOLS,
  declareDestructive,
  destructiveConsequence,
  diffValue,
  isDestructiveTool,
} from "../../albanna_ai_chat/public/js/lib/write-safety.mjs";

describe("isDestructiveTool", () => {
  it("marks the tool whose write cannot be undone from here", () => {
    // write_file declares mechanism="none": the core ships no delete_file, so a
    // File created in error is removed by an operator.
    assert.equal(isDestructiveTool("write_file"), true);
  });

  it("does not mark the tool that is genuinely reversible", () => {
    // edit_file declares mechanism="reverse": swap the two strings and the file
    // returns to what it was.
    assert.equal(isDestructiveTool("edit_file"), false);
  });

  it("does not mark a read", () => {
    assert.equal(isDestructiveTool("read_file"), false);
  });

  it("does not mark an unknown tool", () => {
    assert.equal(isDestructiveTool("acme_stamp_record"), false);
  });

  it("survives no name at all", () => {
    assert.equal(isDestructiveTool(""), false);
    assert.equal(isDestructiveTool(undefined), false);
  });
});

describe("destructiveConsequence", () => {
  it("gives a sentence for a destructive tool", () => {
    const text = destructiveConsequence("write_file");
    assert.ok(text.length > 0);
    assert.ok(text.includes("operator"));
  });

  it("gives nothing for a recoverable write", () => {
    // A card that warns about a recoverable write is a card read past.
    assert.equal(destructiveConsequence("edit_file"), "");
    assert.equal(destructiveConsequence("read_file"), "");
  });

  it("falls back to a generic sentence for an undeclared destructive tool", () => {
    DESTRUCTIVE_TOOLS.add("mystery_tool");
    try {
      assert.ok(destructiveConsequence("mystery_tool").length > 0);
    } finally {
      DESTRUCTIVE_TOOLS.delete("mystery_tool");
      delete CONSEQUENCES.mystery_tool;
    }
  });
});

describe("declareDestructive", () => {
  it("lets an extension mark its own tool", () => {
    declareDestructive("acme_purge", "This purges the ACME ledger.");
    try {
      assert.equal(isDestructiveTool("acme_purge"), true);
      assert.equal(destructiveConsequence("acme_purge"), "This purges the ACME ledger.");
    } finally {
      DESTRUCTIVE_TOOLS.delete("acme_purge");
      delete CONSEQUENCES.acme_purge;
    }
  });

  it("gives a default sentence when none is declared", () => {
    // A tool marked destructive with no sentence is a card that warns and then
    // says nothing.
    declareDestructive("acme_wipe", "");
    try {
      assert.ok(destructiveConsequence("acme_wipe").length > 0);
    } finally {
      DESTRUCTIVE_TOOLS.delete("acme_wipe");
      delete CONSEQUENCES.acme_wipe;
    }
  });

  it("ignores an empty name", () => {
    const before = DESTRUCTIVE_TOOLS.size;
    declareDestructive("", "nothing");
    assert.equal(DESTRUCTIVE_TOOLS.size, before);
  });
});

describe("diffValue", () => {
  it("shows a dash for a field that had nothing in it", () => {
    // An empty cell does not say "nothing was here" — it says "broken".
    assert.equal(diffValue(null), "—");
    assert.equal(diffValue(undefined), "—");
    assert.equal(diffValue(""), "—");
  });

  it("shows a real zero as zero", () => {
    assert.equal(diffValue(0), "0");
  });

  it("shows a real false as false", () => {
    assert.equal(diffValue(false), "false");
  });

  it("shows a real value as itself", () => {
    assert.equal(diffValue("Acme"), "Acme");
    assert.equal(diffValue(42), "42");
  });
});
