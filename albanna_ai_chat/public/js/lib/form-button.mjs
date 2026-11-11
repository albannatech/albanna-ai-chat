// The "Ask Albanna" button on a form — a Layer B adapter.
//
// This is the first module in the port that is *not* pure, and it is here
// rather than skipped because `access.test.mjs` proves the access contract
// end to end through it. Without it the test would assert the contract
// against nothing, which is a test that passes and proves nothing.
//
// What makes it Layer B: it reads `frappe.cur_frm` and calls
// `add_custom_button`, both of which are Desk's, not ours. Everything it
// *decides* comes from `access.mjs`, which is pure. That split is the whole
// port strategy — the decision is portable, the adapter is rewritten.
//
// Ported from `albanna`'s form-button bundle, with the access contract
// pointed at this app's namespaced global and event.

import { chatAllowed, onAccessDecision } from "./access.mjs";

/** What the button is called, in the reader's language. */
export const BUTTON_LABEL = "Ask Albanna";

/**
 * Put the button on the form, when the reader may chat.
 *
 * Called once per form draw. It is safe to call twice: the button is only
 * added when it is not already there, because a form that redraws should
 * not grow a second button.
 *
 * @param {object} env the page: `{window, document}`
 * @returns {boolean} true when a button was added
 */
export function mountFormButton(env) {
	const win = env && env.window;
	const form = win && win.cur_frm;
	if (!form || typeof form.add_custom_button !== "function") return false;
	if (!chatAllowed(env)) return false;
	if (form.custom_buttons && form.custom_buttons[BUTTON_LABEL]) return false;

	form.add_custom_button(BUTTON_LABEL, () => {
		// The launcher owns opening the panel. This button's whole job is
		// to exist for a reader who may chat, and to not exist for one who
		// may not — a button that opened nothing was the original bug.
		win.dispatchEvent(new CustomEvent("albanna-ai-chat:open"));
	});
	return true;
}

/**
 * Watch for the access decision, and put the button on when it arrives.
 *
 * The answer may come after the form has already been drawn — the launcher
 * asks the server asynchronously — so a reader who may chat must not be the
 * one left without a button.
 *
 * @param {object} env the page: `{window, document}`
 * @returns {function(): void} a function that stops watching
 */
export function watchAccess(env) {
	mountFormButton(env);
	return onAccessDecision(() => mountFormButton(env), env);
}
