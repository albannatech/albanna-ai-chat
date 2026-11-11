// The questions the reader has asked, for the assistant to be told about.
//
// A reader who has just asked "which sales orders are open?" and then
// asks "and what are they worth?" means the second question to continue
// the first.  The assistant cannot know that unless it is told what was
// asked before, so the panel sends the recent questions with the turn.
//
// The list is capped, and it is a convenience rather than a history: the
// conversation is the history — it is on the server, it survives a
// reload, and the reader can delete it.  This is the last few questions,
// so that a follow-up can be understood as a follow-up.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/** How many questions are sent with a turn. */
export const MAX_RECENT_QUESTIONS = 10;

/**
 * Add a question to the list of recent questions, oldest first.
 *
 * The list is capped from the *end*, so the questions that are dropped
 * are the oldest: a reader's most recent questions are the ones that
 * explain the question they are asking now.
 *
 * @param {string[]} asked the questions so far
 * @param {string} question the question just asked
 * @returns {string[]} the new list
 */
export function addQuestion(asked, question) {
	const text = oneLine(question);
	if (!text) return asked || [];

	const next = [...(asked || []), text];
	return next.length > MAX_RECENT_QUESTIONS
		? next.slice(next.length - MAX_RECENT_QUESTIONS)
		: next;
}

/**
 * The recent questions, as the one line the prompt carries.
 *
 * @param {string[]} asked the questions
 * @returns {string} the line, or "" when there are none
 */
export function renderRecentQuestions(asked) {
	const rows = (asked || []).map(oneLine).filter(Boolean);
	if (!rows.length) return "";
	return rows.join(" | ");
}

/**
 * One line of text: whitespace collapsed.
 *
 * The page context is carried as lines, and a question that carries a
 * newline of its own would be two lines — and the second would look like
 * part of the framing rather than part of the data.
 *
 * @param {*} value the value
 * @returns {string} the value, on one line
 */
function oneLine(value) {
	if (value === null || value === undefined) return "";
	return String(value).replace(/\s+/g, " ").trim();
}
