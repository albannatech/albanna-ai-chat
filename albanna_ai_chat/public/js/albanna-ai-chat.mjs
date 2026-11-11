/**
 * The Desk entry point — the launcher.
 *
 * Stage 4a establishes the build pipeline, so this file is deliberately
 * small: it proves the bundle builds, hashes and registers. Stage 4b ports
 * the real widget behind it.
 *
 * The shape it will grow into is the one `albanna` documented at length in
 * its own hooks: a framework-free launcher that asks the server whether the
 * widget should render, places a button and an empty panel on the page, and
 * fetches the real bundle on the first click. A global hook is paid on every
 * Desk page load, so the framework itself must not be in it.
 *
 * Note what is *not* here: no `frappe` import, no socket, no tool names.
 * Those are the contract-bound adapters, and they are rewritten against this
 * core's own contract rather than copied from `albanna`'s.
 */

export const APP_NAME = "albanna_ai_chat";

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
      detail: { app: APP_NAME, version: VERSION },
    }),
  );
}
