// The renders a streaming answer asks for, coalesced.
//
// Ported from `albanna`'s side-chat without a change: the problem it solves
// is not this app's contract, it is arithmetic. A token event used to append
// a character and then re-render the whole answer: the full markdown parse,
// again, per token. A thousand-token answer was therefore parsed a thousand
// times, and the cost of the last parse was paid a thousand times over by
// the parses before it.
//
// The fix is not a faster renderer — it is asking for *renders*, not tokens:
// every token mutates the message's content synchronously, and a single
// render is scheduled at the end of the frame batch. The render reads
// whatever the content is *then*, so the last token wins, and the reader
// sees the answer grow in steps the eye cannot split from the token stream.
//
// Pure scheduling logic: the caller supplies the scheduler, so the test
// runs under plain node and the component runs it on `setTimeout`.
// (Deliberately not `requestAnimationFrame`: a scheduler bounded by the
// display's refresh rate still re-renders every frame's worth of cost on a
// long answer, and the eye does not need 60 markdown parses a second.)

/** How often, at most, a streaming answer renders, in milliseconds. */
export const RENDER_EVERY_MS = 66;

/**
 * Make a coalescing queue for renders of one growing message.
 *
 * @param {function} render called at most once per batch, with the message
 *   the latest request asked for — whose content is read at flush time, so
 *   the last token wins without a render per token
 * @param {function} schedule the scheduler: `(fn, delayMs) => any`.
 *   Receiving it as a parameter keeps the timing out of the logic.
 * @param {number} [everyMs] the gap between renders
 * @returns {(message: object) => void} hand every token to this
 */
export function createRenderThrottle(render, schedule, everyMs = RENDER_EVERY_MS) {
  /** Whether a render is already scheduled. */
  let queued = false;
  /** The message the last request asked to render. */
  let latest = null;

  return function requestRender(message) {
    if (message) latest = message;
    if (queued) return;
    queued = true;

    schedule(() => {
      // Read only at flush time: the content the message carries *now* is
      // what the previous tokens made it, so no token was lost and no
      // render was wasted.
      queued = false;
      if (latest) {
        render(latest);
        latest = null;
      }
    }, everyMs);
  };
}

/**
 * The scheduler the panel should use.
 *
 * A plain `setTimeout` wrapper, kept as its own export so that both the
 * tests' fake clock and the component's real one agree on it.
 *
 * @param {function} fn the render
 * @param {number} ms the gap
 * @returns {any} the timer's id, whatever the host returns
 */
export function scheduleRender(fn, ms) {
  return setTimeout(fn, ms);
}
