// Translation — the reader's language, reached without breaking the tests.
//
// Frappe publishes `__` on the global scope, and every reader-facing sentence in
// this app goes through it. But these modules are imported by tests that run
// under plain node, where `__` does not exist — and a module that throws on
// import in a test is a module whose pure half cannot be tested, which is the
// whole point of having a pure half.
//
// So the guard lives here, once, rather than being copied into every module that
// has a sentence in it. A guard copied into six files is a guard that drifts.
//
// The fallback is the source string, not an empty one. A missing translation
// that renders as blank is a panel with holes in it; a missing translation that
// renders as English is a panel a reader can still use, and a translator can
// still find the string to translate.

/**
 * Translate *text*, substituting ``{0}``, ``{1}``, … from *args*.
 *
 * Frappe's `__` takes the substitutions as an array in its second argument.
 * They are accepted either way — as an array or as rest arguments — because
 * both spellings appear in the wild and a caller that gets it wrong silently
 * renders the placeholders.
 *
 * @param {string} text the source string
 * @param {...*} args substitutions, as an array or as rest arguments
 * @returns {string} the translated, substituted string
 */
export function translate(text, ...args) {
  const source = String(text == null ? "" : text);
  const say = typeof globalThis.__ === "function" ? globalThis.__ : (t) => t;

  // Flatten: `translate("x {0}", ["a"])` and `translate("x {0}", "a")` are the
  // same call, and only one of them is what Frappe's own signature expects.
  const flat = args.length === 1 && Array.isArray(args[0]) ? args[0] : args;

  // The substitutions are handed to Frappe's `__` as its second argument, which
  // is where it expects them. Dropping them would translate the sentence and
  // leave the placeholders in it — a panel reading "Tools used: {0}".
  let out = say(source, flat);
  if (out === source && flat.length) {
    // No translation was applied, so the placeholders are still in the source
    // and must be substituted here — otherwise a translated string and an
    // untranslated one would render differently.
    flat.forEach((value, index) => {
      out = out.split(`{${index}}`).join(String(value));
    });
  }
  return out;
}
