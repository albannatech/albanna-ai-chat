// Which waits belong to which thread.
//
// The bug this file exists to prevent: a wait of another thread counted
// as this thread's.  The symptom is a Stop button that vanishes while a
// turn is still streaming, and a turn that ends in thread A clearing the
// activity line of thread B.

import assert from "node:assert";
import { waitsOfConversation, waitsOfPage } from "../../albanna_ai_chat/public/js/lib/turn-waits.mjs";

/** The panel's waits, as it keeps them. */
function waits(...entries) {
	return entries.map(([streamId, waiting]) => [streamId, waiting]);
}

const pageThread = { controller: {}, conversation: "", page: "List/Sales Order/List" };
const threadA = { controller: {}, conversation: "6bp8e4nplp", page: "List/Sales Order/List" };
const threadB = { controller: {}, conversation: "other-thread", page: "List/Sales Order/List" };
const otherPage = { controller: {}, conversation: "6bp8e4nplp", page: "Form/Item/ITEM-1" };

const all = waits(["s1", pageThread], ["s2", threadA], ["s3", threadB], ["s4", otherPage]);

// The waits of the thread being read, and only those.
{
	const here = waitsOfConversation(all, "6bp8e4nplp");
	assert.deepEqual(
		here.map((wait) => wait.streamId),
		["s2", "s4"],
		"the thread's own turns, whatever page they were asked on",
	);
	assert.equal(here[0].conversation, "6bp8e4nplp");
}

// The page's own thread: a first question's turn has no id yet.
{
	const here = waitsOfConversation(all, "");
	assert.deepEqual(
		here.map((wait) => wait.streamId),
		["s1"],
		"an empty id means this page's own thread, not every thread",
	);
}

// A thread with nothing running is an empty list, not everything.
{
	assert.deepEqual(waitsOfConversation(all, "nobody"), []);
	assert.deepEqual(waitsOfConversation([], "6bp8e4nplp"), []);
}

// The waits of one page: every thread of it, and no other page's.
{
	const page = waitsOfPage(all, "List/Sales Order/List");
	assert.deepEqual(
		page.map((wait) => wait.streamId),
		["s1", "s2", "s3"],
	);
	assert.equal(page[0].controller, pageThread.controller, "the controllers travel with them");

	assert.deepEqual(
		waitsOfPage(all, "Form/Item/ITEM-1").map((wait) => wait.streamId),
		["s4"],
	);
	assert.deepEqual(waitsOfPage(all, "nowhere"), []);
}

console.log("turn-waits: all assertions passed");
