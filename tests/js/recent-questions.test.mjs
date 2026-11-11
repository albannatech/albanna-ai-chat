// The recent questions sent with a turn.
//
// The rule under test: a follow-up question is only understandable as a
// follow-up if the assistant is told what was asked before, and the list
// is capped so that it stays a convenience rather than a history.

import assert from "node:assert";
import { MAX_RECENT_QUESTIONS, addQuestion, renderRecentQuestions } from "../../albanna_ai_chat/public/js/lib/recent-questions.mjs";

// A question is added to the list.
{
	const asked = addQuestion([], "which sales orders are open?");
	assert.deepEqual(asked, ["which sales orders are open?"]);
}

// The questions accumulate, oldest first.
{
	let asked = [];
	asked = addQuestion(asked, "first");
	asked = addQuestion(asked, "second");
	assert.deepEqual(asked, ["first", "second"]);
}

// The list is capped, and what is dropped is the oldest.
{
	let asked = [];
	for (let index = 0; index < MAX_RECENT_QUESTIONS + 5; index += 1) {
		asked = addQuestion(asked, `question ${index}`);
	}
	assert.equal(asked.length, MAX_RECENT_QUESTIONS);
	assert.equal(asked[0], `question ${5}`);
	assert.equal(asked[asked.length - 1], `question ${MAX_RECENT_QUESTIONS + 4}`);
}

// A blank question is not a question.
{
	assert.deepEqual(addQuestion([], ""), []);
	assert.deepEqual(addQuestion([], "   "), []);
	assert.deepEqual(addQuestion([], null), []);
	assert.deepEqual(addQuestion(["kept"], ""), ["kept"]);
}

// The questions are rendered as one line, because the page context is
// carried as lines and a question that carries a newline would be two.
{
	const asked = addQuestion(addQuestion([], "first\nquestion"), "second");
	assert.equal(renderRecentQuestions(asked), "first question | second");
}

// No questions means no line.
{
	assert.equal(renderRecentQuestions([]), "");
	assert.equal(renderRecentQuestions(null), "");
	assert.equal(renderRecentQuestions(["", "  "]), "");
}

console.log("recent-questions: all assertions passed");
