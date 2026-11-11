// The launcher's pure geometry.
//
// The launcher bundle (`albanna-side-chat.bundle.js`) is a browser script,
// and its pure logic — width clamping, restoring a width from storage,
// which side the panel sits on, which physical edge the resize handle
// faces — used to live inside it, untested.  `SideChatApp.vue` states the
// app's own rule: "The pure, tested logic is deliberately out of this
// file; what stays here is state, wiring and DOM."  The launcher broke
// that rule, so the logic lives here, where it runs under plain node like
// its neighbours.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/** The localStorage key the panel's width is persisted under. */
export const WIDTH_KEY = "albanna.side-chat.width";

/** The narrowest the panel may be dragged. */
export const MIN_WIDTH = 320;

/** The widest the panel may be dragged. */
export const MAX_WIDTH = 720;

/** How far one arrow-key press moves the resize handle. */
export const KEYBOARD_STEP = 24;

/** The width used when nothing valid is stored. */
export const DEFAULT_WIDTH = 400;

/**
 * Clamp a width to the allowed range and round it.
 *
 * @param {number} width the requested width
 * @returns {number} the clamped, rounded width
 */
export function clampWidth(width) {
	return Math.round(Math.min(Math.max(width, MIN_WIDTH), MAX_WIDTH));
}

/**
 * Read a persisted width from a storage object.
 *
 * Returns the default when the stored value is missing, unparseable or out
 * of range — and, crucially, when the read itself throws.  A browser that
 * will not remember the width is a browser that will not lose it either,
 * but only if the read does not escape and take the widget down with it:
 * this runs from boot() with no try/catch around it.
 *
 * @param {object} storage anything with a getItem(key) method
 * @returns {number} the restored width, or the default
 */
export function readStoredWidth(storage) {
	let stored;
	try {
		stored = Number.parseInt((storage && storage.getItem(WIDTH_KEY)) || "", 10);
	} catch (error) {
		return DEFAULT_WIDTH;
	}
	return Number.isFinite(stored) && stored >= MIN_WIDTH && stored <= MAX_WIDTH
		? stored
		: DEFAULT_WIDTH;
}

/**
 * The logical side the panel sits on, from its configured position.
 *
 * "bottom-left" is the inline start; everything else is the inline end.
 *
 * @param {string} position the configured position
 * @returns {"inline-start" | "inline-end"} the side
 */
export function sideFor(position) {
	return position === "bottom-left" ? "inline-start" : "inline-end";
}

/**
 * Which physical edge the panel is pinned to.
 *
 * The panel is pinned to one edge of the screen and the handle is on the
 * other one.  Which physical edge that is depends on the direction as well
 * as on the side, so it is worked out here rather than read from the DOM.
 *
 * @param {"inline-start" | "inline-end"} side the logical side
 * @param {boolean} isRtl whether the document is right-to-left
 * @returns {boolean} true when the panel is pinned to the right edge
 */
export function pinnedRight(side, isRtl) {
	return side === "inline-end" ? !isRtl : isRtl;
}
