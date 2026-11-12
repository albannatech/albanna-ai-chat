// Watching the page the reader is on.
//
// `context.mjs` describes the page; this module *watches* it.
//
// The Desk is a single-page application, so a navigation does not reload
// the page — it changes the route, and the router says so. The event it
// says so with is **"change"**, and it is the only one: the Desk's own
// code listens for "change" in six places — `desk.js`, `router_history.js`,
// `filter_list.js`, `link_preview.js`, `group_by.js` and `form_tour.js`.
//
// There is no "route-change" event. A listener for one is a listener for
// something that never happens, and the widget listened for one: the page
// it thought it was on was frozen at the page it had been *opened* on, so
// the assistant was asked about the wrong page, the answer was filed under
// the wrong page, and the transcript showed the wrong conversation.
//
// So the name lives here, on its own, where a test can hold it to account.

/** The event the Desk's router fires when the page changes. */
export const ROUTE_EVENT = "change";

/**
 * Watch the Desk's route.
 *
 * @param {function} onChange called when the page changes
 * @param {{window?: object}} [env] the browser, for the tests
 * @returns {function} unwatch
 */
export function watchRoute(onChange, env) {
  const win = env && typeof env === "object" ? env.window : window;
  const router = win && win.frappe ? win.frappe.router : null;
  if (!router || typeof router.on !== "function") return () => {};

  const handler = () => onChange();
  router.on(ROUTE_EVENT, handler);

  return () => {
    if (typeof router.off === "function") {
      router.off(ROUTE_EVENT, handler);
    }
  };
}
