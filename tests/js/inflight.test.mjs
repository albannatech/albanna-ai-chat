// The turns that are in flight, remembered across a reload.
//
// The rule under test: a reader who reloads during a turn finds the
// turn again — every turn they asked, not only the last one, and only
// the turns of the page they are on.

import assert from "node:assert";
import { INFLIGHT_KEY } from "../../albanna_ai_chat/public/js/lib/wire.mjs";
import {
	INFLIGHT_TTL_MS,
	MAX_TURNS,
	clearInflight,
	loadInflightTurns,
	removeInflight,
	saveInflight,
	turnsForConversation,
	turnsForPage,
} from "../../albanna_ai_chat/public/js/lib/inflight.mjs";

/** A storage that keeps what it is given, like a browser's. */
function memoryStorage(initial) {
	const data = new Map(Object.entries(initial || {}));
	return {
		getItem: (key) => (data.has(key) ? data.get(key) : null),
		setItem: (key, value) => data.set(key, value),
		removeItem: (key) => data.delete(key),
		data,
	};
}

const turn = {
	stream_id: "abc123",
	conversation_id: "6bp8e4nplp",
	page: "List/Sales Order/List",
	question: "كم عدد أوامر البيع؟",
};

// A turn is written down and read back.
{
	const storage = memoryStorage();
	assert.equal(saveInflight(turn, storage), true);

	const [entry] = loadInflightTurns(storage);
	assert.equal(entry.stream_id, "abc123");
	assert.equal(entry.conversation_id, "6bp8e4nplp");
	assert.equal(entry.page, "List/Sales Order/List");
	assert.equal(entry.question, "كم عدد أوامر البيع؟");
	assert.ok(entry.started_at, "the entry says when it was written");
}

// A second turn is remembered beside the first, newest first — the two
// turns of a reader who asked, moved, and asked again.
{
	const storage = memoryStorage();
	saveInflight(turn, storage);
	saveInflight(
		{
			...turn,
			stream_id: "def456",
			conversation_id: "other-thread",
			question: "the second question",
		},
		storage,
	);

	const turns = loadInflightTurns(storage);
	assert.equal(turns.length, 2, "both turns are remembered");
	assert.equal(turns[0].stream_id, "def456", "the newest first");
	assert.equal(turns[1].stream_id, "abc123", "and the first beside it");
}

// The same stream saved twice is one turn, updated — an approval
// attaching to a running turn must not duplicate it.
{
	const storage = memoryStorage();
	saveInflight(turn, storage);
	saveInflight({ ...turn, approval: { request_id: "req-1" } }, storage);

	const turns = loadInflightTurns(storage);
	assert.equal(turns.length, 1);
	assert.equal(turns[0].approval.request_id, "req-1");
}

// One turn finishing forgets only itself: the turn running beside it
// keeps its address, so a reload still finds it.
{
	const storage = memoryStorage();
	saveInflight(turn, storage);
	saveInflight({ ...turn, stream_id: "def456" }, storage);

	removeInflight("abc123", storage);
	const turns = loadInflightTurns(storage);
	assert.equal(turns.length, 1);
	assert.equal(turns[0].stream_id, "def456");
}

// The list is bounded: the newest turns are the ones worth keeping.
{
	const storage = memoryStorage();
	for (let index = 0; index < MAX_TURNS + 5; index += 1) {
		saveInflight({ ...turn, stream_id: `stream-${index}` }, storage);
	}
	const turns = loadInflightTurns(storage);
	assert.equal(turns.length, MAX_TURNS);
	assert.equal(turns[0].stream_id, `stream-${MAX_TURNS + 4}`, "the newest survive");
}

// Nothing written means nothing to read.
{
	assert.deepEqual(loadInflightTurns(memoryStorage()), []);
	assert.deepEqual(loadInflightTurns(memoryStorage({ [INFLIGHT_KEY]: "not json" })), []);
	assert.deepEqual(loadInflightTurns(memoryStorage({ [INFLIGHT_KEY]: "{}" })), []);
}

// A turn that has been there too long is not a turn any more.
{
	const storage = memoryStorage({
		[INFLIGHT_KEY]: JSON.stringify({
			...turn,
			started_at: Date.now() - INFLIGHT_TTL_MS - 1000,
		}),
	});
	assert.deepEqual(loadInflightTurns(storage), []);
}

// An entry written by the single-slot version is still a turn.
{
	const storage = memoryStorage({
		[INFLIGHT_KEY]: JSON.stringify({ ...turn, started_at: Date.now() - 1000 }),
	});
	const [entry] = loadInflightTurns(storage);
	assert.equal(entry.stream_id, "abc123");
}

// A turn that is still within its time is read.
{
	const storage = memoryStorage({
		[INFLIGHT_KEY]: JSON.stringify({ turns: [{ ...turn, started_at: Date.now() - 1000 }] }),
	});
	assert.equal(loadInflightTurns(storage)[0].stream_id, "abc123");
}

// Every turn can be forgotten.
{
	const storage = memoryStorage();
	saveInflight(turn, storage);
	saveInflight({ ...turn, stream_id: "def456" }, storage);
	clearInflight(storage);
	assert.deepEqual(loadInflightTurns(storage), []);
}

// A turn with no stream is not a turn.
{
	const storage = memoryStorage();
	assert.equal(saveInflight({ question: "no stream" }, storage), false);
	assert.deepEqual(loadInflightTurns(storage), []);
}

// The turns of one conversation — including the page's own thread, whose
// id is empty until the first question creates it.
{
	const storage = memoryStorage();
	saveInflight(turn, storage);
	saveInflight({ ...turn, stream_id: "def456", conversation_id: "" }, storage);
	saveInflight({ ...turn, stream_id: "ghi789", conversation_id: "third" }, storage);

	assert.deepEqual(
		turnsForConversation("6bp8e4nplp", storage).map((entry) => entry.stream_id),
		["abc123"],
	);
	assert.deepEqual(
		turnsForConversation("", storage).map((entry) => entry.stream_id),
		["def456"],
	);
	assert.deepEqual(turnsForConversation("nobody", storage), []);
}

// The turns of one page: a turn belongs to the thread of the page it was
// asked on.
{
	const storage = memoryStorage();
	saveInflight(turn, storage);
	saveInflight({ ...turn, stream_id: "def456", page: "Form/Item/ITEM-1" }, storage);

	assert.deepEqual(
		turnsForPage("List/Sales Order/List", storage).map((entry) => entry.stream_id),
		["abc123"],
	);
	assert.deepEqual(
		turnsForPage("Form/Item/ITEM-1", storage).map((entry) => entry.stream_id),
		["def456"],
	);
	assert.deepEqual(turnsForPage("", storage), []);
}

// A storage that refuses is a storage that cannot be asked to remember.
{
	const broken = {
		getItem: () => null,
		setItem: () => {
			throw new Error("no");
		},
		removeItem: () => {
			throw new Error("no");
		},
	};
	assert.equal(saveInflight(turn, broken), false);
	assert.deepEqual(loadInflightTurns(broken), []);
	clearInflight(broken);
	removeInflight("abc123", broken);
}

console.log("inflight: all assertions passed");
