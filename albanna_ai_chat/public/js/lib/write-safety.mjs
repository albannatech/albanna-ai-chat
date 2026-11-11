// What counts as a destructive write, and what it costs.
//
// The confirmation card is the widget saying *this one changes data*. Some of
// those are recoverable and some are not, and the reader deserves to know which
// before they press the button — a file whose text was replaced can be replaced
// back, and a file that was created in error cannot be removed from here.
//
// This was a bare comparison in the panel, tested by nobody. That is the kind of
// line that stays wrong: a tool added to the manifest tomorrow would destroy data
// without the card saying so, and nothing would fail. So the list is a list, with
// a test that names every tool the manifest carries and says whether it is on it.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.
//
// What is rewritten rather than ported
// -----------------------------------
// `albanna`'s list named `cancel_doc` and `delete_doc`, because those were its
// two irreversible writes. This core's answer is read from its own contract
// rather than guessed: `edit_file` declares `mechanism="reverse"` — swap the two
// strings and the file returns to what it was — so it is *not* destructive.
// `write_file` declares `mechanism="none"`, because the core ships no
// `delete_file` and a File created in error is removed by an operator holding
// delete rights. That one is.
//
// The distinction is not cosmetic. A card that warns about a recoverable write is
// a card the reader learns to read past, and then the warning means nothing when
// a genuinely irreversible one arrives.

import { translate } from "./i18n.mjs";

/**
 * The tools whose writes cannot be undone from here.
 *
 * A `Set` rather than an array so an extension can add its own without editing
 * this file — and a test asserts the set agrees with the Python contract's
 * `mechanism === "none"` tools, so a tool that becomes irreversible is a tool the
 * card starts warning about, rather than one that silently destroys data.
 */
export const DESTRUCTIVE_TOOLS = new Set(["write_file"]);

/**
 * What the reader is told a destructive write will do.
 *
 * A sentence only for the destructive ones: a card that warns about a write that
 * is recoverable is a card the reader learns to read past.
 */
export const CONSEQUENCES = {
  write_file: translate(
    "This creates a file. The core ships no tool that removes one, so an operator must delete it.",
  ),
};

/**
 * Whether a tool may take something away that cannot be put back.
 *
 * @param {string} toolName the tool the model called
 * @returns {boolean} true when the write is destructive
 */
export function isDestructiveTool(toolName) {
  return DESTRUCTIVE_TOOLS.has(String(toolName || ""));
}

/**
 * What the reader is told the destructive write will do.
 *
 * @param {string} toolName the tool the model called
 * @returns {string} the sentence, or nothing to show
 */
export function destructiveConsequence(toolName) {
  const key = String(toolName || "");
  if (!DESTRUCTIVE_TOOLS.has(key)) return "";
  return CONSEQUENCES[key] || translate("This change cannot be undone from here.");
}

/**
 * Declare a tool destructive, with what it costs.
 *
 * The seam an extension uses. It is a function rather than direct mutation of the
 * set so the consequence is declared at the same time — a tool marked destructive
 * with no sentence is a card that warns and then says nothing.
 *
 * @param {string} toolName the tool's name
 * @param {string} consequence what the reader is told
 */
export function declareDestructive(toolName, consequence) {
  const key = String(toolName || "");
  if (!key) return;
  DESTRUCTIVE_TOOLS.add(key);
  CONSEQUENCES[key] = String(consequence || "") || translate("This change cannot be undone from here.");
}

/**
 * The value a diff row shows, when the field had nothing in it.
 *
 * A field that was empty and now is not is the commonest diff there is, and an
 * empty cell does not say "nothing was here" — it says "broken". The dash is the
 * mark every diff the reader has seen uses for it. A real zero and a real "false"
 * are values: only null, undefined and the empty string count as nothing, so a
 * rate of 0 still reads as 0.
 *
 * @param {*} value the value the field carried
 * @returns {string} the value to show
 */
export function diffValue(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}
