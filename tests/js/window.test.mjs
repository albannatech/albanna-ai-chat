// The transcript window rule.
//
// The rule under test: the panel draws a window, not a whole thread, and
// the windows are keyed by the stored index so that a spliced transcript
// cannot show the same page twice.

import assert from "node:assert";
import {
	TRANSCRIPT_WINDOW,
	mergeOlder,
	oldestIdx,
	olderRequest,
	windowRequest,
} from "../../albanna_ai_chat/public/js/lib/window.mjs";

function stored(idx, role = "user") {
	return { idx, role, content: `message ${idx}` };
}

// Opening a transcript asks for the newest end.
{
	assert.deepEqual(windowRequest(), { limit: TRANSCRIPT_WINDOW, before_idx: 0 });
	assert.deepEqual(windowRequest(10), { limit: 10, before_idx: 0 });
}

// An older page is the one below an index.
{
	assert.deepEqual(olderRequest(120), { limit: TRANSCRIPT_WINDOW, before_idx: 120 });
	assert.deepEqual(olderRequest("120"), { limit: TRANSCRIPT_WINDOW, before_idx: 120 });
	assert.deepEqual(olderRequest(0), { limit: TRANSCRIPT_WINDOW, before_idx: 0 });
	assert.deepEqual(olderRequest(null), { limit: TRANSCRIPT_WINDOW, before_idx: 0 });
}

// An older page goes in front, oldest first.
{
	const current = [stored(120), stored(121)];
	const older = [stored(118), stored(119)];
	const merged = mergeOlder(current, older);

	assert.deepEqual(
		merged.map((message) => message.idx),
		[118, 119, 120, 121],
	);
}

// A page that overlaps what is on screen is not shown twice.  A
// transcript is spliced — a retry removes the failed turn — so the
// overlap is real, and the index is what catches it.
{
	const current = [stored(120), stored(121)];
	const older = [stored(119), stored(120), stored(121)];
	const merged = mergeOlder(current, older);

	assert.deepEqual(
		merged.map((message) => message.idx),
		[119, 120, 121],
	);
}

// Merging nothing changes nothing.
{
	assert.deepEqual(mergeOlder([stored(1)], []), [stored(1)]);
	assert.deepEqual(mergeOlder([], [stored(1)]), [stored(1)]);
	assert.deepEqual(mergeOlder(null, null), []);
}

// The next older page ends before the oldest stored message on screen.
{
	assert.equal(oldestIdx([stored(120), stored(121)]), 120);
	assert.equal(oldestIdx([stored(120), stored(121)].reverse()), 120);
}

// A message that has not been stored yet has no index, and it is the
// newest one, so it is not the end of the walk.
{
	assert.equal(oldestIdx([{ idx: 0, role: "user" }, stored(120)]), 120);
	assert.equal(oldestIdx([{ role: "user" }]), 0);
	assert.equal(oldestIdx([]), 0);
	assert.equal(oldestIdx(null), 0);
}

console.log("window: all assertions passed");
