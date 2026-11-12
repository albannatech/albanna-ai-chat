// The live hint's names.
//
// The hint counts the reader's overdue invoices and then says nothing about
// *which* ones. A number with no names sends the reader back to the list to
// work out what the number meant — and the list is the page they are already
// looking at.
//
// So the hint names them: the documents the reader would recognise at a
// glance, and a count of the ones it left out.
//
// Pure — no `frappe`, no DOM — so it is tested under plain node. The one
// sentence goes through `lib/i18n.mjs`'s `translate`.

import { translate } from "./i18n.mjs";

/**
 * The Desk's route to a document.
 *
 * It is the link the Desk's own list view makes, so that a name in the hint
 * opens the same thing a name in the list opens.
 *
 * `frappe.router.slug` lower-cases the DocType and turns its spaces into
 * dashes; the rule is spelled out here so that this module needs nothing but
 * the strings it is given — and so that the link can be checked under plain
 * node, without a Desk around it.
 *
 * @param {string} doctype the DocType, as the Desk names it
 * @param {string} name the document's name
 * @returns {string} the Desk's route
 */
export function documentRoute(doctype, name) {
  const slug = String(doctype || "")
    .toLowerCase()
    .replace(/ /g, "-");
  return `/app/${encodeURIComponent(slug)}/${encodeURIComponent(name)}`;
}

/**
 * The names the hint carries, as the panel draws them.
 *
 * The label is the name the reader sees in the list — the customer on an
 * invoice — and the document's own name travels with it, because two
 * invoices of the same customer are two different invoices. A document
 * with no title is labelled by its name; that is what the reader would see
 * anyway.
 *
 * The server decides how many names there are, and counts the rest itself,
 * so this draws what it is given rather than deciding on its own: a panel
 * that showed three of five names while claiming two were left out would be
 * a panel that cannot be trusted.
 *
 * @param {object} payload the hint, as the server sent it
 * @returns {object[]} the documents to draw
 */
export function namedDocuments(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  const documents = Array.isArray(source.documents) ? source.documents : [];
  const doctype = String(source.doctype || "");

  const named = [];
  for (const document of documents) {
    if (!document || !document.name) continue;
    const name = String(document.name);
    const title = String(document.title || "").trim();
    named.push({
      name,
      title,
      label: title || name,
      url: documentRoute(doctype, name),
    });
  }
  return named;
}

/**
 * How many documents the hint left out.
 *
 * @param {object} payload the hint, as the server sent it
 * @returns {number} the number of documents not named
 */
export function unnamedCount(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  const more = Number(source.more);
  if (!Number.isFinite(more) || more <= 0) return 0;
  return Math.floor(more);
}

/**
 * The line that says how many documents the hint left out.
 *
 * There is no line when nothing was left out: "and 0 more" is a sentence
 * about nothing, and a panel that says it is a panel that is counting
 * rather than talking.
 *
 * @param {number} count the number of documents not named
 * @returns {string} the line, in the reader's language
 */
export function moreText(count) {
  const more = Number(count);
  if (!Number.isFinite(more) || more <= 0) return "";
  return translate("and {0} more", [Math.floor(more)]);
}
