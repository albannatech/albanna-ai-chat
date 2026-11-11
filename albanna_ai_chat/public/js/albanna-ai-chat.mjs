/**
 * The Desk entry point — the launcher.
 *
 * Stage 4a established the build pipeline. Stage 4b ports the pure layer
 * behind it: the formatting, the refusal unwrapping, the render coalescing
 * and the turn state machine now live in `lib/`, are tested under plain
 * node, and are imported here so the bundle actually contains them.
 *
 * Stage 4c adds the two remaining pure modules: the access decision the
 * launcher and the form button must share, and the attachment rules checked
 * before the bytes leave the browser.
 *
 * Stage 4d adds the transport — the socket fast path with the poll as the
 * delivery guarantee. Its poll ramp is pure and tested under plain node; its
 * two `window.frappe` calls are the only contract-bound parts, and they read
 * their event name and endpoints from `lib/wire.mjs` rather than spelling them
 * out.
 *
 * The shape is the one `albanna` documented at length in its own hooks: a
 * framework-free launcher that asks the server whether the widget should
 * render, places a button and an empty panel on the page, and fetches the
 * real bundle on the first click. A global hook is paid on every Desk page
 * load, so the framework itself must not be in it.
 *
 * Note what is *not* here: no `frappe` import, no socket connection, no tool
 * names. Those are the contract-bound adapters, and they are rewritten against
 * this core's own contract rather than copied from `albanna`'s — see
 * `lib/wire.mjs`, which is the one place the frontend's assumptions about the
 * server live.
 *
 * Still to come: the panel itself, and the server endpoints in `lib/wire.mjs`
 * that the transport calls.
 */

import {
  ACCESS_EVENT,
  ACCESS_GLOBAL,
  chatAllowed,
  onAccessDecision,
  publishAccess,
} from "./lib/access.mjs";
import {
  REFUSED_SIZE,
  REFUSED_TYPE,
  checkAttachment,
  makeAttachment,
  storeAll,
  turnAttachments,
} from "./lib/attachments.mjs";
import { APP_NAME, STREAM_EVENT } from "./lib/wire.mjs";
import { STATES, initialState } from "./lib/turn-state.mjs";
import {
  FIRST_POLL_MS,
  STATUS_POLL_MAX_MS,
  call,
  nextPollDelay,
  runTurn,
  subscribe,
  waitForTurn,
} from "./lib/transport.mjs";

export {
  APP_NAME,
  STREAM_EVENT,
  STATES,
  initialState,
  ACCESS_EVENT,
  ACCESS_GLOBAL,
  chatAllowed,
  onAccessDecision,
  publishAccess,
  REFUSED_SIZE,
  REFUSED_TYPE,
  checkAttachment,
  makeAttachment,
  storeAll,
  turnAttachments,
  FIRST_POLL_MS,
  STATUS_POLL_MAX_MS,
  call,
  nextPollDelay,
  runTurn,
  subscribe,
  waitForTurn,
};

export const VERSION = "0.1.0";

/**
 * Whether the widget should render for this page.
 *
 * A stub for now — it answers yes so the pipeline can be exercised end to
 * end. The real answer comes from the server, because only the server knows
 * the reader's roles, and a reader who may not chat gets no widget at all.
 */
export function shouldRender() {
  return true;
}

if (typeof document !== "undefined" && shouldRender()) {
  document.dispatchEvent(
    new CustomEvent("albanna-ai-chat:ready", {
      detail: { app: APP_NAME, version: VERSION, phases: STATES },
    }),
  );
}
