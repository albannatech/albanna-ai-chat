// The empty state's suggested questions.
//
// The widget's whole claim is that it knows what the user is looking at,
// and an empty panel that offers "Which Sales Orders are still open?" on
// an HR page is a panel that does not. So the suggestions follow the
// page: a form gets questions about *that* document, a list gets questions
// about the list the reader is looking at, a report gets questions about
// the report. Only when there is nothing to anchor on do we fall back to
// the generic ones.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node. The
// sentences go through `lib/i18n.mjs`'s `translate` rather than a local
// `__` — a guard copied into six files is a guard that drifts.

import { translate } from "./i18n.mjs";

/**
 * The kind of empty state the page calls for.
 *
 * @param {{view?: string, doctype?: string, name?: string, report?: string}} context
 * @returns {"form" | "list" | "report" | "generic"} the set to show
 */
export function exampleSet(context) {
  const page = context || {};
  if (page.view === "form" && page.doctype) return "form";
  if (page.report) return "report";
  // A list is a route whose last segment is "List" and which carries a
  // doctype. `resolveContext` sets `view` to the route for non-forms,
  // so we lean on the doctype being present instead.
  if (page.doctype && !page.name) return "list";
  return "generic";
}

/**
 * The document the empty state is asking about, if any.
 *
 * @param {{doctype?: string, name?: string}} context
 * @returns {{doctype: string, name: string} | null}
 */
export function openDocumentFrom(context) {
  const page = context || {};
  if (!page.doctype || !page.name) return null;
  return { doctype: page.doctype, name: page.name };
}

/**
 * The questions the empty state offers, for a given page.
 *
 * With a document open, the questions are about *that* document — a
 * reader with a Sales Order open wants to know about the Sales Order in
 * front of them, not about sales orders in general. Without one, they
 * are the questions people actually ask of a site.
 *
 * They are asked as questions rather than described, because a suggestion
 * the reader has to translate into a question is a suggestion that costs
 * more than it gives.
 *
 * @param {{view?: string, doctype?: string, name?: string, report?: string}} context
 * @param {number|null} count how many rows the list shows, if any
 * @param {string} party the party on a brand-new document, if any
 * @returns {string[]} the suggested questions
 */
export function examplesFor(context, count, party) {
  const ctx = context || {};
  const set = exampleSet(ctx);

  if (set === "form") {
    const document = openDocumentFrom(ctx);
    if (document && document.doctype === "Issue") {
      return [
        translate("What is the customer asking for?"),
        translate("What has already been done?"),
        translate("What is still open?"),
      ];
    }
    if (document) {
      return [
        translate("Summarise this {0}", [document.doctype]),
        translate("What is the status of this {0}?", [document.doctype]),
        translate("What is the total of this {0}?", [document.doctype]),
      ];
    }
    // A brand-new document: offer to seed it from the last similar one.
    if (party && ctx.doctype) {
      return [
        translate("Copy this {0} from the last one for {1}", [ctx.doctype, party]),
        translate("What fields are required for this {0}?", [ctx.doctype]),
      ];
    }
    if (ctx.doctype) {
      return [translate("What fields are required for this {0}?", [ctx.doctype])];
    }
    return [];
  }

  if (set === "list" && ctx.doctype) {
    if (ctx.doctype === "Issue") {
      return [
        translate("What is the customer asking for?"),
        translate("What has already been done?"),
        translate("What is still open?"),
        translate("Show my open tickets"),
      ];
    }
    if (count === 0) {
      return [translate("Create a {0}", [ctx.doctype])];
    }
    return [
      translate("How many {0} are there?", [ctx.doctype]),
      translate("Which {0} are still open?", [ctx.doctype]),
      translate("What is the total value of these {0}?", [ctx.doctype]),
    ];
  }

  if (set === "report" && ctx.report) {
    return [
      translate("Summarise this report"),
      translate("What are the totals in this report?"),
      translate("Which rows stand out?"),
    ];
  }

  // Generic fallback: support-shaped, and "my" is never used — the
  // assistant has no way to know who "my" is, so it answers with every
  // open ticket and calls them the reader's.
  return [
    translate("How many open Issues are there?"),
    translate("Which Issues are still open?"),
    translate("How many customers are there?"),
  ];
}
