/**
 * Tests for the attachment rules — checked before the bytes leave the browser.
 *
 * What these verify is the reader's experience of a rule enforced in the wrong
 * place: a browser that accepts an SVG and a server that refuses it is a reader
 * who chose a file, waited for the upload, and was then told the file they
 * chose could not be attached.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  REFUSED_SIZE,
  REFUSED_TYPE,
  checkAttachment,
  makeAttachment,
  storeAll,
  turnAttachments,
} from "../../albanna_ai_chat/public/js/lib/attachments.mjs";

const RULES = { types: ["image/png", "application/pdf"], maxBytes: 1000 };

describe("checkAttachment", () => {
  it("accepts a file of a type the site takes", () => {
    const result = checkAttachment({ type: "image/png", size: 10 }, RULES);
    assert.deepEqual(result, { ok: true, reason: "" });
  });

  it("refuses a type the site does not take", () => {
    const result = checkAttachment({ type: "image/svg+xml", size: 10 }, RULES);
    assert.equal(result.ok, false);
    assert.equal(result.reason, REFUSED_TYPE);
  });

  it("refuses a file over the site's ceiling", () => {
    const result = checkAttachment({ type: "image/png", size: 5000 }, RULES);
    assert.equal(result.ok, false);
    assert.equal(result.reason, REFUSED_SIZE);
  });

  it("treats a ceiling of zero as no ceiling", () => {
    const result = checkAttachment(
      { type: "image/png", size: 10 ** 9 },
      { types: ["image/png"], maxBytes: 0 },
    );
    assert.equal(result.ok, true);
  });

  it("refuses everything when the site has published no types", () => {
    // A browser that guesses is a browser that guesses wrong.
    const result = checkAttachment({ type: "image/png", size: 1 }, {});
    assert.equal(result.ok, false);
    assert.equal(result.reason, REFUSED_TYPE);
  });

  it("refuses a file with no type at all", () => {
    const result = checkAttachment({ size: 1 }, RULES);
    assert.equal(result.ok, false);
    assert.equal(result.reason, REFUSED_TYPE);
  });

  it("accepts a file exactly at the ceiling", () => {
    const result = checkAttachment({ type: "image/png", size: 1000 }, RULES);
    assert.equal(result.ok, true);
  });
});

describe("makeAttachment", () => {
  it("carries the six fields", () => {
    const a = makeAttachment({
      dataUrl: "data:...",
      name: "x.png",
      type: "image/png",
      size: 5,
      fileUrl: "/files/x.png",
    });
    assert.equal(a.dataUrl, "data:...");
    assert.equal(a.name, "x.png");
    assert.equal(a.type, "image/png");
    assert.equal(a.size, 5);
    assert.equal(a.fileUrl, "/files/x.png");
    assert.equal(a.stored, true);
  });

  it("defaults every field rather than leaving one undefined", () => {
    const a = makeAttachment();
    assert.equal(a.dataUrl, "");
    assert.equal(a.size, 0);
    assert.equal(a.stored, true);
  });

  it("records an explicit not-stored", () => {
    assert.equal(makeAttachment({ stored: false }).stored, false);
  });
});

describe("storeAll", () => {
  it("writes the list once, at the end", () => {
    // Writing after each file lets a later upload overwrite an earlier one,
    // and a reader who dropped three pictures finds one of them gone.
    let writes = 0;
    const files = [{ n: 1 }, { n: 2 }, { n: 3 }];
    storeAll(files, (f) => Promise.resolve({ n: f.n }), () => {
      writes += 1;
    }).then((added) => {
      assert.equal(writes, 1);
      assert.equal(added.length, 3);
    });
  });

  it("keeps the order the reader chose", async () => {
    const files = [{ n: 1 }, { n: 2 }, { n: 3 }];
    const added = await storeAll(files, (f) => Promise.resolve({ n: f.n }), () => {});
    assert.deepEqual(added.map((a) => a.n), [1, 2, 3]);
  });

  it("skips a file the store refused", async () => {
    const added = await storeAll(
      [{ n: 1 }, { n: 2 }],
      (f) => Promise.resolve(f.n === 1 ? { n: 1 } : null),
      () => {},
    );
    assert.deepEqual(added.map((a) => a.n), [1]);
  });

  it("does not write when nothing was stored", async () => {
    let writes = 0;
    await storeAll([{ n: 1 }], () => Promise.resolve(null), () => {
      writes += 1;
    });
    assert.equal(writes, 0);
  });
});

describe("turnAttachments", () => {
  it("builds the two parallel lists together", () => {
    // The address at one place is the address of the bytes at the same place,
    // so the two are built together and never apart.
    const files = [
      makeAttachment({ dataUrl: "d1", fileUrl: "/files/1" }),
      makeAttachment({ dataUrl: "d2", fileUrl: "/files/2" }),
    ];
    const carried = turnAttachments(files);
    assert.deepEqual(carried.attachments, ["d1", "d2"]);
    assert.deepEqual(carried.attachmentUrls, ["/files/1", "/files/2"]);
    assert.equal(carried.attachments.length, carried.attachmentUrls.length);
  });

  it("carries nothing for no attachments", () => {
    assert.deepEqual(turnAttachments([]), { attachments: [], attachmentUrls: [] });
  });
});
