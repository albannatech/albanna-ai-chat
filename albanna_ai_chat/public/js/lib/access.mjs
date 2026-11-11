// The chat access decision, shared by the global bundles.
//
// Ported from `albanna`'s `access.mjs`, and the *reason* it exists is ported
// with it. The launcher asks the server whether the widget should exist at
// all, and the answer arrives asynchronously. The other global bundle — the
// "Ask Albanna" button on a form — needs the same answer before it puts a
// button on the screen.
//
// The two bundles used to answer the question separately: the launcher
// decided, and the button assumed. A user who may not chat was therefore
// given a button that did nothing when it was clicked — the launcher had not
// mounted, so there was nothing for the button to open.
//
// The answer is published once, and the button waits for it:
//
//   * `publishAccess` records the decision and announces it. It is called
//     with whatever the server said, *including* when the answer is "no" — a
//     silent failure would leave the button waiting for an answer that never
//     comes, which is the same dead button again.
//   * `chatAllowed` is the question the button asks, and it answers "no"
//     until the decision has been published. "Not yet" and "no" are the same
//     answer for a button: either way there is nothing to offer.
//   * `onAccessDecision` is how the button hears the answer when it arrives
//     after the form has already been drawn.
//
// The environment is passed in rather than read from the global scope, so the
// rule can be tested under plain node, with a window that is a fake. That is
// the whole reason this file is not part of the launcher bundle.
//
// What is *not* ported: the global and event names. `albanna` published on
// `albannaChatAccess` and fired `albanna:access`; this core publishes on its
// own, because two apps on one Desk sharing a global is two apps overwriting
// each other's access decision.

/** The global the launcher's answer is published on. */
export const ACCESS_GLOBAL = "albannaAiChatAccess";

/** The event the launcher fires when it publishes the answer. */
export const ACCESS_EVENT = "albanna-ai-chat:access";

/**
 * Publish the launcher's answer, and announce it.
 *
 * Called with whatever the server said, including "no". A silent failure
 * leaves the button waiting for an answer that never comes.
 *
 * @param {object|null} detail what the server said about the widget
 * @param {{window: object, document: object}} env the page
 * @returns {{visible: boolean, chat_access: boolean}} the decision
 */
export function publishAccess(detail, env) {
  const decision = {
    visible: !!(detail && detail.visible === true),
    chat_access: !!(detail && detail.chat_access === true),
  };

  env.window[ACCESS_GLOBAL] = decision;

  const doc = env.document;
  if (doc && typeof doc.dispatchEvent === "function" && typeof CustomEvent === "function") {
    doc.dispatchEvent(new CustomEvent(ACCESS_EVENT, { detail: decision }));
  }

  return decision;
}

/**
 * Whether the chat may be offered to the reader.
 *
 * "No" until the launcher has answered: an unanswered question is not a yes,
 * and a button that appears before the answer and disappears after it is
 * worse than one that never appears.
 *
 * @param {{window: object, document: object}} env the page
 * @returns {boolean} true when the widget exists for this reader
 */
export function chatAllowed(env) {
  const decision = env.window[ACCESS_GLOBAL];
  return !!(decision && decision.visible === true);
}

/**
 * Run *handler* when the launcher publishes its answer.
 *
 * The handler is called with the decision, so a bundle that missed the answer
 * can still act on it.
 *
 * @param {function(object): void} handler what to do with the decision
 * @param {{window: object, document: object}} env the page
 * @returns {function(): void} a function that stops listening
 */
export function onAccessDecision(handler, env) {
  const doc = env.document;
  if (!doc || typeof doc.addEventListener !== "function") return () => {};

  const listener = (event) => {
    handler((event && event.detail) || null);
  };
  doc.addEventListener(ACCESS_EVENT, listener);

  return () => {
    if (typeof doc.removeEventListener === "function") {
      doc.removeEventListener(ACCESS_EVENT, listener);
    }
  };
}
