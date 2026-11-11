// The question card.
//
// A question the assistant asked is a card in the thread: the question, and the
// answers the reader may choose from. The card is drawn from the server's own
// record of the question, so the same card is in every tab and after every
// reload — and the reader's answer is recorded against that record, not against
// the browser's memory of it.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.
//
// What is ported and what is not
// ------------------------------
// The shape is ported from `albanna`'s `question.mjs`, because a question card is
// a question card. The *address* is not: `albanna` addressed a question by its
// own doctype name, and this core addresses one by the turn it belongs to — see
// `lib/wire.mjs`, whose `answerQuestion` endpoint takes a stream id. A card that
// carried the wrong address would be a card whose answer went nowhere.

import { translate } from "./i18n.mjs";

/** The question is waiting for an answer. */
export const PENDING = "Pending";

/** The question has been answered. */
export const ANSWERED = "Answered";

/**
 * The card, as the browser needs it.
 *
 * Everything the server sends is turned into strings here, so that the template
 * never has to wonder whether a field is a string or a number, and a card that
 * arrives half-built is a card with no buttons rather than a card that throws.
 *
 * @param {object} raw the question, as the server sent it
 * @returns {object} the card
 */
export function questionCard(raw) {
  const card = raw && typeof raw === "object" ? raw : {};
  const options = Array.isArray(card.options) ? card.options : [];

  return {
    name: String(card.name || ""),
    question: String(card.question || ""),
    conversation: String(card.conversation || ""),
    turn: String(card.turn || ""),
    options: options
      .map((option) => ({
        label: String((option && option.label) || ""),
        value: String((option && option.value) || ""),
      }))
      .filter((option) => option.label),
    status: String(card.status || PENDING),
    answer: String(card.answer || ""),
    answerValue: String(card.answer_value || ""),
    multiple: Boolean(card.multiple),
  };
}

/**
 * May the reader answer this question?
 *
 * A question with no options is a question the reader has to type the answer to,
 * and a question that has been answered is a question that has been answered.
 *
 * @param {object} card the card
 * @returns {boolean} true when the card may still be answered
 */
export function canAnswer(card) {
  if (!card || !card.name) return false;
  if (card.status !== PENDING) return false;
  return Boolean(card.options && card.options.length);
}

/**
 * The reader's answer, as the message their next turn carries.
 *
 * The message names the question it answers, because the assistant's own reply
 * says what it needs and the card says what the choices were, and neither is in
 * the transcript. Without the question, an answer of "GOLD-RING-001" is a string
 * with no meaning attached to it.
 *
 * The answer itself is the option's *value* — the document's name, the field
 * value — and not the label the reader saw. The label is a name for a person; the
 * value is the thing the assistant goes on to put in a document, and an answer
 * that carries the label instead is an answer the assistant has to guess at.
 *
 * @param {object} card the card
 * @param {object} option the option the reader chose
 * @returns {string} the message
 */
export function answerMessage(card, option) {
  const question = String((card && card.question) || "").trim();
  const answer = String((option && option.value) || (option && option.label) || "").trim();

  if (!answer) return "";
  if (!question) return answer;

  return translate("The answer to “{0}”: {1}", [question, answer]);
}
