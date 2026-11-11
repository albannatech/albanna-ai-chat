// This core's wire contract — the one place the frontend's assumptions live.
//
// This is the Layer B of the port: the part that is *bound* to this app's
// contract and therefore rewritten rather than copied. `albanna`'s widget
// hard-coded `albanna_chat_progress` as its socket event and reached for
// endpoints by name in a dozen places, so a change to either was a change
// found by reading the whole panel.
//
// Everything the frontend assumes about the server is named here, once. The
// API implements this; the tests assert it. When the two disagree, the test
// fails rather than the panel silently doing nothing.
//
// What is deliberately *not* here: no `frappe` import, no socket connection,
// no tool names. Those belong to the modules that use them.

/** The app's name, as Frappe knows it. */
export const APP_NAME = "albanna_ai_chat";

/** The socket.io event the server publishes turn progress on. */
export const STREAM_EVENT = "albanna_ai_chat_progress";

/** The socket.io event the server publishes a finished turn on. */
export const TURN_DONE_EVENT = "albanna_ai_chat_turn_done";

/**
 * The whitelisted endpoints the panel calls.
 *
 * Every one is a path under `/api/method/`, which is where Frappe serves
 * whitelisted functions from. They are named here so the transport module
 * never spells one out.
 */
export const ENDPOINTS = {
  /** Start a turn. */
  startTurn: `${APP_NAME}.api.chat.start_turn`,
  /** Read back a turn's finished answer, for a client whose socket died. */
  getTurn: `${APP_NAME}.api.chat.get_turn`,
  /** Stop a turn at the reader's request. */
  stopTurn: `${APP_NAME}.api.chat.stop_turn`,
  /** Answer a question the assistant asked. */
  answerQuestion: `${APP_NAME}.api.chat.answer_question`,
  /** Approve or refuse a write that is waiting. */
  resolveApproval: `${APP_NAME}.api.chat.resolve_approval`,
  /** The conversations the reader may see. */
  conversations: `${APP_NAME}.api.chat.conversations`,
  /** Whether the widget should render for this reader at all. */
  access: `${APP_NAME}.api.chat.access`,
};

/**
 * The envelope every tool result and every endpoint answer arrives in.
 *
 * `status` is "ok" or "error". `message` is the one line a reader could be
 * shown. `data` is the payload. `hints` is what to do about it — a failure
 * the caller cannot act on is a failure the caller will retry identically.
 *
 * The shape is the one `albanna`'s `ok()`/`error()` settled on and it is
 * kept, because a tool result envelope is not this app's to redesign and
 * the model reads it.
 */
export const ENVELOPE_STATUS = {
  OK: "ok",
  ERROR: "error",
};

/**
 * The message roles, in the order the server's doctype declares them.
 *
 * Mirrors `AI Chat Message.role`. A role the runtime does not recognise is a
 * message the panel cannot render, so the list is asserted rather than
 * assumed.
 */
export const ROLES = ["system", "user", "assistant", "tool"];

/**
 * The turn phases, in the order the server's doctype declares them.
 *
 * Mirrors `AI Chat Conversation.status` and `chat.turn.TurnState`. Kept as
 * data here so the widget and the server cannot drift, and asserted by
 * `tests/js/turn-state.test.mjs`.
 */
export const PHASES = [
  "idle",
  "running",
  "awaiting_tool",
  "awaiting_approval",
  "awaiting_answer",
  "done",
  "failed",
  "stopped",
];

/**
 * The progress events the server publishes on STREAM_EVENT.
 *
 * A turn is not a request that returns an answer — it is a request that
 * starts a turn, a stream of progress events, and eventually an answer. The
 * panel shows tokens as they are produced and each tool call as it starts
 * and finishes, so the event names are part of the contract.
 */
export const PROGRESS = {
  /** A piece of the answer's text. */
  TEXT: "text",
  /** A tool call started. */
  TOOL_START: "tool_start",
  /** A tool call finished. */
  TOOL_END: "tool_end",
  /** The turn moved to a new phase. */
  PHASE: "phase",
  /** The turn is over. */
  DONE: "done",
  /** The turn failed. */
  ERROR: "error",
};

/**
 * Read an envelope out of a response body.
 *
 * @param {*} body the parsed response body
 * @returns {{status: string, message: string, data: *, hints: string[]}} the envelope
 */
export function readEnvelope(body) {
  const payload = body && typeof body === "object" ? body : {};
  const hints = Array.isArray(payload.hints) ? payload.hints.map(String) : [];
  return {
    status: String(payload.status || (payload.exc ? ENVELOPE_STATUS.ERROR : ENVELOPE_STATUS.OK)),
    message: String(payload.message || ""),
    data: payload.data !== undefined ? payload.data : payload,
    hints,
  };
}
