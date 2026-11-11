// The conversations, grouped by when they were last used.
//
// The rule under test: a drawer that lists thirty conversations in one
// column is a list the reader scans rather than reads, so the
// conversations are grouped by day — and "yesterday" means yesterday,
// not "a day ago".

import assert from "node:assert";
import { GROUPS, PINNED_GROUP, groupByDate } from "../../albanna_ai_chat/public/js/lib/groups.mjs";

/** A moment, as epoch seconds. */
function at(date) {
	return Math.floor(date.getTime() / 1000);
}

/** The same day, a number of days ago, at the given hour. */
function daysAgo(now, days, hour = 12) {
	const date = new Date(now.getTime());
	date.setDate(date.getDate() - days);
	date.setHours(hour, 0, 0, 0);
	return at(date);
}

const now = new Date("2026-10-21T15:00:00");

// A conversation from today, one from yesterday, one from this week and
// one from earlier are in four groups, in that order.
{
	const groups = groupByDate(
		[
			{ name: "earlier", last_activity_ts: daysAgo(now, 40) },
			{ name: "week", last_activity_ts: daysAgo(now, 3) },
			{ name: "yesterday", last_activity_ts: daysAgo(now, 1) },
			{ name: "today", last_activity_ts: daysAgo(now, 0) },
		],
		now.getTime(),
	);

	assert.deepEqual(
		groups.map((group) => group.key),
		["today", "yesterday", "week", "earlier"],
	);
	assert.deepEqual(
		groups.map((group) => group.conversations[0].name),
		["today", "yesterday", "week", "earlier"],
	);
}

// An empty group is left out.
{
	const groups = groupByDate(
		[{ name: "today", last_activity_ts: daysAgo(now, 0) }],
		now.getTime(),
	);
	assert.deepEqual(
		groups.map((group) => group.key),
		["today"],
	);
}

// The conversations keep their order inside a group.
{
	const groups = groupByDate(
		[
			{ name: "newest", last_activity_ts: daysAgo(now, 0, 14) },
			{ name: "older", last_activity_ts: daysAgo(now, 0, 9) },
		],
		now.getTime(),
	);
	assert.deepEqual(
		groups[0].conversations.map((conversation) => conversation.name),
		["newest", "older"],
	);
}

// "Yesterday" means yesterday: an hour before midnight is yesterday,
// even though it is not a whole day ago.
{
	const justBeforeMidnight = new Date("2026-10-20T23:30:00");
	const groups = groupByDate(
		[{ name: "late", last_activity_ts: at(justBeforeMidnight) }],
		now.getTime(),
	);
	assert.equal(groups[0].key, "yesterday");
}

// And an hour after midnight is today.
{
	const justAfterMidnight = new Date("2026-10-21T00:30:00");
	const groups = groupByDate(
		[{ name: "early", last_activity_ts: at(justAfterMidnight) }],
		now.getTime(),
	);
	assert.equal(groups[0].key, "today");
}

// A week is a week: the eighth day is earlier.
{
	const groups = groupByDate(
		[
			{ name: "seven", last_activity_ts: daysAgo(now, 7) },
			{ name: "eight", last_activity_ts: daysAgo(now, 8) },
		],
		now.getTime(),
	);
	assert.equal(groups.find((group) => group.conversations[0].name === "seven").key, "week");
	assert.equal(groups.find((group) => group.conversations[0].name === "eight").key, "earlier");
}

// A conversation that says nothing about when it was used is an old one.
{
	const groups = groupByDate([{ name: "unknown" }], now.getTime());
	assert.equal(groups[0].key, "earlier");
}

// No conversations are no groups.
{
	assert.deepEqual(groupByDate([], now.getTime()), []);
	assert.deepEqual(groupByDate(null, now.getTime()), []);
}

// The groups are in a fixed order.
{
	assert.deepEqual(GROUPS, ["today", "yesterday", "week", "earlier"]);
}

// A pinned conversation is pulled out of the date buckets and shown in
// its own group at the top, so it stays visible however old it is.
{
	const groups = groupByDate(
		[
			{ name: "pinned-old", pinned: 1, last_activity_ts: daysAgo(now, 40) },
			{ name: "today", last_activity_ts: daysAgo(now, 0) },
			{ name: "pinned-new", pinned: 1, last_activity_ts: daysAgo(now, 2) },
		],
		now.getTime(),
	);
	assert.deepEqual(
		groups.map((group) => group.key),
		[PINNED_GROUP, "today"],
	);
	assert.deepEqual(
		groups[0].conversations.map((conversation) => conversation.name),
		["pinned-old", "pinned-new"],
	);
}

// A pinned conversation is in the pinned group and not in a date group
// as well: the reader must not see the same thread twice.
{
	const groups = groupByDate(
		[
			{ name: "pinned", pinned: 1, last_activity_ts: daysAgo(now, 0) },
			{ name: "plain", last_activity_ts: daysAgo(now, 0) },
		],
		now.getTime(),
	);
	const names = groups.flatMap((group) => group.conversations.map((c) => c.name));
	assert.deepEqual(names.sort(), ["pinned", "plain"]);
	assert.equal(names.filter((name) => name === "pinned").length, 1);
}

// The pinned group is left out when nothing is pinned.
{
	const groups = groupByDate(
		[{ name: "today", last_activity_ts: daysAgo(now, 0) }],
		now.getTime(),
	);
	assert.deepEqual(
		groups.map((group) => group.key),
		["today"],
	);
}

// A pinned conversation that says nothing about when it was used is
// still pinned: pinning is the reader's decision, not the clock's.
{
	const groups = groupByDate([{ name: "pinned", pinned: 1 }], now.getTime());
	assert.deepEqual(
		groups.map((group) => group.key),
		[PINNED_GROUP],
	);
}

console.log("groups: all assertions passed");
