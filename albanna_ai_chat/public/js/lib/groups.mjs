// The conversations, grouped by when they were last used.
//
// A drawer that lists thirty conversations in one column is a list the
// reader scans rather than reads.  Grouping them by day turns it into
// something a person can navigate: what happened today, what happened
// yesterday, what happened this week, and the rest.
//
// The groups are **keys**, not sentences: the drawer renders them, and
// the renderer's language is the reader's.  A key that carried a
// sentence would carry the wrong one into every other language.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/** The groups, in the order they are shown. */
export const GROUPS = ["today", "yesterday", "week", "earlier"];

/** The group key for pinned conversations, which always show first. */
export const PINNED_GROUP = "pinned";

/**
 * Group the conversations by the day they were last used.
 *
 * Pinned conversations are pulled out first and shown in a dedicated
 * group at the top, so a pinned conversation stays visible at the top of
 * the drawer no matter how old it is. The rest keep their order inside
 * their date group, so the newest is still first.
 *
 * The server already returns rows ordered `pinned desc, last_activity
 * desc`, so pinned rows lead the input; we split them off before the
 * date buckets.
 *
 * @param {object[]} conversations the conversations, newest first
 * @param {number} [now] the moment to judge them against
 * @returns {Array<{key: string, conversations: object[]}>} the groups, in
 *   order, with the empty ones left out
 */
export function groupByDate(conversations, now = Date.now()) {
	const pinned = [];
	const unpinned = [];

	for (const conversation of conversations || []) {
		if (conversation && conversation.pinned) {
			pinned.push(conversation);
		} else {
			unpinned.push(conversation);
		}
	}

	const groups = new Map();

	for (const conversation of unpinned) {
		const key = groupKey(conversation && conversation.last_activity_ts, now);
		if (!groups.has(key)) groups.set(key, []);
		groups.get(key).push(conversation);
	}

	const result = [];

	if (pinned.length) {
		result.push({ key: PINNED_GROUP, conversations: pinned });
	}

	for (const key of GROUPS) {
		if (groups.has(key)) {
			result.push({ key, conversations: groups.get(key) });
		}
	}

	return result;
}

/**
 * The group a moment belongs to.
 *
 * @param {number|string|Date} value the moment
 * @param {number} now the moment to judge it against
 * @returns {string} the group's key
 */
function groupKey(value, now) {
	const when = toDate(value);
	if (!when) return "earlier";

	const days = daysBetween(when, now);
	if (days <= 0) return "today";
	if (days === 1) return "yesterday";
	if (days <= 7) return "week";
	return "earlier";
}

/**
 * How many days apart two moments are, counted between their midnights.
 *
 * Counting between midnights is what makes "yesterday" mean yesterday:
 * an hour before midnight is yesterday, and an hour after midnight is
 * today, and neither is "a day ago".
 *
 * @param {Date} when the moment
 * @param {number} now the moment to judge it against
 * @returns {number} the days
 */
function daysBetween(when, now) {
	const from = startOfDay(when);
	const to = startOfDay(new Date(now));
	return Math.round((to - from) / 86400000);
}

/**
 * The midnight at the start of a day, in the reader's own time.
 *
 * @param {Date} date the moment
 * @returns {Date} the midnight
 */
function startOfDay(date) {
	const start = new Date(date.getTime());
	start.setHours(0, 0, 0, 0);
	return start;
}

/**
 * A moment, as a date.
 *
 * @param {number|string|Date} value the moment
 * @returns {Date|null} the date, or null when the value says nothing
 */
function toDate(value) {
	if (!value) return null;
	if (typeof value === "number") return new Date(value * 1000);
	if (value instanceof Date) return value;
	const date = new Date(String(value).replace(" ", "T"));
	return Number.isNaN(date.getTime()) ? null : date;
}
