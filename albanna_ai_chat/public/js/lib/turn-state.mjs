// The turn's state, and the transitions between its states.
//
// The *pattern* is ported from `albanna`'s side-chat: the state of a turn is
// the part of the widget that can be wrong in ways the reader can see — a
// turn that is "running" and has already finished, a stop button that stops
// nothing, an error that hides a message — so it is written down once, as a
// state machine, and the component is a view over it. Every function takes
// the state and changes it; the state is a plain object, so it is tested
// without Vue.
//
// The *vocabulary* is not ported, and this is the clearest example of why
// the port is a rewrite with a reference rather than a copy. `albanna`'s
// widget had three phases — idle, running, stopping — because its tool set
// was fixed and small. This core has eight, because a turn here can be
// waiting on a tool, waiting on the reader's approval of a write, or
// waiting on the reader's answer to a question, and those are three
// different things the panel has to show differently.
//
// The eight values mirror `albanna_ai_chat.chat.turn.TurnState` exactly, and
// `tests/js/turn-state.test.mjs` asserts the two lists agree. A status the
// runtime does not recognise is a conversation stuck in it.

/** No turn is running. */
export const IDLE = "idle";
/** A turn is running. */
export const RUNNING = "running";
/** The provider has called tools; they are executing. */
export const AWAITING_TOOL = "awaiting_tool";
/** A write is waiting for the reader's approval. */
export const AWAITING_APPROVAL = "awaiting_approval";
/** A question is waiting for the reader's answer. */
export const AWAITING_ANSWER = "awaiting_answer";
/** The turn finished. */
export const DONE = "done";
/** The turn failed. */
export const FAILED = "failed";
/** The reader stopped it. */
export const STOPPED = "stopped";

/** Every state, in the order the Python enum declares them. */
export const STATES = [
  IDLE,
  RUNNING,
  AWAITING_TOOL,
  AWAITING_APPROVAL,
  AWAITING_ANSWER,
  DONE,
  FAILED,
  STOPPED,
];

/** The states in which the reader is being waited on. */
export const WAITING_ON_READER = [AWAITING_APPROVAL, AWAITING_ANSWER];

/** The states in which a turn is over. */
export const FINISHED = [DONE, FAILED, STOPPED];

/**
 * The state of the widget, before anything has happened.
 *
 * @returns {object} the state
 */
export function initialState() {
  return {
    /** One of STATES. */
    phase: IDLE,
    /** The transcript. */
    messages: [],
    /** What the assistant is doing right now. */
    activity: "",
    /** Something went wrong. */
    error: "",
    /** Something happened that is not an error. */
    notice: "",
    /** The reader's last question, for a retry. */
    asked: "",
  };
}

/**
 * May the reader ask a question?
 *
 * @param {object} state the state
 * @returns {boolean} true when a question may be sent
 */
export function canSend(state) {
  return state.phase === IDLE;
}

/**
 * May the reader stop the turn?
 *
 * A turn that is waiting on the reader cannot be stopped by the reader —
 * they are the one being waited on. The work finishes on the server; the
 * waiting stops here.
 *
 * @param {object} state the state
 * @returns {boolean} true when a turn may be stopped
 */
export function canStop(state) {
  return state.phase === RUNNING || state.phase === AWAITING_TOOL;
}

/**
 * Is a turn in flight?
 *
 * @param {object} state the state
 * @returns {boolean} true when a turn is running or settling
 */
export function isBusy(state) {
  return state.phase !== IDLE && !FINISHED.includes(state.phase);
}

/**
 * Is the panel waiting on the reader?
 *
 * The composer shows a different thing in each of these: an approval is a
 * decision about a write, a question is a choice the assistant cannot make.
 * Collapsing them into "busy" is how a reader ends up staring at a spinner
 * when what is wanted is a button.
 *
 * @param {object} state the state
 * @returns {boolean} true when the reader is being waited on
 */
export function isWaitingOnReader(state) {
  return WAITING_ON_READER.includes(state.phase);
}

/**
 * Start a turn.
 *
 * @param {object} state the state
 * @param {string} question the reader's question
 * @param {object} asked the message for the question
 * @param {object} answer the message for the answer
 * @returns {object} the answer message
 */
export function beginTurn(state, question, asked, answer) {
  state.phase = RUNNING;
  state.activity = "";
  state.error = "";
  state.notice = "";
  state.asked = question;
  state.messages.push(asked, answer);
  return answer;
}

/**
 * Say what the assistant is doing.
 *
 * @param {object} state the state
 * @param {string} activity the line to show
 */
export function setActivity(state, activity) {
  state.activity = activity;
}

/**
 * Move to a new phase.
 *
 * The single place a phase changes, so that anything which depends on the
 * phase is computed from it rather than tracked beside it. `busy` and a
 * per-message "pending" flag were two answers to one question in the
 * original, and they could disagree.
 *
 * @param {object} state the state
 * @param {string} phase one of STATES
 */
export function setPhase(state, phase) {
  if (!STATES.includes(phase)) {
    throw new Error(`Unknown turn phase: ${phase}`);
  }
  state.phase = phase;
}

/**
 * Finish a turn.
 *
 * The answer's *text* is the caller's: it renders the text, and this says
 * that the turn is over. One owner each.
 *
 * @param {object} state the state
 * @param {object} answer the answer message
 */
export function endTurn(state, answer) {
  if (answer) answer.pending = false;
  state.phase = DONE;
  state.activity = "";
}

/**
 * Fail a turn.
 *
 * @param {object} state the state
 * @param {object} answer the answer message, if there is one
 * @param {string} message what went wrong
 */
export function failTurn(state, answer, message) {
  if (answer) answer.pending = false;
  state.phase = FAILED;
  state.activity = "";
  state.error = message;
}

/**
 * Stop a turn at the reader's request.
 *
 * The work finishes on the server; the waiting stops here. What arrived is
 * kept — it is the truth so far — and the answer is in the conversation when
 * the reader comes back to it.
 *
 * The notice is the caller's: the panel says *why* a turn stopped, and
 * "because you moved to another page" is not the same sentence as "because
 * you asked it to".
 *
 * @param {object} state the state
 * @param {object} answer the answer message, if there is one
 */
export function stopTurn(state, answer) {
  if (answer) answer.pending = false;
  state.phase = STOPPED;
  state.activity = "";
}

/**
 * Clear the transcript, because the reader has moved to another page.
 *
 * A turn in flight is stopped first: the answer would be about the page the
 * reader has left, and it belongs to that page's thread.
 *
 * @param {object} state the state
 * @returns {object|null} the answer message of a turn that was stopped
 */
export function clearTranscript(state) {
  let stopped = null;
  if (isBusy(state)) {
    const answer = state.messages[state.messages.length - 1];
    if (answer && answer.pending) stopped = answer;
    stopTurn(state, answer);
  }
  state.messages = [];
  return stopped;
}

/**
 * Put a message away.
 *
 * @param {object} state the state
 * @param {string} channel "error" or "notice"
 */
export function dismiss(state, channel) {
  if (channel === "error") state.error = "";
  if (channel === "notice") state.notice = "";
}
