// A conversation as a Markdown file.
//
// The reader may want the thread outside the panel — to paste into a
// ticket, to keep for reference. The shape is deliberately plain: one
// line per message, the speaker in bold, a blank line between turns.
// Everything the file needs is already in the transcript; nothing is
// fetched and nothing is invented.
//
// The *download* lives in the panel component — it is DOM work. What
// lives here is the part worth testing: which messages are sayable, in
// whose voice, and what happens to tool rows.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/**
 * The transcript as one Markdown document.
 *
 * Tool rows (role `tool`) are skipped: they are the plumbing of an
 * answer, and the answer already says what its calls found. A message
 * with no content still gets its speaker line, so the file shows the
 * shape of the conversation rather than silently dropping turns.
 *
 * @param {Array<{role: string, content: string}>} messages the transcript
 * @param {{reader: string, assistant: string}} speakers how each side is
 *   introduced — already pluralised/translated by the caller
 * @returns {string} the Markdown text
 */
export function conversationToMarkdown(messages, speakers) {
  const lines = [];
  for (const message of messages || []) {
    if (!message) continue;
    if (message.role === "user") {
      lines.push(`**${speakers.reader}:** ${message.content || ""}`);
    } else if (message.role === "assistant") {
      lines.push(`**${speakers.assistant}:**\n\n${message.content || ""}`);
    } else {
      // A tool row, or anything else: plumbing, not speech.
      continue;
    }
    lines.push("");
  }
  // A file that ends mid-block is a file that renders badly; a final
  // newline is part of the format.
  return `${lines.join("\n").trimEnd()}\n`;
}

/**
 * A filename for the export, sortable and unambiguous.
 *
 * @param {number} when the export's clock time, in milliseconds
 * @param {string} [app] the prefix the file carries
 * @returns {string}
 */
export function exportFilename(when, app = "albanna-ai-chat") {
  const moment = new Date(when);
  const stamp = [
    moment.getFullYear(),
    String(moment.getMonth() + 1).padStart(2, "0"),
    String(moment.getDate()).padStart(2, "0"),
  ].join("");
  const time = [
    String(moment.getHours()).padStart(2, "0"),
    String(moment.getMinutes()).padStart(2, "0"),
  ].join("");
  return `${app}-conversation-${stamp}-${time}.md`;
}
