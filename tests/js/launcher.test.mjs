// The launcher's pure geometry.
//
// Clamping, restoring a width from storage, side selection, and which
// physical edge the resize handle faces — all of it runs under plain node,
// with no frappe and no DOM.

import assert from "node:assert";
import {
	WIDTH_KEY,
	MIN_WIDTH,
	MAX_WIDTH,
	KEYBOARD_STEP,
	DEFAULT_WIDTH,
	clampWidth,
	readStoredWidth,
	sideFor,
	pinnedRight,
} from "../../albanna_ai_chat/public/js/lib/launcher.mjs";

// Constants are exported from one home.
{
	assert.equal(WIDTH_KEY, "albanna.side-chat.width");
	assert.equal(MIN_WIDTH, 320);
	assert.equal(MAX_WIDTH, 720);
	assert.equal(KEYBOARD_STEP, 24);
	assert.equal(DEFAULT_WIDTH, 400);
}

// Clamping at both bounds and beyond.
{
	assert.equal(clampWidth(100), MIN_WIDTH);
	assert.equal(clampWidth(1000), MAX_WIDTH);
	assert.equal(clampWidth(400), 400);
	assert.equal(clampWidth(320.4), 320);
	assert.equal(clampWidth(719.6), 720);
}

// A stored value that is out of range or unparseable falls back.
{
	const storage = { getItem: (k) => "9999" };
	assert.equal(readStoredWidth(storage), DEFAULT_WIDTH);
	const storage2 = { getItem: (k) => "abc" };
	assert.equal(readStoredWidth(storage2), DEFAULT_WIDTH);
	const storage3 = { getItem: (k) => "" };
	assert.equal(readStoredWidth(storage3), DEFAULT_WIDTH);
	const storage4 = { getItem: (k) => "500" };
	assert.equal(readStoredWidth(storage4), 500);
}

// A storage whose getItem throws returns the default rather than propagating.
{
	const storage = { getItem: () => { throw new Error("no storage"); } };
	assert.equal(readStoredWidth(storage), DEFAULT_WIDTH);
	assert.equal(readStoredWidth(null), DEFAULT_WIDTH);
}

// sideFor for each configured position.
{
	assert.equal(sideFor("bottom-left"), "inline-start");
	assert.equal(sideFor("bottom-right"), "inline-end");
	assert.equal(sideFor("floating"), "inline-end");
	assert.equal(sideFor(undefined), "inline-end");
}

// pinnedRight for all four (side x direction) combinations.
{
	assert.equal(pinnedRight("inline-end", false), true);
	assert.equal(pinnedRight("inline-end", true), false);
	assert.equal(pinnedRight("inline-start", false), false);
	assert.equal(pinnedRight("inline-start", true), true);
}
