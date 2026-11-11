// The rules for sending a question from the composer.
//
// The rule is here and not in the composer because it *is* a rule, and a rule that
// lives in a component is a rule nobody can test: this file is read by plain node,
// with no Vue and no Desk. The composer calls it and does the side effects
// (clearing the box, stopping the microphone) only when it says the question may
// go.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.
//
// What is ported and what is not
// ------------------------------
// The rules are ported from `albanna`'s `submit.mjs` unchanged, because they are
// the right rules: nothing goes while a turn is running, an empty question with no
// attachment is refused, and an over-long one is refused *with its length*, because
// a refusal the reader cannot act on is a refusal that fails.
//
// The translation is not ported. `albanna` carried a private `__` stand-in in this
// file; this core has `lib/i18n.mjs`, and a stand-in copied into a second file is a
// stand-in that drifts from the first.

import { translate } from "./i18n.mjs";

/** The question's ceiling when the site has not published one.
 *
 * A fallback and not the rule: the site publishes its own number through
 * `options()`, the same way it publishes the attachable types, and the composer
 * uses that. This is what a panel rendered before the site answered falls back to
 * — a bound that is this one rather than no bound at all. */
export const DEFAULT_QUESTION_LENGTH = 4000;

/** Why a question may not be sent. */
export const REASONS = {
  BUSY: "busy",
  NO_CHAT: "no-chat",
  EMPTY: "empty",
  TOO_LONG: "too-long",
};

/**
 * Whether a question may be sent, and the question that would be sent.
 *
 * The rules, in order:
 *   - while a turn is running, or chat is not allowed, nothing is sent
 *     (the primary key stops instead);
 *   - an empty question with no attachment is refused;
 *   - a question over the ceiling is refused, with its length, because
 *     a refusal the reader cannot act on is a refusal that fails;
 *   - otherwise the trimmed question is sent.
 *
 * @param {{modelValue?: string, files?: any[], busy?: boolean, canChat?: boolean,
 *          maxLength?: number}} input
 * @returns {{ok: boolean, question: string, reason: string, length: number}}
 */
export function submitDecision(input) {
  const data = input || {};
  if (data.busy) {
    return { ok: false, question: "", reason: REASONS.BUSY, length: 0 };
  }
  if (!data.canChat) {
    return { ok: false, question: "", reason: REASONS.NO_CHAT, length: 0 };
  }
  const question = String(data.modelValue || "").trim();
  const hasFile = Array.isArray(data.files) && data.files.length > 0;
  if (!question && !hasFile) {
    return { ok: false, question: "", reason: REASONS.EMPTY, length: 0 };
  }
  const ceiling = Number(data.maxLength) > 0 ? Number(data.maxLength) : DEFAULT_QUESTION_LENGTH;
  // The length is the *trimmed* length: leading whitespace is not part of the
  // question, and a reader who pasted with an indent should not be charged for it.
  if (question.length > ceiling) {
    return { ok: false, question: "", reason: REASONS.TOO_LONG, length: question.length };
  }
  return { ok: true, question, reason: "", length: question.length };
}

/**
 * What the reader is told when a question may not be sent.
 *
 * A sentence rather than a code, because the composer shows it. Each one says what
 * to do about it — a refusal the reader cannot act on is a refusal that fails.
 *
 * @param {string} reason the code from `submitDecision`
 * @param {number} length the question's length, for the too-long case
 * @param {number} ceiling the ceiling that was exceeded
 * @returns {string} the sentence, or nothing when the question may go
 */
export function refusalText(reason, length = 0, ceiling = DEFAULT_QUESTION_LENGTH) {
  switch (reason) {
    case REASONS.BUSY:
      return translate("A turn is already running. Stop it first.");
    case REASONS.NO_CHAT:
      return translate("You do not have access to the chat.");
    case REASONS.EMPTY:
      return translate("Ask something, or attach a file.");
    case REASONS.TOO_LONG:
      return translate("That question is {0} characters; the limit is {1}.", [length, ceiling]);
    default:
      return "";
  }
}
