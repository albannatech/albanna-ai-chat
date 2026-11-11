// The notices the panel can show, in the reader's language.
//
// A notice is the panel saying something in passing: the turn was stopped, the
// answer was cut off, nothing was saved because it was a dry run. Each is a
// sentence the reader reads once, in their own language.
//
// The state holds a *key*, not a sentence. The state machine is pure and has no
// language of its own, and the reader's language can change under a notice that
// was already shown — a sentence stored once would be the wrong language the
// next morning. So the key is stored and the sentence is drawn from it at the
// moment it is shown.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.
//
// What is rewritten rather than ported
// -----------------------------------
// `albanna`'s notice keys named its own features — a table to copy, a submission
// to cancel, a document to revert. This core has none of those yet, so its list
// is shorter and says only what is true. A notice key with no sentence behind it
// is a notice that renders blank, which is worse than not having the key: the
// panel goes quiet exactly when it had something to say.

import { translate } from "./i18n.mjs";

/**
 * The notices the panel can show, in the reader's language.
 *
 * @param {string} notice the key
 * @returns {string} the sentence
 */
export function noticeText(notice) {
  switch (notice) {
    case "stopped":
      return translate("Stopped.");
    case "moved":
      return translate(
        "You moved to another page. The turn is still running — its answer will be in that page's conversation.",
      );
    case "no-answer":
      return translate("The turn produced no answer.");
    case "answer-cut-off":
      return translate("The answer was cut off because the turn needed too many steps.");
    case "refused":
      return translate("The assistant was not permitted to do that.");
    case "no-provider":
      return translate(
        "No model provider is configured for this site. Set one in Albanna AI Chat Settings.",
      );
    case "conversation-deleted":
      return translate("The conversation was deleted.");
    case "started":
      return translate("A new conversation was started.");
    case "attachments-dropped":
      return translate("This model cannot see attachments; the attachment was ignored.");
    case "dry-run":
      return translate("Dry run — nothing was saved.");
    case "undone":
      return translate("The turn was undone.");
    default:
      return "";
  }
}

/**
 * Every notice key this core can show.
 *
 * Exported so a test can assert that every key has a sentence — a key that
 * renders blank is a panel that goes quiet when it had something to say, and
 * that is exactly the kind of thing nobody notices until a reader reports it.
 *
 * @returns {string[]} the keys
 */
export function noticeKeys() {
  return [
    "stopped",
    "moved",
    "no-answer",
    "answer-cut-off",
    "refused",
    "no-provider",
    "conversation-deleted",
    "started",
    "attachments-dropped",
    "dry-run",
    "undone",
  ];
}
