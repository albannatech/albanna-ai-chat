// The panel's mount — the half the launcher talks to.
//
// The panel is fetched on the first click, injected as a classic `<script>`,
// and a classic script cannot hand the launcher a module's exports. So this
// file registers the mount function on a global — `lib/wire.mjs` names it —
// and the launcher calls `window[ALBANNA_PANEL_GLOBAL].mount(el, options)`.
// That is `albanna`'s own pattern, ported with its reasoning.
//
// The bundle is built as an IIFE rather than ESM for the same reason: an ESM
// script injected without `type="module"` does not execute at all, and a
// module script cannot be given a URL the launcher resolved a moment earlier
// without a round of indirection nobody needs.
//
// Mounting twice replaces the component rather than stacking a second one. A
// launcher that mounted twice would be a launcher with two panels on one
// page, and only one of them would be wired to the button.

import { createApp } from "vue";
import SideChat from "./SideChat.vue";

let app = null;

window.albannaAiChatPanel = {
  /**
   * Mount the panel into *el*, which the launcher has already placed and
   * opened.
   *
   * @param {HTMLElement} el the root element
   * @param {{onReady?: function}} [options]
   */
  mount(el, options = {}) {
    if (app) {
      app.unmount();
      app = null;
    }
    el.setAttribute("data-open", "true");
    app = createApp(SideChat);
    app.mount(el);
    if (typeof options.onReady === "function") options.onReady();
  },

  /** Take the panel down — the launcher calls this when the root is removed. */
  unmount() {
    if (app) {
      app.unmount();
      app = null;
    }
  },
};
