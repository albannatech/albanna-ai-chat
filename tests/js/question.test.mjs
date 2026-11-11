/**
 * Tests for the question card — the shape a reader chooses from.
 *
 * What these verify is that a card which arrives half-built is a card with no
 * buttons rather than a card that throws, and that the answer carried forward is
 * the option's *value* and not the label the reader saw.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ANSWERED,
  PENDING,
  answerMessage,
  canAnswer,
  questionCard,
} from "../../albanna_ai_chat/public/js/lib/question.mjs";

const RAW = {
  name: "Q-0001",
  question: "Which customer?",
  conversation: "conv-1",
  turn: "conv-1",
  options: [
    { label: "Acme Corp", value: "CUST-0001" },
    { label: "Globex", value: "CUST-0002" },
  ],
  status: PENDING,
  multiple: false,
};

describe("questionCard", () => {
  it("carries the question and its options", () => {
    const card = questionCard(RAW);
    assert.equal(card.question, "Which customer?");
    assert.equal(card.options.length, 2);
    assert.equal(card.options[0].value, "CUST-0001");
  });

  it("turns every field into a string", () => {
    // So the template never has to wonder whether a field is a string or a number.
    const card = questionCard({ name: 7, question: 9, options: [] });
    assert.equal(card.name, "7");
    assert.equal(card.question, "9");
  });

  it("drops an option with no label", () => {
    // A button with no text on it is not a choice.
    const card = questionCard({
      options: [{ label: "Acme", value: "CUST-0001" }, { value: "CUST-0002" }],
    });
    assert.equal(card.options.length, 1);
  });

  it("survives a card that arrives half-built", () => {
    const card = questionCard(null);
    assert.equal(card.question, "");
    assert.deepEqual(card.options, []);
    assert.equal(card.status, PENDING);
  });

  it("defaults the status to pending", () => {
    assert.equal(questionCard({}).status, PENDING);
  });

  it("reads the answer value from the server's snake_case field", () => {
    const card = questionCard({ ...RAW, status: ANSWERED, answer: "Acme", answer_value: "CUST-0001" });
    assert.equal(card.answer, "Acme");
    assert.equal(card.answerValue, "CUST-0001");
  });
});

describe("canAnswer", () => {
  it("allows a pending question with options", () => {
    assert.equal(canAnswer(questionCard(RAW)), true);
  });

  it("refuses an answered question", () => {
    assert.equal(canAnswer(questionCard({ ...RAW, status: ANSWERED })), false);
  });

  it("refuses a question with no options", () => {
    // The reader has to type the answer, which this card does not offer.
    assert.equal(canAnswer(questionCard({ ...RAW, options: [] })), false);
  });

  it("refuses a card with no name", () => {
    assert.equal(canAnswer(questionCard({ options: [{ label: "x", value: "y" }] })), false);
  });

  it("refuses nothing at all", () => {
    assert.equal(canAnswer(null), false);
  });
});

describe("answerMessage", () => {
  it("carries the option's value, not its label", () => {
    // The label is a name for a person; the value is the thing the assistant goes
    // on to put in a document.
    const message = answerMessage(questionCard(RAW), { label: "Acme Corp", value: "CUST-0001" });
    assert.ok(message.includes("CUST-0001"));
    assert.ok(!message.includes("Acme Corp"));
  });

  it("names the question it answers", () => {
    // Without it, an answer of "CUST-0001" is a string with no meaning attached.
    const message = answerMessage(questionCard(RAW), { value: "CUST-0001" });
    assert.ok(message.includes("Which customer?"));
  });

  it("falls back to the label when there is no value", () => {
    const message = answerMessage(questionCard(RAW), { label: "Acme Corp" });
    assert.ok(message.includes("Acme Corp"));
  });

  it("returns nothing when there is no answer", () => {
    assert.equal(answerMessage(questionCard(RAW), {}), "");
    assert.equal(answerMessage(questionCard(RAW), null), "");
  });

  it("returns the bare answer when the card has no question", () => {
    assert.equal(answerMessage(questionCard({}), { value: "CUST-0001" }), "CUST-0001");
  });
});
