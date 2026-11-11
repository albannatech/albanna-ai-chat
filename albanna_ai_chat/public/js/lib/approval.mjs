// The write-approval card.
//
// A write that waits for the reader does so for as long as the server
// said it would — the server owns the deadline, and sends it with the
// approval event.  The card does not keep a second opinion: a countdown
// that runs on the browser's clock against a different constant tells
// the reader they have time they do not have, and the reader decides
// how long to take by it.
//
// After the window the worker has already recorded a timeout, and a card
// that still offers "Approve" is a card that lies.  So the card is only
// actionable while the wait is still open, and when it is not it says so
// rather than going quiet.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/** How long a write waits for the reader, in milliseconds.
 *
 * Only a default: an approval that carries the server's window uses
 * that instead, and this is what a card falls back to if the event
 * arrived without one. */
export const APPROVAL_WINDOW_MS = 120000;

/** The shortest a wait may be, in seconds — the server's floor. */
export const MIN_WINDOW_SECONDS = 30;

/** The longest a wait may be, in seconds — the server's ceiling. */
export const MAX_WINDOW_SECONDS = 600;

/**
 * The window one approval was given, in milliseconds.
 *
 * @param {{window_seconds?: number}} approval the pending approval
 * @returns {number} the window, clamped to the server's bounds
 */
export function windowMs(approval) {
	const seconds = Number(approval && approval.window_seconds);
	if (!Number.isFinite(seconds) || seconds <= 0) {
		return APPROVAL_WINDOW_MS;
	}
	return Math.min(Math.max(seconds, MIN_WINDOW_SECONDS), MAX_WINDOW_SECONDS) * 1000;
}

/**
 * Whether the card may still be decided.
 *
 * @param {{at?: number, window_seconds?: number}} approval the pending approval
 * @param {number} now the current time, in milliseconds
 * @returns {boolean}
 */
export function canDecide(approval, now) {
	if (!approval || !approval.request_id) return false;
	const at = Number(approval.at);
	if (!Number.isFinite(at)) return false;
	return Number(now) - at < windowMs(approval);
}

/**
 * The seconds left on the wait, floored at zero.
 *
 * This is what the card's countdown says.  It agrees with
 * :func:`canDecide` by construction — both read the same window — so the
 * card cannot show "3s left" while refusing to be clicked, or the other
 * way round.
 *
 * @param {{at?: number, window_seconds?: number}} approval the pending approval
 * @param {number} now the current time, in milliseconds
 * @returns {number} whole seconds left, zero when the wait has run out
 */
export function remainingSeconds(approval, now) {
	if (!canDecide(approval, now)) return 0;
	const at = Number(approval.at);
	return Math.max(0, Math.ceil((windowMs(approval) - (Number(now) - at)) / 1000));
}
