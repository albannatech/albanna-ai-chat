// The rule of a retry: the failed attempt goes, whole.
//
// A retry is one attempt, not two.  So the question that failed goes with
// the answer that failed with it, and the question is asked again in
// their place — otherwise the transcript reads as the same question
// asked twice, and the reader is left looking at two answers and not
// knowing which one is the answer.
//
// The failed *answer* is removed when the turn fails, because an empty
// bubble says nothing and the error beside it says everything.  What is
// left is the question, and this is what takes it away.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/**
 * Take the failed attempt's question out of the transcript.
 *
 * The list is searched from the end, so it is the *last* attempt at that
 * question that is removed — the one the reader is retrying, and not an
 * older question that happens to read the same.
 *
 * @param {object[]} messages the transcript
 * @param {string} question the question that failed
 * @returns {string} the question to ask again, or "" when there is none
 */
export function takeRetryQuestion(messages, question) {
	const text = String(question == null ? "" : question).trim();
	if (!text || !Array.isArray(messages)) return "";

	for (let index = messages.length - 1; index >= 0; index -= 1) {
		const message = messages[index];
		if (!message || message.role !== "user") continue;
		if (String(message.content || "").trim() !== text) continue;

		// The question, and anything that was said in answer to it.
		messages.splice(index, 1);
		const answer = messages[index];
		if (answer && answer.role === "assistant") {
			messages.splice(index, 1);
		}
		return text;
	}
	return "";
}
