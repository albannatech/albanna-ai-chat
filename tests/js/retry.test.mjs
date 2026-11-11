// The rule of a retry.
//
// The rule under test: a retry is one attempt, not two — so the failed
// attempt's question goes with it, and the question is asked again in its
// place.

import assert from "node:assert";
import { takeRetryQuestion } from "../../albanna_ai_chat/public/js/lib/retry.mjs";

function asked(text) {
	return { role: "user", content: text };
}

function answer(text) {
	return { role: "assistant", content: text };
}

// The question of the failed attempt is taken out.
{
	const messages = [asked("what is open?"), answer("a first try")];
	const question = takeRetryQuestion(messages, "what is open?");

	assert.equal(question, "what is open?");
	assert.equal(messages.length, 0, "the question and its answer go together");
}

// The question alone is taken out, when the answer has already gone.
{
	const messages = [asked("what is open?")];
	const question = takeRetryQuestion(messages, "what is open?");

	assert.equal(question, "what is open?");
	assert.equal(messages.length, 0);
}

// It is the *last* attempt at that question that is taken out, not an
// older one that happens to read the same.
{
	const messages = [asked("what is open?"), answer("an old answer"), asked("what is open?")];
	const question = takeRetryQuestion(messages, "what is open?");

	assert.equal(question, "what is open?");
	assert.equal(messages.length, 2);
	assert.equal(messages[0].content, "what is open?");
	assert.equal(messages[1].content, "an old answer");
}

// A question that is not in the transcript is left alone.
{
	const messages = [asked("something else")];
	const question = takeRetryQuestion(messages, "what is open?");

	assert.equal(question, "");
	assert.equal(messages.length, 1);
}

// A blank question is not a question.
{
	const messages = [asked("what is open?")];
	assert.equal(takeRetryQuestion(messages, ""), "");
	assert.equal(takeRetryQuestion(messages, null), "");
	assert.equal(takeRetryQuestion(null, "what is open?"), "");
	assert.equal(messages.length, 1);
}

// An answer is never mistaken for the question.
{
	const messages = [asked("what is open?"), answer("what is open?")];
	const question = takeRetryQuestion(messages, "what is open?");

	assert.equal(question, "what is open?");
	assert.equal(messages.length, 0);
}

console.log("retry: all assertions passed");
