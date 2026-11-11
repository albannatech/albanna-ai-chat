// The transcript window rule.
//
// A conversation holds up to four hundred messages, and a transcript of
// two hundred of them is twenty thousand nodes: the panel would spend
// the better part of a second laying them out, every time it
// re-rendered.  (Measured: 705ms for two hundred messages, in a panel
// that is otherwise instant.)
//
// So the server hands out **windows** and the client pages backwards:
// the newest fifty messages, and an explicit "show earlier messages"
// for what is behind them.  The reader's history is not hidden — it is
// one click away — and the panel is never asked to draw more than a
// window of it.
//
// The windows are keyed by the **stored index**, never by position: a
// transcript is spliced — a retry removes the failed turn — and an
// index-keyed merge would add a page that overlaps what is on screen a
// second time.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/** How many messages one window holds. */
export const TRANSCRIPT_WINDOW = 50;

/**
 * The request that opens a transcript: the newest `limit` messages.
 *
 * `before_idx: 0` means "from the newest end" — the server reads the
 * tail.
 *
 * @param {number} limit how many messages the window holds
 * @returns {{limit: number, before_idx: number}} the request
 */
export function windowRequest(limit = TRANSCRIPT_WINDOW) {
	return { limit, before_idx: 0 };
}

/**
 * The request for the page of messages older than `beforeIdx`.
 *
 * The server answers with the messages whose stored index is below it,
 * so walking back through a transcript is a series of these.
 *
 * @param {number} beforeIdx the index the page ends before
 * @param {number} limit how many messages the window holds
 * @returns {{limit: number, before_idx: number}} the request
 */
export function olderRequest(beforeIdx, limit = TRANSCRIPT_WINDOW) {
	return { limit, before_idx: Number(beforeIdx) || 0 };
}

/**
 * Merge an older page in front of the messages already shown.
 *
 * Older first, and idempotent: a row whose stored index is already on
 * screen is dropped, so a page that overlaps what is shown never appears
 * twice.
 *
 * @param {object[]} current the messages on screen
 * @param {object[]} older the page that came back
 * @returns {object[]} the merged transcript
 */
export function mergeOlder(current, older) {
	const seen = new Set((current || []).map((message) => Number(message.idx) || 0));
	const fresh = (older || []).filter((message) => !seen.has(Number(message.idx) || 0));
	return [...fresh, ...(current || [])];
}

/**
 * The stored index the next older page ends before.
 *
 * The messages that have not been stored yet — the question being
 * answered now — have no index, and they are the *newest* ones, so they
 * are not the end of the walk.
 *
 * @param {object[]} messages the messages on screen
 * @returns {number} the index, or 0 when there is nothing stored yet
 */
export function oldestIdx(messages) {
	const indexes = (messages || [])
		.map((message) => Number(message.idx) || 0)
		.filter((index) => index > 0);
	return indexes.length ? Math.min(...indexes) : 0;
}
