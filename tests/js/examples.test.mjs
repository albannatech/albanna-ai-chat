// Tests for the suggested questions — the empty state follows the page.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  exampleSet,
  examplesFor,
  openDocumentFrom,
} from "../../albanna_ai_chat/public/js/lib/examples.mjs";

describe("exampleSet", () => {
  it("a form with a doctype asks about that document", () => {
    assert.equal(exampleSet({ view: "form", doctype: "Issue", name: "ISS-1" }), "form");
  });

  it("a report asks about the report", () => {
    assert.equal(exampleSet({ report: "Accounts Receivable" }), "report");
  });

  it("a list is a doctype without a name", () => {
    assert.equal(exampleSet({ view: "List/Issue/List", doctype: "Issue" }), "list");
  });

  it("nothing to anchor on is generic", () => {
    assert.equal(exampleSet({}), "generic");
    assert.equal(exampleSet({ view: "form", doctype: "Issue" }), "form");
  });
});

describe("openDocumentFrom", () => {
  it("carries the doctype and the name, or nothing", () => {
    assert.deepEqual(openDocumentFrom({ doctype: "Issue", name: "ISS-1" }), {
      doctype: "Issue",
      name: "ISS-1",
    });
    assert.equal(openDocumentFrom({ doctype: "Issue" }), null);
  });
});

describe("examplesFor", () => {
  it("a form asks about that document, naming the doctype", () => {
    const questions = examplesFor({ view: "form", doctype: "Sales Invoice", name: "SINV-1" });
    assert.ok(questions.some((q) => q.includes("Sales Invoice")));
    assert.ok(questions.every((q) => q.includes("?") || q.startsWith("Summarise")));
  });

  it("an Issue is asked about in support terms", () => {
    const questions = examplesFor({ view: "form", doctype: "Issue", name: "ISS-1" });
    assert.deepEqual(questions, [
      "What is the customer asking for?",
      "What has already been done?",
      "What is still open?",
    ]);
  });

  it("a list asks about the list, and counts what it shows", () => {
    const questions = examplesFor({ doctype: "Sales Order" }, 12);
    assert.ok(questions.some((q) => q.startsWith("How many Sales Order")));
    assert.ok(questions.some((q) => q.startsWith("Which Sales Order")));
  });

  it("an empty list offers to create, not to count", () => {
    // "How many are there?" of an empty list is a question about nothing.
    const questions = examplesFor({ doctype: "Sales Order" }, 0);
    assert.deepEqual(questions, ["Create a Sales Order"]);
  });

  it("a report asks about the report", () => {
    const questions = examplesFor({ report: "Accounts Receivable" });
    assert.ok(questions.every((q) => typeof q === "string" && q.length > 0));
  });

  it("generic: 'my' is never used, because nobody knows who that is", () => {
    const questions = examplesFor({});
    assert.ok(questions.every((q) => !/\bmy\b/i.test(q)));
  });

  it("a brand-new document offers to seed it from the last one", () => {
    const questions = examplesFor(
      { view: "form", doctype: "Sales Order" },
      null,
      "Albanna Ltd",
    );
    assert.ok(questions.some((q) => q.includes("Albanna Ltd")));
  });
});
