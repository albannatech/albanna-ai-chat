// The turns that are in flight, remembered across a reload.
//
// Ported from `albanna`'s side-chat. One contract-bound constant moved: the
// storage key now comes from `lib/wire.mjs`, which is the one place this
// core's wire assumptions live — `albanna` spelled it out in this file, so a
// change to it was a change found by reading the whole panel.
//
// A reader who reloads the Desk during a turn loses the turn from the
// screen: the worker is still working, and the answer is parked in the
// cache, but the browser forgot the stream it was waiting for.  So the
// stream is written down — in the session's storage, which a reload
// keeps and a closed tab does not — and the panel picks it up again
// when the page comes back.
//
// The entry is per *turn*, not per panel, and that is the whole point
// of this module: a reader may ask a question in one thread, move to
// another, ask again there, and come back.  Both turns are running, and
// each needs its own address remembered — a single slot would have the
// second turn overwrite the first, and the first turn's completion
// erase the second's address on its way out.
//
// The entry is also per *page*: a turn belongs to the thread of the page
// it was asked on, and re-attaching it on another page would put the
// answer in the wrong thread.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

import { INFLIGHT_KEY } from "./wire.mjs";

/** How long a turn may be waited for after a reload. */
export const INFLIGHT_TTL_MS = 4 * 60 * 60 * 1000;

/** How many turns are remembered.
 *
 * A bound, because storage is small and a reader who opens fifty
 * threads in a session should not push the session's storage quota:
 * the newest turns are the ones that can still be picked up, and an
 * old one has either finished or outlived its TTL. */
export const MAX_TURNS = 12;

/**
 * The storage the turns are written to.
 *
 * @returns {object|null} the session's storage, or null when there is
 *   none
 */
function sessionStorageOrNull() {
	try {
		return typeof sessionStorage !== "undefined" ? sessionStorage : null;
	} catch (error) {
		// A browser that refuses its own storage is a browser that
		// cannot be asked to remember anything.
		return null;
	}
}

/**
 * Read every remembered turn, newest first.
 *
 * Expired entries are dropped on the way through: a turn that is hours
 * old is a turn whose worker died, and a reader who comes back should
 * not be shown it.
 *
 * @param {object} [storage] the storage, for the test
 * @returns {Array<object>} the turns, newest first
 */
export function loadInflightTurns(storage) {
	const store = storage || sessionStorageOrNull();
	if (!store) return [];

	try {
		const raw = store.getItem(INFLIGHT_KEY);
		if (!raw) return [];

		const parsed = JSON.parse(raw);
		// The single-slot format this module used before a reader could
		// ask a second question before the first turn finished.  A
		// storage entry written by that version is still a turn.
		const turns = Array.isArray(parsed)
			? parsed
			: parsed && parsed.turns
			? parsed.turns
			: parsed
			? [parsed]
			: [];

		const now = Date.now();
		return turns
			.filter((turn) => turn && turn.stream_id)
			.map((turn) => ({ ...turn, started_at: turn.started_at || now }))
			.filter((turn) => now - turn.started_at <= INFLIGHT_TTL_MS)
			.sort((left, right) => (right.started_at || 0) - (left.started_at || 0));
	} catch (error) {
		return [];
	}
}

/**
 * Write a turn down, keeping the others.
 *
 * Upsert by stream id: a turn that was saved once — the same stream id,
 * perhaps with its approval now attached — replaces its own entry
 * rather than adding a second one.
 *
 * @param {object} entry the turn: `stream_id`, `conversation_id`, `page`
 *   and `question`
 * @param {object} [storage] the storage, for the test
 * @returns {boolean} true when it was written
 */
export function saveInflight(entry, storage) {
	const store = storage || sessionStorageOrNull();
	if (!store || !entry || !entry.stream_id) return false;

	const turns = loadInflightTurns(store).filter((turn) => turn.stream_id !== entry.stream_id);
	const saved = { ...entry, started_at: entry.started_at || Date.now() };
	turns.unshift(saved);
	// True only when the write landed: a storage that refused is a
	// storage the caller must not believe remembered anything.
	return writeTurns(store, turns);
}

/**
 * Forget one turn, and keep the others.
 *
 * A turn finishing must not erase the address of the turn running
 * beside it: each turn cleans up after itself, and only itself.
 *
 * @param {string} streamId the turn's stream id
 * @param {object} [storage] the storage, for the test
 */
export function removeInflight(streamId, storage) {
	const store = storage || sessionStorageOrNull();
	if (!store || !streamId) return;

	const turns = loadInflightTurns(store).filter((turn) => turn.stream_id !== streamId);
	writeTurns(store, turns);
}

/**
 * Forget every turn.
 *
 * @param {object} [storage] the storage, for the test
 */
export function clearInflight(storage) {
	const store = storage || sessionStorageOrNull();
	if (!store) return;
	writeTurns(store, []);
}

/**
 * The remembered turn with this stream id, if it is still remembered.
 *
 * @param {string} streamId the turn's stream id
 * @param {object} [storage] the storage, for the test
 * @returns {object|null} the turn, or null
 */
export function findInflight(streamId, storage) {
	if (!streamId) return null;
	return loadInflightTurns(storage).find((turn) => turn.stream_id === streamId) || null;
}

/**
 * The remembered turns of one conversation.
 *
 * @param {string} conversationId the conversation, empty for the page's
 *   own thread — the thread a first question creates
 * @param {object} [storage] the storage, for the test
 * @returns {Array<object>} its turns, newest first
 */
export function turnsForConversation(conversationId, storage) {
	const wanted = conversationId || "";
	return loadInflightTurns(storage).filter((turn) => (turn.conversation_id || "") === wanted);
}

/**
 * The remembered turns of one page.
 *
 * @param {string} page the page identity
 * @param {object} [storage] the storage, for the test
 * @returns {Array<object>} its turns, newest first
 */
export function turnsForPage(page, storage) {
	return loadInflightTurns(storage).filter((turn) => (turn.page || "") === (page || ""));
}

/**
 * Write the list, bounded.
 *
 * @param {object} store the storage
 * @param {Array<object>} turns the turns, newest first
 * @returns {boolean} true when the write landed
 */
function writeTurns(store, turns) {
	try {
		if (!turns.length) {
			store.removeItem(INFLIGHT_KEY);
			return true;
		}
		store.setItem(INFLIGHT_KEY, JSON.stringify({ turns: turns.slice(0, MAX_TURNS) }));
		return true;
	} catch (error) {
		/* A storage that refuses is a storage that cannot be asked. */
		return false;
	}
}
