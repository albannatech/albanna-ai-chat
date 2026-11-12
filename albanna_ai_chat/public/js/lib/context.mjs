// What the widget knows about the page the user is looking at.
//
// The Desk is a single-page application, so the page is not a URL — it is
// the current form, the current route, and whatever the user has selected.
// A poll that reads `cur_frm` is wrong twice over: it cannot see a list or
// a report, and `cur_frm` outlives the document it points at.
//
// So the route is the authority — it is the Desk's own statement of what
// is on the screen — and the open document is consulted only for the
// details the route does not carry, and only when it is the document the
// route names. The route's shape is unchanged: a form is
// "form|<doctype>|<name>" and everything else is the route itself, so a
// conversation scoped by one page is still found after the change.
//
// Everything here is a *description*. The server re-reads whatever it
// needs and treats the description as untrusted, so a wrong answer here
// costs a slightly less relevant question, never a wrong document.
//
// The selection is captured passively. The user selected something, and
// that selection is the strongest signal available about what they are
// about to ask.
//
// Pure half: the normalisers — the route classifier, the filter and
// column describers, the renderers, the page identity. They take values,
// not globals, and are tested under plain node. The three readers that
// touch the browser (`currentRoute`, `resolveContext`, `currentSelection`)
// take an injected `env` — the same seam `access.mjs` uses — so the tests
// drive them without a Desk.

/** The longest selection that is sent. */
export const MAX_SELECTION = 500;

/** How many filters of a list or a report are carried with a turn. */
export const MAX_LIST_FILTERS = 20;

/** How many columns of a list are carried with a turn. */
export const MAX_LIST_COLUMNS = 30;

/** How long the rendered filters may be. */
const MAX_FILTER_TEXT = 300;

/** How long the rendered columns may be. */
const MAX_COLUMN_TEXT = 300;

/**
 * The current route, as a string.
 *
 * `frappe.get_route()` returns an array in Frappe v16 (`["Form", "Sales
 * Invoice", "SINV-0001"]`) and a string in some builds. Left as an array
 * it stringifies with commas wherever it is joined, which makes a page
 * identity that looks like a typo.
 *
 * @param {{window?: object}} [env] the browser, for the tests
 * @returns {string} the route
 */
export function currentRoute(env) {
  const win = envEnv(env);
  const frappe = win.frappe;
  const route =
    frappe && typeof frappe.get_route === "function" ? frappe.get_route() : "";
  if (Array.isArray(route)) return route.filter(Boolean).join("/");
  return String(route || "");
}

/**
 * The identity of a page — the string a conversation is scoped by.
 *
 * It is computed from the *kind* of page, not from the whole description.
 * The description grows — it carries the filters of a list, the rows it
 * shows, the questions the reader has asked — and a conversation scoped by
 * a growing description would be re-scoped every time the description
 * grows, and the reader would lose their thread.
 *
 * So the shape is fixed: a form is `form|<doctype>|<name>` and every
 * other page is its route. The conversations already on a site were
 * scoped by these strings, and they are still found.
 *
 * @param {object} [context] the description, read from the page if absent
 * @param {{window?: object}} [env] the browser, for the tests
 * @returns {string} the identity
 */
export function pageIdentity(context, env) {
  const page = context || resolveContext(env);
  if (page.view === "form") {
    return ["form", page.doctype, page.name].filter(Boolean).join("|");
  }
  return page.view;
}

/**
 * Describe the current page.
 *
 * @param {{window?: object, document?: object}} [env] the browser, for
 *   the tests
 * @returns {{view: string, route: string, doctype: string, name: string,
 *   title: string, filters: string, rows: number, columns: string,
 *   sort: string, report: string, selection: string}} the description
 */
export function resolveContext(env) {
  const win = envEnv(env);
  const route = currentRoute(env);
  const parts = route ? route.split("/") : [];

  // The route is the Desk's own statement of what is on the screen, and
  // it is the only statement that is always true.
  //
  // `cur_frm` is not. The Desk sets it when a form opens and never
  // clears it when the reader walks away from that form — only a *page*
  // view clears it — so on the list they walked to, it still points at
  // the form they walked away from. A widget that trusts it answers
  // about a page the reader has already left, and looks perfectly
  // correct while doing it.
  //
  // So the route decides, and the open document only supplies the
  // details the route does not carry.
  const onForm = parts[0] === "Form";

  const frm = win.cur_frm;
  let view = route;
  let doctype = "";
  let name = "";
  let title = "";
  let filters = "";
  let rows = 0;
  let columns = "";
  let sort = "";
  let report = "";

  if (onForm) {
    // A form: the document is the page.
    view = "form";
    doctype = parts[1] || "";
    name = parts[2] || "";

    // The open document has what the route does not: its title, and
    // its real name when it is a document that was only just saved.
    // It is used only when it is the document the route names — a
    // stale form must not describe the page.
    if (frm && frm.doctype && frm.doc && frm.doctype === doctype) {
      title = documentTitle(frm.doc);
      if (frm.doc.name) name = frm.doc.name;
    }
  } else if (classifyRoute(route) === "list") {
    // A list: the page is the list the reader is looking at, and the
    // route says only which list — not the filters on it, and not how
    // many rows it shows. So the list view is read for those, and
    // only because the route agrees that this *is* a list.
    //
    // `cur_list` is stale in the same way `cur_frm` is: the Desk
    // clears it when the doctype changes, and not otherwise, so on the
    // form the reader walked to it still holds the list they walked
    // away from.
    const list = win.cur_list;
    if (list) {
      doctype = String(list.doctype || "");
      filters = renderListFilters(describeListFilters(listFilters(list)));
      rows = Number(list.total_count) || 0;
      columns = renderListColumns(describeListColumns(list.columns));
      sort = describeSort(list.sort_by, list.sort_order);
    }
  } else if (classifyRoute(route) === "report") {
    // A report: the reader is looking at a query, and the filters on
    // it are the question they are asking. The live report is stale
    // in the same way the list is — the Desk builds it and does not
    // clear it — so the route decides that this *is* a report.
    const live = win.frappe && win.frappe.query_report;
    if (live) {
      report = String(live.report_name || "");
      filters = renderListFilters(describeReportFilters(live.filters));
    }
  }
  // A report, a workspace, a dashboard: the route is the page.
  // The route carries the module and the view ("erpnext/sales-order"),
  // which is enough to scope a conversation and to tell the model where
  // the user is.
  return {
    view,
    route,
    doctype,
    name,
    title,
    filters,
    rows,
    columns,
    sort,
    report,
    selection: currentSelection(env),
  };
}

/**
 * The kind of page the reader is on, from the route alone.
 *
 * The route is the Desk's own statement of what is on the screen, and
 * the live objects are not: the Desk sets `cur_frm` and `cur_list` when a
 * view opens and does not always clear them when the reader walks away.
 *
 * So the route decides *which* live object may be read, and the live
 * object only supplies the details. A widget that reads them
 * unconditionally is a widget that describes the page the reader has
 * just left.
 *
 * @param {string} route the route, as "Form/Sales Invoice/SINV-0001"
 * @returns {string} "form", "list", "report" or "other"
 */
export function classifyRoute(route) {
  const parts = String(route || "").split("/");
  const head = (parts[0] || "").toLowerCase();
  if (head === "form") return "form";
  if (head === "query-report") return "report";
  // A list is "List/<doctype>/List" and a report on a doctype is
  // "List/<doctype>/Report". The other shapes under "List" — a kanban,
  // a calendar, a tree — are neither, and their filters are not the
  // list's filters.
  if (head === "list") {
    const sub = (parts[2] || "").toLowerCase();
    if (sub === "list") return "list";
    if (sub === "report") return "report";
  }
  return "other";
}

/**
 * Normalise a list view's filters into `{field, op, value}` rows.
 *
 * The Desk's `get_filters_for_args()` answers with
 * `[doctype, fieldname, operator, value]` quadruples. A filter with no
 * field is dropped: it is a row of the filter area that says nothing.
 *
 * @param {Array} raw the quadruples, as the list view gives them
 * @returns {Array<{field: string, op: string, value: string}>} the rows
 */
export function describeListFilters(raw) {
  if (!Array.isArray(raw)) return [];
  const rows = [];
  for (const entry of raw) {
    if (!Array.isArray(entry)) continue;
    const field = oneLine(entry[1]);
    if (!field) continue;
    rows.push({ field, op: oneLine(entry[2]) || "=", value: oneLine(entry[3]) });
    if (rows.length >= MAX_LIST_FILTERS) break;
  }
  return rows;
}

/**
 * The filters, as the one line the prompt carries.
 *
 * @param {Array<{field: string, op: string, value: string}>} rows the rows
 * @returns {string} the line, or "" when there are none
 */
export function renderListFilters(rows) {
  if (!Array.isArray(rows) || !rows.length) return "";
  return rows
    .map((row) => `${row.field} ${row.op} ${row.value}`.trim())
    .join("; ")
    .slice(0, MAX_FILTER_TEXT);
}

/**
 * Normalise a list view's columns into the field names they show.
 *
 * The Desk's list holds a column per field, plus the indicator and
 * subject columns, which name no field of their own.
 *
 * @param {Array} raw the columns, as the list view holds them
 * @returns {string[]} the field names
 */
export function describeListColumns(raw) {
  if (!Array.isArray(raw)) return [];
  const names = [];
  for (const entry of raw) {
    if (!entry) continue;
    const df = entry.df || entry;
    const name = oneLine(df.fieldname);
    if (!name) continue;
    names.push(name);
    if (names.length >= MAX_LIST_COLUMNS) break;
  }
  return names;
}

/**
 * Normalise a report's filters into `{field, op, value}` rows.
 *
 * A report's filter is a control with a DocField and a value, and the
 * value may be read through a method rather than a property. A filter
 * with no value is dropped: a report ships with most of them empty.
 *
 * @param {Array} raw the filter controls
 * @returns {Array<{field: string, value: string}>} the rows
 */
export function describeReportFilters(raw) {
  if (!Array.isArray(raw)) return [];
  const rows = [];
  for (const control of raw) {
    if (!control) continue;
    const df = control.df || {};
    const field = oneLine(df.fieldname || control.fieldname);
    if (!field) continue;

    let value = control.value;
    if (typeof control.get_value === "function") {
      try {
        value = control.get_value();
      } catch {
        // The control cannot say; its own value will have to do.
      }
    }
    const text = oneLine(value);
    if (!text) continue;

    // A report's filter is a value, not a comparison, so it is
    // carried as one: "company = Albanna" reads the same as the
    // list's, and a range reads as the range it is.
    rows.push({ field, op: "=", value: text });
    if (rows.length >= MAX_LIST_FILTERS) break;
  }
  return rows;
}

/**
 * The list's sort, as one line.
 *
 * @param {string} by the field the list is sorted by
 * @param {string} order the direction
 * @returns {string} the line, or "" when the list names no field
 */
export function describeSort(by, order) {
  const field = oneLine(by);
  if (!field) return "";
  return `${field} ${oneLine(order) || "desc"}`;
}

/**
 * The columns, as the one line the prompt carries.
 *
 * @param {string[]} names the field names
 * @returns {string} the line, or "" when there are none
 */
export function renderListColumns(names) {
  if (!Array.isArray(names) || !names.length) return "";
  return names.join(", ").slice(0, MAX_COLUMN_TEXT);
}

/**
 * The filters of the live list view.
 *
 * @param {object} list the list view
 * @returns {Array} the quadruples, or [] when the list cannot say
 */
function listFilters(list) {
  if (!list || typeof list.get_filters_for_args !== "function") return [];
  try {
    return list.get_filters_for_args() || [];
  } catch {
    // A list that cannot say what it is filtered by is a list whose
    // filters are unknown, not a list with no filters.
    return [];
  }
}

/**
 * One line of text: whitespace collapsed.
 *
 * The page context is carried as lines, and a value that carries a
 * newline of its own would be two lines — and the second one would look
 * like part of the framing rather than part of the data.
 *
 * @param {*} value the value
 * @returns {string} the value, on one line
 */
function oneLine(value) {
  if (value === null || value === undefined) return "";
  // A range filter is an object, and "[object Object]" says nothing
  // about it.
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value).replace(/\s+/g, " ").trim();
}

/**
 * A readable title for a document.
 *
 * `doc.title` is null on most ERPNext documents — the field is not a thing
 * ERPNext has — so a title that stops at the name is a title that says
 * nothing. The party and the amount are what identify a document to a
 * person, so they are used when the title is missing.
 */
function documentTitle(doc) {
  if (doc.title) return doc.title;
  for (const field of [
    "customer",
    "supplier",
    "company",
    "item_name",
    "full_name",
    "subject",
  ]) {
    if (doc[field]) return String(doc[field]);
  }
  return doc.name || "";
}

/**
 * The text the user has selected, if any.
 *
 * @param {{window?: object}} [env] the browser, for the tests
 * @returns {string} the selected text, clipped
 */
export function currentSelection(env) {
  const win = envEnv(env);
  try {
    const selection = win.getSelection && win.getSelection();
    if (!selection) return "";
    const text = String(selection).trim();
    if (text.length < 3) return "";
    return text.slice(0, MAX_SELECTION);
  } catch {
    return "";
  }
}

/**
 * The window the readers run against.
 *
 * Every window-touching function takes `env` so the tests can drive it;
 * when the caller says nothing, the real globals are it. `getSelection`
 * is reached through the window rather than bare `window` for the same
 * reason — a stub in the tests is a window for these purposes.
 */
function envEnv(env) {
  const provided = env && typeof env === "object" ? env : {};
  return (
    provided.window || (typeof window !== "undefined" ? window : {})
  );
}
