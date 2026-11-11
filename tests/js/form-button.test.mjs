/**
 * Tests for the form-button adapter — the Layer B half of the access contract.
 *
 * What these verify is the failure `access.mjs` exists to prevent, seen from
 * the Desk's side: a reader who may not chat being given a button that opens
 * nothing. That happens when the launcher's answer and the button's
 * assumption are two different answers.
 *
 * This is the one module in `lib/` that touches the Desk — it reads
 * `cur_frm` and calls `add_custom_button` — so it is also the proof that the
 * split holds: everything it *decides* comes from `access.mjs`, which is pure
 * and tested separately.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
	BUTTON_LABEL,
	mountFormButton,
	watchAccess,
} from "../../albanna_ai_chat/public/js/lib/form-button.mjs";
import {
	chatAllowed,
	publishAccess,
} from "../../albanna_ai_chat/public/js/lib/access.mjs";

/** A document that dispatches events to the listeners registered on it. */
function fakeDocument() {
	const listeners = new Map();
	return {
		addEventListener(type, handler) {
			if (!listeners.has(type)) listeners.set(type, []);
			listeners.get(type).push(handler);
		},
		removeEventListener(type, handler) {
			const list = listeners.get(type) || [];
			const index = list.indexOf(handler);
			if (index >= 0) list.splice(index, 1);
		},
		dispatchEvent(event) {
			for (const handler of listeners.get(event.type) || []) handler(event);
		},
	};
}

/** A form that records the custom buttons put on its toolbar. */
function fakeForm() {
	const buttons = [];
	return {
		buttons,
		custom_buttons: {},
		add_custom_button(label, handler) {
			buttons.push({ label, handler });
			this.custom_buttons[label] = handler;
		},
	};
}

/** A page with a form on it, and no access decision published yet. */
function fakePage({ form = null, decision = null } = {}) {
	const win = { cur_frm: form, dispatchEvent() {} };
	const doc = fakeDocument();
	const env = { window: win, document: doc };
	if (decision) publishAccess(decision, env);
	return { win, doc, env };
}

describe("the form button", () => {
	it("is not offered to a reader who may not chat", () => {
		const form = fakeForm();
		const { env } = fakePage({ form, decision: { visible: false, chat_access: false } });

		assert.equal(mountFormButton(env), false);
		assert.equal(form.buttons.length, 0);
	});

	it("is offered to a reader who may chat", () => {
		const form = fakeForm();
		const { env } = fakePage({ form, decision: { visible: true, chat_access: true } });

		assert.equal(mountFormButton(env), true);
		assert.equal(form.buttons.length, 1);
		assert.equal(form.buttons[0].label, BUTTON_LABEL);
	});

	it("is not offered before the launcher has answered", () => {
		// "Not yet" and "no" are the same answer for a button: either way
		// there is nothing to offer, and a button that appears and then
		// disappears is worse than one that never appears.
		const form = fakeForm();
		const { env } = fakePage({ form });

		assert.equal(mountFormButton(env), false);
		assert.equal(form.buttons.length, 0);
	});

	it("arrives when the answer comes after the form was drawn", () => {
		const form = fakeForm();
		const { env } = fakePage({ form });

		watchAccess(env);
		assert.equal(form.buttons.length, 0, "no button before the answer");

		publishAccess({ visible: true, chat_access: true }, env);
		assert.equal(form.buttons.length, 1, "the button arrives with the answer");
	});

	it("never arrives when no answer comes", () => {
		const form = fakeForm();
		const { env } = fakePage({ form });

		watchAccess(env);
		assert.equal(form.buttons.length, 0);
	});

	it("is not added twice when the form redraws", () => {
		const form = fakeForm();
		const { env } = fakePage({ form, decision: { visible: true, chat_access: true } });

		mountFormButton(env);
		mountFormButton(env);
		assert.equal(form.buttons.length, 1, "a redraw must not grow a second button");
	});

	it("does nothing when there is no form on the page", () => {
		const { env } = fakePage({ decision: { visible: true, chat_access: true } });
		assert.equal(mountFormButton(env), false);
	});

	it("agrees with the access module about who may chat", () => {
		// The adapter and the pure contract must not drift: a button offered
		// to a reader `chatAllowed` refuses is the original bug.
		const form = fakeForm();
		const { env } = fakePage({ form, decision: { visible: true, chat_access: true } });

		assert.equal(mountFormButton(env), chatAllowed(env));
	});
});
