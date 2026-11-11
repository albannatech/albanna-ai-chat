// Which waits belong to which thread.
//
// A panel waits for the turns of the thread it is showing.  "Which
// thread" sounds like the easy part, and it is the part that is easy to
// get subtly wrong in three ways at once:
//
//   - a turn asked as the page's *first* question is remembered with no
//     conversation id yet, because the conversation is created by the
//     answer — so "no id" means "this page's own thread", not "no
//     thread";
//   - a turn in another thread must never be treated as this thread's,
//     or its ending clears this thread's Stop button;
//   - the panel is showing exactly one thread, so the answer is a list,
//     and an empty list is an answer ("nothing running here"), not a
//     failure to find something.
//
// Pure: no `frappe`, no DOM, no Vue — so it is tested under plain node,
// which is where a wrong answer here would otherwise only show up as a
// Stop button that vanishes at the wrong moment.

/**
 * The waits of one conversation, newest last.
 *
 * @param {Array<[string, object]>} entries the waits, as the panel keeps
 *   them: `[streamId, {controller, conversation, page}]`
 * @param {string} conversationId the thread, empty for the page's own
 *   thread before its first question created it
 * @returns {Array<{streamId: string, controller: AbortController, conversation: string, page: string}>}
 */
export function waitsOfConversation(entries, conversationId) {
	const wanted = conversationId || "";
	return entries
		.filter(([, waiting]) => (waiting.conversation || "") === wanted)
		.map(([streamId, waiting]) => ({ streamId, ...waiting }));
}

/**
 * The waits of one page.
 *
 * A page may hold several threads, and every thread of it is the
 * reader's to come back to — so a route change stops the waits of the
 * page being left, all of them, and none of another page's.
 *
 * @param {Array<[string, object]>} entries the waits
 * @param {string} page the page identity
 * @returns {Array<{streamId: string, controller: AbortController}>}
 */
export function waitsOfPage(entries, page) {
	const wanted = page || "";
	return entries
		.filter(([, waiting]) => (waiting.page || "") === wanted)
		.map(([streamId, waiting]) => ({ streamId, controller: waiting.controller }));
}
