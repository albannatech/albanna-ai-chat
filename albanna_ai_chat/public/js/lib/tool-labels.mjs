// What a tool call is called, in the reader's language.
//
// The transcript shows a tool call as it happens: a line that says what the
// assistant is doing, and a summary at the end that says what it did. Both are
// *labels*, and a label is the reader's business — the tool's own name
// (`read_file`, `write_file`) is the model's name for it, and it is available on
// demand rather than on the face of the conversation.
//
// This was the panel's own logic until it was tested. A label that reads
// "Working" for a tool the manifest knows by another name is a label nobody
// notices being wrong, which is the kind that stays wrong.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node. The language
// comes through `lib/i18n.mjs`, as everywhere else in the widget.
//
// What is rewritten rather than ported
// -----------------------------------
// `albanna`'s table named its thirteen tools — `list_docs`, `run_report`,
// `create_doc` — because that was its whole surface. This core has three file
// tools plus whatever an extension contributes, and an extension's tools are
// names this module has never heard of. So the table covers the core's three,
// and everything else falls to a default that is honest about not knowing:
// "Working" is a true sentence about a tool whose name means nothing to a
// reader, and a table that guessed would be a table that was wrong.
//
// An extension that wants its own labels declares them — see `EXTENSION_LABELS`
// below, which is the seam rather than a hardcoded list.

import { translate } from "./i18n.mjs";

/**
 * Labels an extension has declared for its own tools.
 *
 * A module-level map rather than a setting, because a label is *code* — it ships
 * with the extension that owns the tool and is tested with it. A label that
 * lived in a site setting would be a label an operator had to maintain by hand
 * for every tool on the site.
 *
 * Shape: `{ tool_name: { label, action } }`.
 */
export const EXTENSION_LABELS = {};

/**
 * The status the turn is in, in the reader's language.
 *
 * The server sends a *code*, not a sentence: the turn runs in a worker, and a
 * worker has no user's language to render a label in. Only the reader has one.
 *
 * The codes are this core's turn phases, mirroring `chat.turn.TurnState` — a
 * phase the panel cannot name is a phase the panel shows as a spinner forever.
 *
 * @param {string} code the status code
 * @returns {string} the label
 */
export function statusLabel(code) {
  switch (code) {
    case "running":
      return translate("Thinking");
    case "awaiting_tool":
      return translate("Working");
    case "awaiting_approval":
      return translate("Waiting for your approval");
    case "awaiting_answer":
      return translate("Waiting for your answer");
    case "done":
      return translate("Done");
    case "failed":
      return translate("Something went wrong");
    case "stopped":
      return translate("Stopped");
    default:
      return "";
  }
}

/**
 * What a tool call is called, in the reader's language.
 *
 * The tool's *name* is the model's name for it, and it is not the reader's. A
 * person wants to know that the assistant is looking something up, not which
 * function it reached for. The name is still available, on demand, in the
 * summary under the answer.
 *
 * @param {string} name the tool's name
 * @returns {string} the label
 */
export function toolLabel(name) {
  const key = String(name || "");
  const extension = EXTENSION_LABELS[key];
  if (extension && extension.label) return extension.label;

  switch (key) {
    case "read_file":
      return translate("Reading a file");
    case "write_file":
      return translate("Writing a file");
    case "edit_file":
      return translate("Editing a file");
    default:
      return translate("Working");
  }
}

/**
 * The verb for a tool that changes something, in the reader's language.
 *
 * Used on the approval card so the reader sees at a glance what kind of change
 * is being asked for — "Writing a file" rather than only the file's name.
 * Returns nothing for read tools, which never reach the card at all.
 *
 * @param {string} name the tool's name
 * @returns {string} the action verb, or nothing when the tool does not write
 */
export function toolAction(name) {
  const key = String(name || "");
  const extension = EXTENSION_LABELS[key];
  if (extension && extension.action) return extension.action;

  switch (key) {
    case "write_file":
      return translate("Writing");
    case "edit_file":
      return translate("Editing");
    default:
      return "";
  }
}

/**
 * The label, with what it is being done to.
 *
 * What is being looked at, not only how: "Reading a file report.pdf" tells the
 * reader the question is being answered against the right thing.
 *
 * The target is whatever the tool's arguments name — `file` for this core's
 * tools, `doctype` for an extension's. Both are read, because a label that
 * named only one would be a label that went blank for the other.
 *
 * @param {string} name the tool's name
 * @param {object} toolArguments the arguments the model called it with
 * @returns {string} the label
 */
export function describeTool(name, toolArguments) {
  const label = toolLabel(name);
  const args = toolArguments || {};
  const target = String(args.file || args.doctype || args.name || "").trim();
  if (!target) return label;
  return `${label} ${target}`;
}

/**
 * The one line that says what the turn did.
 *
 * The count is of *distinct* tools and of *calls*, because "3 tools" and
 * "7 calls" are different questions and the reader may want either. The model's
 * own names are behind the disclosure, for the reader who wants them.
 *
 * @param {object} message the message
 * @returns {string} the summary
 */
export function toolSummary(message) {
  const tools = (message && message.tools) || [];
  if (!tools.length) return "";
  const distinct = new Set(tools.map((tool) => tool.name)).size;
  return translate("Tools used: {0} · Calls: {1}", [distinct, tools.length]);
}
