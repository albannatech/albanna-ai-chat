/**
 * Tests for the tool labels — what a tool call is called in the reader's language.
 *
 * What these verify is that a reader is never shown the model's vocabulary. A
 * label that reads "Working" for a tool the manifest knows by another name is a
 * label nobody notices being wrong, which is the kind that stays wrong.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EXTENSION_LABELS,
  describeTool,
  statusLabel,
  toolAction,
  toolLabel,
  toolSummary,
} from "../../albanna_ai_chat/public/js/lib/tool-labels.mjs";

describe("statusLabel", () => {
  it("names every phase the server can report", () => {
    // A phase the panel cannot name is a phase the panel shows as a spinner
    // forever, so each one gets a sentence.
    const phases = [
      "running",
      "awaiting_tool",
      "awaiting_approval",
      "awaiting_answer",
      "done",
      "failed",
      "stopped",
    ];
    for (const phase of phases) {
      assert.ok(statusLabel(phase).length > 0, `no label for phase ${phase}`);
    }
  });

  it("distinguishes waiting on a tool from waiting on the reader", () => {
    // Collapsing them is how a reader ends up staring at a spinner when what is
    // wanted is a button.
    assert.notEqual(statusLabel("awaiting_tool"), statusLabel("awaiting_approval"));
    assert.notEqual(statusLabel("awaiting_approval"), statusLabel("awaiting_answer"));
  });

  it("returns nothing for an unknown phase", () => {
    assert.equal(statusLabel("teleporting"), "");
  });

  it("returns nothing for no phase at all", () => {
    assert.equal(statusLabel(""), "");
    assert.equal(statusLabel(undefined), "");
  });
});

describe("toolLabel", () => {
  it("names the core's three file tools in the reader's language", () => {
    assert.equal(toolLabel("read_file"), "Reading a file");
    assert.equal(toolLabel("write_file"), "Writing a file");
    assert.equal(toolLabel("edit_file"), "Editing a file");
  });

  it("never shows the model's own name", () => {
    for (const name of ["read_file", "write_file", "edit_file"]) {
      assert.ok(!toolLabel(name).includes(name), `${name} leaked into its label`);
    }
  });

  it("falls to an honest default for an unknown tool", () => {
    // "Working" is a true sentence about a tool whose name means nothing to a
    // reader. A table that guessed would be a table that was wrong.
    assert.equal(toolLabel("acme_stamp_record"), "Working");
  });

  it("uses an extension's declared label when it has one", () => {
    EXTENSION_LABELS.acme_stamp_record = { label: "Stamping a record", action: "Stamping" };
    try {
      assert.equal(toolLabel("acme_stamp_record"), "Stamping a record");
      assert.equal(toolAction("acme_stamp_record"), "Stamping");
    } finally {
      delete EXTENSION_LABELS.acme_stamp_record;
    }
  });
});

describe("toolAction", () => {
  it("names the verbs for the two writing tools", () => {
    assert.equal(toolAction("write_file"), "Writing");
    assert.equal(toolAction("edit_file"), "Editing");
  });

  it("returns nothing for a read tool", () => {
    // A read never reaches the approval card at all.
    assert.equal(toolAction("read_file"), "");
  });

  it("returns nothing for an unknown tool", () => {
    assert.equal(toolAction("acme_stamp_record"), "");
  });
});

describe("describeTool", () => {
  it("adds the file the tool is acting on", () => {
    assert.equal(
      describeTool("read_file", { file: "/files/report.pdf" }),
      "Reading a file /files/report.pdf",
    );
  });

  it("adds the doctype for an extension's tool", () => {
    // Both argument names are read, because a label that named only one would
    // go blank for the other.
    assert.equal(
      describeTool("acme_stamp_record", { doctype: "Patient" }),
      "Working Patient",
    );
  });

  it("returns the bare label when there is no target", () => {
    assert.equal(describeTool("read_file", {}), "Reading a file");
    assert.equal(describeTool("read_file"), "Reading a file");
  });

  it("trims the target", () => {
    assert.equal(describeTool("read_file", { file: "  x  " }), "Reading a file x");
  });
});

describe("toolSummary", () => {
  it("counts distinct tools and calls separately", () => {
    // "3 tools" and "7 calls" are different questions.
    const message = {
      tools: [
        { name: "read_file" },
        { name: "read_file" },
        { name: "edit_file" },
      ],
    };
    assert.equal(toolSummary(message), "Tools used: 2 · Calls: 3");
  });

  it("returns nothing when no tools were used", () => {
    assert.equal(toolSummary({ tools: [] }), "");
    assert.equal(toolSummary({}), "");
    assert.equal(toolSummary(null), "");
  });
});
