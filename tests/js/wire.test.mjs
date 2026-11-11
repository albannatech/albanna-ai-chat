/**
 * Tests for the wire contract — the one place the frontend's assumptions live.
 *
 * `wire.mjs` is the Layer B of the port: everything the widget assumes about
 * the server, named once. These tests assert the invariants that make it safe
 * to centralise — if the names drift, the panel silently does nothing, and
 * nothing on the screen says so.
 *
 * The cross-language half (that PHASES matches the server's `TurnState`, and
 * ROLES matches `AI Chat Message.role`) is asserted from Python in
 * `tests/test_wire_contract.py`, because only Python can read both sides.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
	APP_NAME,
	ENVELOPE_STATUS,
	ENDPOINTS,
	INFLIGHT_KEY,
	PHASES,
	PROGRESS,
	ROLES,
	STREAM_EVENT,
	TURN_DONE_EVENT,
	readEnvelope,
} from "../../albanna_ai_chat/public/js/lib/wire.mjs";

describe("the wire contract", () => {
	it("names the app as Frappe knows it", () => {
		assert.equal(APP_NAME, "albanna_ai_chat");
	});

	it("namespaces its socket events to this app", () => {
		// A bench serves several apps from one origin, and socket.io events
		// are a shared channel: an app publishing on another app's event name
		// is an app whose progress another panel renders.
		assert.ok(STREAM_EVENT.startsWith("albanna_ai_chat"));
		assert.ok(TURN_DONE_EVENT.startsWith("albanna_ai_chat"));
		assert.notEqual(STREAM_EVENT, TURN_DONE_EVENT);
	});

	it("namespaces its storage key to this app", () => {
		assert.ok(INFLIGHT_KEY.startsWith("albanna_ai_chat"));
	});

	it("serves every endpoint from this app", () => {
		for (const [name, path] of Object.entries(ENDPOINTS)) {
			assert.ok(
				path.startsWith(`${APP_NAME}.`),
				`endpoint ${name} (${path}) is not served by ${APP_NAME}`,
			);
		}
	});

	it("declares the endpoints the transport needs", () => {
		for (const name of [
			"startTurn",
			"getTurn",
			"stopTurn",
			"answerQuestion",
			"resolveApproval",
			"conversations",
			"access",
		]) {
			assert.ok(ENDPOINTS[name], `missing endpoint: ${name}`);
		}
	});

	it("reads an ok envelope", () => {
		const envelope = readEnvelope({ status: "ok", message: "done", data: { a: 1 } });
		assert.equal(envelope.status, "ok");
		assert.equal(envelope.message, "done");
		assert.deepEqual(envelope.data, { a: 1 });
		assert.deepEqual(envelope.hints, []);
	});

	it("reads an error envelope", () => {
		const envelope = readEnvelope({ status: "error", message: "refused", hints: ["ask an admin"] });
		assert.equal(envelope.status, "error");
		assert.deepEqual(envelope.hints, ["ask an admin"]);
	});

	it("treats a traceback as an error even when status is absent", () => {
		// Frappe's own error shape carries `exc` and no `status`.
		const envelope = readEnvelope({ exc: "ValidationError: nope" });
		assert.equal(envelope.status, ENVELOPE_STATUS.ERROR);
	});

	it("defaults to ok when nothing says otherwise", () => {
		assert.equal(readEnvelope({}).status, ENVELOPE_STATUS.OK);
		assert.equal(readEnvelope(null).status, ENVELOPE_STATUS.OK);
	});

	it("keeps the payload when there is no data key", () => {
		const envelope = readEnvelope({ status: "ok", thing: 1 });
		assert.deepEqual(envelope.data, { status: "ok", thing: 1 });
	});

	it("coerces hints to strings", () => {
		const envelope = readEnvelope({ status: "error", hints: [1, 2] });
		assert.deepEqual(envelope.hints, ["1", "2"]);
	});

	it("declares the roles the server's doctype declares", () => {
		assert.deepEqual(ROLES, ["system", "user", "assistant", "tool"]);
	});

	it("declares the phases the server's doctype declares", () => {
		assert.deepEqual(PHASES, [
			"idle",
			"running",
			"awaiting_tool",
			"awaiting_approval",
			"awaiting_answer",
			"done",
			"failed",
			"stopped",
		]);
	});

	it("declares the progress events the server publishes", () => {
		for (const name of ["TEXT", "TOOL_START", "TOOL_END", "PHASE", "DONE", "ERROR"]) {
			assert.ok(PROGRESS[name], `missing progress event: ${name}`);
		}
	});
});
