// The approval card's clock.
//
// The rules under test: the card is actionable for exactly as long as
// the server's window says — no longer, no shorter — and the countdown
// and the clickability are the same judgment, read from the same
// number, so they cannot disagree.

import assert from "node:assert";
import { APPROVAL_WINDOW_MS, canDecide, remainingSeconds, windowMs } from "../../albanna_ai_chat/public/js/lib/approval.mjs";

// The window the server sends is the window the card uses.
{
	const approval = { request_id: "abc", at: 1000, window_seconds: 300 };
	assert.equal(windowMs(approval), 300000, "the server's number is the window");
	assert.equal(remainingSeconds(approval, 1000), 300);
	assert.equal(canDecide(approval, 1000 + 299000), true, "and it holds for that long");
	assert.equal(canDecide(approval, 1000 + 300000), false);
}

// An event that arrived without a window falls back to the default,
// rather than to "no window at all" or "already expired".
{
	const approval = { request_id: "abc", at: 1000 };
	assert.equal(windowMs(approval), APPROVAL_WINDOW_MS);
	assert.equal(remainingSeconds(approval, 1000), 120);
}

// Nonsense from the wire is clamped, not obeyed: a window of a
// millisecond or of a day is a bug somewhere else, and the card still
// has to behave.
{
	assert.equal(windowMs({ request_id: "a", window_seconds: 0 }), APPROVAL_WINDOW_MS);
	assert.equal(windowMs({ request_id: "a", window_seconds: -5 }), APPROVAL_WINDOW_MS);
	assert.equal(windowMs({ request_id: "a", window_seconds: 1 }), 30000, "the floor holds");
	assert.equal(
		windowMs({ request_id: "a", window_seconds: 99999 }),
		600000,
		"and so does the ceiling",
	);
	assert.equal(
		windowMs({ request_id: "a", window_seconds: "45" }),
		45000,
		"a string is still a number",
	);
	assert.equal(windowMs(null), APPROVAL_WINDOW_MS);
}

// An approval with no request id cannot be decided.
{
	assert.equal(canDecide({ at: 1000 }, 1000), false);
	assert.equal(canDecide(null, 1000), false);
}

// An approval with no timestamp cannot be decided.
{
	assert.equal(canDecide({ request_id: "abc" }, 1000), false);
}

// The countdown and the actionable window agree, by construction.
{
	const approval = { request_id: "abc", at: 1000 };
	// Just opened: the full window, rounded up.
	assert.equal(remainingSeconds(approval, 1000), 120);
	// One second in.
	assert.equal(remainingSeconds(approval, 2000), 119);
	// Half a second in still says 120 — it counts the whole first second.
	assert.equal(remainingSeconds(approval, 1500), 120);
	// The last actionable instant still says 1, not 0.
	assert.equal(remainingSeconds(approval, 1000 + APPROVAL_WINDOW_MS - 100), 1);
	// Expired: zero, and the card is not clickable either.
	assert.equal(remainingSeconds(approval, 1000 + APPROVAL_WINDOW_MS), 0);
	assert.equal(canDecide(approval, 1000 + APPROVAL_WINDOW_MS), false);
}

// An unusable approval says 0 seconds rather than a number.
{
	assert.equal(remainingSeconds(null, 1000), 0);
	assert.equal(remainingSeconds({ at: 1000 }, 1000), 0);
}

console.log("approval: all assertions passed");
