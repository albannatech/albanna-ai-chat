// Tests for the live hint's names — which documents it names, and the line
// that says how many it left out.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  documentRoute,
  moreText,
  namedDocuments,
  unnamedCount,
} from "../../albanna_ai_chat/public/js/lib/nudge.mjs";

describe("documentRoute", () => {
  it("slugifies the doctype the way the Desk's own links do", () => {
    // Lower-case, spaces to dashes, *then* encoded — so the dash is what
    // the reader's URL carries, exactly as `frappe.router.slug` does.
    assert.equal(documentRoute("Sales Invoice", "SINV-0001"), "/app/sales-invoice/SINV-0001");
  });

  it("encodes the parts that are not the Desk's own slug", () => {
    // A document name can carry a slash or a space; the name is encoded,
    // so the route still opens the right document.
    assert.equal(
      documentRoute("Issue", "ISS 1/2"),
      "/app/issue/ISS%201%2F2",
    );
  });
});

describe("namedDocuments", () => {
  it("labels by title, carrying the document's own name alongside", () => {
    const named = namedDocuments({
      doctype: "Sales Invoice",
      documents: [
        { name: "SINV-0001", title: "Albanna Ltd — 1,000" },
        { name: "SINV-0002", title: "Albanna Ltd — 2,000" },
      ],
    });
    assert.equal(named[0].label, "Albanna Ltd — 1,000");
    assert.equal(named[0].name, "SINV-0001");
    assert.equal(named[1].label, "Albanna Ltd — 2,000");
  });

  it("a document with no title is labelled by its name", () => {
    const named = namedDocuments({
      doctype: "Issue",
      documents: [{ name: "ISS-0009" }],
    });
    assert.equal(named[0].label, "ISS-0009");
  });

  it("every link opens what the list's own link opens", () => {
    const named = namedDocuments({
      doctype: "Sales Invoice",
      documents: [{ name: "SINV-0001", title: "T" }],
    });
    assert.equal(named[0].url, documentRoute("Sales Invoice", "SINV-0001"));
  });

  it("draws what it is given — it does not decide the count", () => {
    // A panel that showed three of five names while claiming two were left
    // out would be a panel that cannot be trusted; the server decides the
    // split, and this draws it.
    const payload = { doctype: "Issue", documents: [{ name: "A" }, { name: "B" }], more: 3 };
    assert.equal(namedDocuments(payload).length, 2);
    assert.equal(unnamedCount(payload), 3);
  });

  it("tolerates a payload that is not a payload", () => {
    assert.deepEqual(namedDocuments(null), []);
    assert.deepEqual(namedDocuments({}), []);
    assert.deepEqual(unnamedCount(null), 0);
  });
});

describe("unnamedCount", () => {
  it("counts what was left out, and never a fraction or a negative", () => {
    assert.equal(unnamedCount({ more: 2 }), 2);
    assert.equal(unnamedCount({ more: 2.9 }), 2);
    assert.equal(unnamedCount({ more: -3 }), 0);
    assert.equal(unnamedCount({ more: "x" }), 0);
  });
});

describe("moreText", () => {
  it("says how many were left out", () => {
    assert.equal(moreText(2), "and 2 more");
  });

  it("says nothing when nothing was left out", () => {
    // "and 0 more" is a sentence about nothing — a panel that says it is
    // counting rather than talking.
    assert.equal(moreText(0), "");
    assert.equal(moreText(-1), "");
    assert.equal(moreText(undefined), "");
  });
});
