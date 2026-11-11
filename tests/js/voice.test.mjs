// The rules of the microphone, under plain node.

import { describe, it } from "node:test";
import assert from "node:assert";

import { MAX_SESSION_MS, mergeTranscript, readResults, voiceErrorText } from "../../albanna_ai_chat/public/js/lib/voice.mjs";

function results(list) {
	// A SpeechRecognitionResultList is array-like with length and item().
	// Each result (`results[i]`) carries `.isFinal`; its transcript is on
	// `results[i][0].transcript` (the first SpeechRecognitionAlternative).
	const holder = list.map((entry) => {
		const inner = { transcript: entry.transcript || "" };
		inner.isFinal = !!entry.isFinal;
		inner[0] = inner;
		return inner;
	});
	holder.length = list.length;
	holder.item = (i) => holder[i];
	return holder;
}

describe("readResults", () => {
	it("takes a final once, not twice", () => {
		const list = results([{ transcript: "show me the invoice", isFinal: true }]);
		const first = readResults(list, 0, 0);
		assert.deepEqual(first.finals, ["show me the invoice"]);
		assert.equal(first.nextFinal, 1);

		// The browser reports the same final again on the next event.
		const again = readResults(list, 0, first.nextFinal);
		assert.deepEqual(again.finals, []);
		assert.equal(again.nextFinal, 1);
	});

	it("keeps the interim words of a sentence still being spoken", () => {
		const list = results([{ transcript: "show me the" }]);
		const read = readResults(list, 0, 0);
		assert.equal(read.interim, "show me the");
		assert.deepEqual(read.finals, []);
	});

	it("takes a final that arrives after an interim", () => {
		const list = results([
			{ transcript: "show me the" },
			{ transcript: "invoice", isFinal: true },
		]);
		const read = readResults(list, 0, 0);
		// "show me the" was interim; once "invoice" is final, it is cleared.
		assert.equal(read.interim, "");
		assert.deepEqual(read.finals, ["invoice"]);
		assert.equal(read.nextFinal, 2);
	});

	it("skips what was already final when the list is reported again", () => {
		const list = results([
			{ transcript: "first", isFinal: true },
			{ transcript: "second" },
			{ transcript: "third", isFinal: true },
		]);
		// One event reported the first final; the next reports all three.
		const after = readResults(list, 0, 1);
		assert.deepEqual(after.finals, ["third"]);
		assert.equal(after.interim, "");
		assert.equal(after.nextFinal, 3);
	});

	it("survives a results object with no rows", () => {
		const read = readResults({ length: 0 }, 0, 0);
		assert.deepEqual(read.finals, []);
		assert.equal(read.interim, "");
	});
});

describe("mergeTranscript", () => {
	it("shows the spoken words", () => {
		assert.equal(
			mergeTranscript({ spoken: "show me the invoice", current: "", lastEmitted: "" }),
			"show me the invoice",
		);
	});

	it("keeps what the reader typed while the microphone was open", () => {
		const text = mergeTranscript({
			spoken: "who is late this month",
			current: "show me the invoices urgent",
			lastEmitted: "show me the invoices",
		});
		assert.equal(text, "who is late this month urgent");

		// Punctuation the reader typed is punctuation they wanted.
		assert.equal(
			mergeTranscript({
				spoken: "who is late",
				current: "show me the invoices, urgent",
				lastEmitted: "show me the invoices",
			}),
			"who is late , urgent",
		);
	});

	it("leaves typed text alone when nothing was spoken", () => {
		assert.equal(
			mergeTranscript({ spoken: "", current: "typed by hand", lastEmitted: "" }),
			"typed by hand",
		);
	});

	it("returns nothing when nothing was said and nothing is there", () => {
		assert.equal(mergeTranscript({ spoken: "", current: "", lastEmitted: "" }), "");
	});

	it("does not treat unrelated text as an addition", () => {
		// The reader rewrote the whole box while speaking; their text wins
		// over an anchor it no longer starts with.
		assert.equal(
			mergeTranscript({ spoken: "spoken", current: "something else", lastEmitted: "anchor" }),
			"spoken",
		);
	});

	it("keeps text typed after the last result event", () => {
		// The shape the composer's `onend` uses.  A session ends three
		// ways — the two-minute limit, a deliberate stop, the browser
		// giving up — and "dictate, correct, click stop" is the ordinary
		// one.  The correction arrives after the last `onresult`, so
		// reusing what that event emitted would drop it, and the merge has
		// to be run again against the box as it stands now.
		const spoken = "hello";
		const lastEmitted = "hello";
		const current = "hello world";

		assert.equal(
			mergeTranscript({ spoken, current, lastEmitted }),
			"hello world",
		);
	});
});

describe("voiceErrorText", () => {
	it("names the permission that was refused", () => {
		assert.match(
			voiceErrorText("not-allowed", (t) => t),
			/Microphone/,
		);
	});

	it("says nothing for a deliberate stop", () => {
		assert.equal(
			voiceErrorText("aborted", (t) => t),
			"",
		);
	});

	it("has a sentence for every browser code it knows", () => {
		for (const code of [
			"service-not-allowed",
			"no-speech",
			"audio-capture",
			"network",
			"language-not-supported",
		]) {
			assert.ok(voiceErrorText(code, (t) => t).length > 0, code);
		}
	});

	it("falls back to a plain sentence for an unknown code", () => {
		assert.ok(voiceErrorText("something-new", (t) => t).length > 0);
	});

	it("translates through the callback it is given", () => {
		assert.equal(
			voiceErrorText("network", (t) => `[${t}]`),
			"[Voice input needs a network connection.]",
		);
	});
});

describe("MAX_SESSION_MS", () => {
	it("is a life of a session, not a lifetime of a microphone", () => {
		assert.ok(MAX_SESSION_MS > 10000 && MAX_SESSION_MS <= 600000);
	});
});
