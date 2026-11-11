/**
 * Tests for translation — the guard that keeps the pure half testable.
 *
 * What these verify is that a module with a sentence in it can still be imported
 * under plain node, where Frappe's `__` does not exist. A module that throws on
 * import in a test is a module whose pure half cannot be tested.
 */

import assert from "node:assert/strict";
import { describe, it, afterEach } from "node:test";

import { translate } from "../../albanna_ai_chat/public/js/lib/i18n.mjs";

/** Install a fake Frappe `__` that records what it was asked. */
function installTranslator(fn) {
  globalThis.__ = fn;
}

afterEach(() => {
  delete globalThis.__;
});

describe("translate — with no Frappe", () => {
  it("returns the source string rather than throwing", () => {
    assert.equal(translate("Thinking"), "Thinking");
  });

  it("substitutes placeholders itself when nothing translated", () => {
    // Otherwise a translated string and an untranslated one would render
    // differently, and the untranslated one would show raw `{0}`.
    assert.equal(translate("Tools used: {0} · Calls: {1}", [3, 7]), "Tools used: 3 · Calls: 7");
  });

  it("accepts substitutions as rest arguments too", () => {
    assert.equal(translate("Tools used: {0}", [3]), "Tools used: 3");
  });

  it("leaves a string with no placeholders alone", () => {
    assert.equal(translate("Stopped."), "Stopped.");
  });

  it("handles a null or undefined source", () => {
    assert.equal(translate(null), "");
    assert.equal(translate(undefined), "");
  });
});

describe("translate — with a Frappe __", () => {
  it("uses it when it is there", () => {
    installTranslator(() => "TRANSLATED");
    assert.equal(translate("Thinking"), "TRANSLATED");
  });

  it("passes the substitutions through as an array", () => {
    // Frappe's own signature takes them as an array in the second argument.
    let seen = null;
    installTranslator((text, args) => {
      seen = { text, args };
      return text;
    });
    translate("Tools used: {0}", [3, 7]);
    assert.deepEqual(seen.args, [3, 7]);
  });

  it("does not double-substitute when Frappe already did", () => {
    installTranslator((text, args) => text.replace("{0}", String(args[0])));
    assert.equal(translate("Tools used: {0}", [3]), "Tools used: 3");
  });

  it("still substitutes when Frappe returns the source unchanged", () => {
    // A language with no translation for this string yet: Frappe hands back the
    // source, and the placeholders are still in it.
    installTranslator((text) => text);
    assert.equal(translate("Tools used: {0}", [3]), "Tools used: 3");
  });
});
