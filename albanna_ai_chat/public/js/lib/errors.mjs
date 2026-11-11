// The text a server refusal carries, whatever shape it arrives in.
//
// Ported from `albanna`'s side-chat without a change, because a refusal
// arrives in the shapes Frappe sends and those shapes are not this app's
// to redesign. The unwrapping was written twice in the original — once in
// the turn's own module and once in the composer — and the two copies
// drifted apart: the composer's copy had no test, so a change in the shape
// a refusal arrives in was a change half the panel noticed. It is here now,
// and it is read by plain node, with no Vue and no Desk.
//
// A refusal reaches the browser in one of three shapes:
//
//   - a rejected request, whose body is JSON;
//   - a response body with `_server_messages` in it;
//   - a traceback, which is a list of lines.
//
// The Desk's own envelope is three levels deep: the text is in its
// `message`, the envelopes come as a list, and each envelope has been
// serialised to a string inside the list. Every level is handled rather
// than assumed.

/**
 * The text the server refused with, if it said.
 *
 * @param {object} source the rejected request, or the raw response
 * @returns {string} the message, or an empty string
 */
export function serverMessage(source) {
  if (!source) return "";

  // A rejected request carries the body as text.
  let body = source.responseJSON;
  if (!body && typeof source.responseText === "string") {
    try {
      body = JSON.parse(source.responseText);
    } catch (error) {
      body = null;
    }
  }
  const payload = body && typeof body === "object" ? body : source;

  const messages = payload._server_messages;
  if (messages) {
    try {
      const text = messageText(JSON.parse(messages));
      if (text) return text;
    } catch (error) {
      // Not JSON: fall through to the traceback.
    }
  }

  const exc = payload.exc;
  if (exc) {
    try {
      const parsed = JSON.parse(exc);
      if (Array.isArray(parsed) && parsed.length) {
        return lastLine(String(parsed[parsed.length - 1]));
      }
    } catch (error) {
      return lastLine(String(exc));
    }
  }

  return "";
}

/**
 * The text a failure is shown to the reader in.
 *
 * A failure carries what the server said, and the caller carries what to
 * say when the server said nothing. The server's text comes first, because
 * it is the reason; the caller's sentence comes second, because it is the
 * only thing there is when there is no reason.
 *
 * This was written fifteen times in the panel, and the copies were not the
 * same: each one fell back to the failure itself, which is `Error` or
 * `[object Object]`, rather than to the sentence the caller had written for
 * exactly that case. The sentence could therefore never be read.
 *
 * @param {Error|object} failure the failure
 * @param {string} [fallback] the sentence to use when the failure carries no text of its own
 * @returns {string} the text
 */
export function failureText(failure, fallback = "") {
  const message = failure && failure.message;
  if (message) return String(message);
  if (fallback) return fallback;
  return failure ? String(failure) : "";
}

/**
 * The text inside a server message, whatever shape it arrives in.
 *
 * A server message is an *envelope* — the text is in its `message`, and the
 * rest is how the Desk would present it — and Frappe sends it as a list of
 * envelopes, each of which has been serialised to a string inside the list.
 * So the unwrapping is three levels deep, and each level is handled rather
 * than assumed.
 *
 * @param {*} value the server message
 * @returns {string} the text, or an empty string
 */
export function messageText(value) {
  if (!value) return "";

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed.startsWith("{")) {
      try {
        return messageText(JSON.parse(trimmed));
      } catch (error) {
        return value;
      }
    }
    return value;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const text = messageText(item);
      if (text) return text;
    }
    return "";
  }

  if (typeof value === "object" && value.message) {
    return String(value.message);
  }

  return "";
}

/**
 * The last line of a traceback, without the exception class in front of it.
 *
 * @param {string} text the traceback
 * @returns {string} the message
 */
export function lastLine(text) {
  const line =
    String(text || "")
      .trim()
      .split("\n")
      .pop() || "";
  return line.replace(/^[A-Za-z_.]*(Error|Exception):\s*/, "");
}
