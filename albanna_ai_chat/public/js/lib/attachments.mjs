// The rules for an attachment, before the bytes leave the browser, and the
// shape an attachment takes on its way.
//
// Ported from `albanna`'s `attachments.mjs`. The rule is here and not in the
// composer because it *is* a rule, and a rule that lives in a component is a
// rule nobody can test: this file is read by plain node, with no Vue and no
// Desk. The shape is here for the same reason, and because two files use it —
// the composer builds an attachment and the panel reads it.
//
// The list is the server's list, and the server publishes it: the browser is
// told which types the site takes rather than keeping a copy of them. A
// browser that accepts an SVG and a server that refuses it is a reader who
// chose a file, waited for the upload, and was then told the file they chose
// could not be attached.
//
// So this file has no list of its own. A browser that keeps a copy of the
// server's list is a browser whose copy goes stale the day the server's
// changes, and a stale list is a browser that accepts a file the server
// refuses.

/** The file is not one of the types that may be attached. */
export const REFUSED_TYPE = "type";

/** The file is over the site's ceiling. */
export const REFUSED_SIZE = "size";

/**
 * May this file be attached?
 *
 * @param {{type?: string, size?: number}} file the file the reader chose
 * @param {{types?: string[], maxBytes?: number}} rules the site's rules —
 *   the types that may be attached, and the ceiling in bytes. A ceiling of
 *   zero means no ceiling. No types means the site has not said, and nothing
 *   may be attached: a browser that guesses is a browser that guesses wrong.
 * @returns {{ok: boolean, reason: string}} whether it may be attached, and
 *   why it may not
 */
export function checkAttachment(file, rules = {}) {
  const types = rules.types || [];
  const maxBytes = Number(rules.maxBytes || 0);
  const type = String((file && file.type) || "");

  if (!types.includes(type)) {
    return { ok: false, reason: REFUSED_TYPE };
  }

  const size = Number((file && file.size) || 0);
  if (maxBytes && size > maxBytes) {
    return { ok: false, reason: REFUSED_SIZE };
  }

  return { ok: true, reason: "" };
}

/**
 * One attachment, as the composer holds it and the panel sends it.
 *
 * The six fields are the attachment: the bytes the model reads, the name the
 * reader recognises, the type the site checks, the size the reader is shown,
 * the address the file was stored under, and whether it was.
 *
 * @param {{dataUrl?: string, name?: string, type?: string, size?: number,
 *          fileUrl?: string, stored?: boolean}} parts the attachment's parts
 * @returns {object} the attachment
 */
export function makeAttachment(parts = {}) {
  return {
    dataUrl: parts.dataUrl || "",
    name: parts.name || "",
    type: parts.type || "",
    size: Number(parts.size || 0),
    fileUrl: parts.fileUrl || "",
    stored: parts.stored !== false,
  };
}

/**
 * Store every file, and write the list of them once.
 *
 * The list is written once, at the end, with every file that was stored.
 * Writing it after each file lets a later upload overwrite an earlier one,
 * and a reader who dropped three pictures finds one of them gone.
 *
 * @param {Array} files the files the reader chose
 * @param {(file: *) => Promise<object|null>} store the store to use
 * @param {(added: object[]) => void} write the one write of the list
 * @returns {Promise<object[]>} the attachments that were stored, in order
 */
export async function storeAll(files, store, write) {
  const added = [];
  for (const file of files) {
    const entry = await store(file);
    if (entry) added.push(entry);
  }
  if (added.length) write(added);
  return added;
}

/**
 * What a turn carries for its attachments: the bytes, and the addresses they
 * were stored under.
 *
 * The two lists are parallel: the address at one place is the address of the
 * bytes at the same place. The server relies on that to reuse the file
 * instead of writing the same bytes twice, so the two are built together and
 * never apart.
 *
 * The field names are this core's contract, declared in `lib/wire.mjs` and
 * implemented by `api/chat.py`'s `start_turn`. They are asserted here so a
 * rename on either side fails a test rather than silently dropping every
 * attachment a reader ever uploaded.
 *
 * @param {object[]} files the attachments
 * @returns {{attachments: string[], attachmentUrls: string[]}} what the turn carries
 */
export function turnAttachments(files) {
  return {
    attachments: files.map((file) => file.dataUrl || ""),
    attachmentUrls: files.map((file) => file.fileUrl || ""),
  };
}
