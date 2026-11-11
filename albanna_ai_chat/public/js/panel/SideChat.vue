<script setup>
/**
 * The panel — a view over `lib/`, and nothing else.
 *
 * `albanna`'s `SideChatApp.vue` is 3,396 lines, and most of it is logic that
 * belongs in a module: the turn state machine, the transport, the labels, the
 * attachment rules, the write-safety list. Over three releases that logic was
 * extracted into `lib/` and tested under plain node — and the component shrank
 * each time.
 *
 * This is that end state, written once. Every decision the panel makes is made
 * by a module in `lib/` that is tested without a browser; what is left here is
 * the shape of the thing on screen and the wiring between them. That is the
 * whole reason the port was worth doing rather than copying the file.
 *
 * What is deliberately absent
 * ---------------------------
 * No `<style>` block. Every rule lives in `css/albanna-ai-chat.css`, which is
 * the one file both language directions are emitted from. A component that
 * carried its own styles would need a second extraction pass in the build and a
 * second place to look for a rule.
 *
 * No `frappe` import. The transport is the only thing that talks to the server,
 * and it reads its endpoints from `lib/wire.mjs`.
 */

import { onBeforeUnmount, onMounted, ref, computed } from "vue";

import {
  canAnswer,
  answerMessage,
  questionCard,
} from "../lib/question.mjs";
import {
  canDecide,
  remainingSeconds,
  windowMs,
} from "../lib/approval.mjs";
import { noticeText } from "../lib/notices.mjs";
import {
  describeTool,
  statusLabel,
  toolSummary,
} from "../lib/tool-labels.mjs";
import {
  destructiveConsequence,
  isDestructiveTool,
} from "../lib/write-safety.mjs";
import {
  REASONS,
  refusalText,
  submitDecision,
} from "../lib/submit.mjs";
import {
  ENDPOINTS,
  PROGRESS,
  readEnvelope,
} from "../lib/wire.mjs";
import {
  AWAITING_APPROVAL,
  AWAITING_ANSWER,
  DONE,
  FAILED,
  IDLE,
  STOPPED,
  canStop,
  initialState,
  isWaitingOnReader,
  setActivity,
  setPhase,
} from "../lib/turn-state.mjs";
import { call, runTurn, subscribe } from "../lib/transport.mjs";
import { serverMessage } from "../lib/errors.mjs";

// --------------------------------------------------------------------------
// State.
//
// The state machine is `lib/turn-state.mjs`; this holds it. A phase is one
// answer to "what is happening", and everything on screen is computed from it
// rather than tracked beside it — `busy` and a per-message `pending` flag were
// two answers to one question in the original, and they could disagree.
// --------------------------------------------------------------------------

const state = ref(initialState());
const conversationId = ref("");
const pendingApproval = ref(null);
const pendingQuestion = ref(null);
const inflightTools = ref([]);
const unsubscribe = ref(() => {});

const busy = computed(() => state.value.phase !== IDLE && state.value.phase !== DONE);
const waiting = computed(() => isWaitingOnReader(state.value));
const statusText = computed(() => statusLabel(state.value.phase));

// --------------------------------------------------------------------------
// The composer.
//
// The rule is `lib/submit.mjs`, and the component does the side effects only
// when it says the question may go. A rule that lived here would be a rule
// nobody could test.
// --------------------------------------------------------------------------

const draft = ref("");
const composerProblem = ref("");

function onDraftInput() {
  composerProblem.value = "";
}

async function send() {
  const decision = submitDecision({
    modelValue: draft.value,
    busy: busy.value,
    canChat: true,
  });
  if (!decision.ok) {
    composerProblem.value = refusalText(decision.reason, decision.length);
    return;
  }

  draft.value = "";
  composerProblem.value = "";
  state.value.notice = "";

  const asked = { role: "user", content: decision.question, pending: false };
  const answer = { role: "assistant", content: "", pending: true, tools: [] };
  state.value.messages.push(asked, answer);
  setPhase(state.value, "running");

  try {
    const payload = await runTurn({
      question: decision.question,
      conversationId: conversationId.value,
      onEvent: onProgress,
      onQueued: (streamId) => {
        // The stream id is the turn's address on the server, and the panel
        // writes it down: a reader who reloads the Desk during a turn can find
        // the turn again.
        conversationId.value = streamId;
      },
    });
    applyPayload(payload, answer);
  } catch (error) {
    failTurnWith(answer, serverMessage(error) || "The request could not be completed.");
  }
}

// --------------------------------------------------------------------------
// Progress.
//
// The socket is the fast path and the poll is the guarantee; both arrive here
// as the same event shape, so the panel does not know which one delivered it.
// --------------------------------------------------------------------------

function onProgress(event) {
  switch (event.event) {
    case PROGRESS.TEXT:
      appendText(event.text || "");
      break;
    case PROGRESS.TOOL_START:
      inflightTools.value.push({
        name: event.name,
        arguments: event.arguments || {},
      });
      setActivity(state.value, describeTool(event.name, event.arguments || {}));
      break;
    case PROGRESS.TOOL_END:
      inflightTools.value = inflightTools.value.filter(
        (tool) => tool.name !== event.name,
      );
      setActivity(state.value, "");
      break;
    case PROGRESS.PHASE:
      setPhase(state.value, event.phase);
      break;
    case "confirm":
      // A card the socket never delivered comes back through the poll too, and
      // the transport passes it on once per request id — so this handler draws
      // it either way without redrawing a clock the server started.
      pendingApproval.value = event;
      setPhase(state.value, AWAITING_APPROVAL);
      break;
    case "question":
      pendingQuestion.value = questionCard(event);
      setPhase(state.value, AWAITING_ANSWER);
      break;
    default:
      break;
  }
}

function appendText(text) {
  const messages = state.value.messages;
  const answer = messages[messages.length - 1];
  if (answer && answer.role === "assistant") {
    answer.content += text;
  }
}

function applyPayload(payload, answer) {
  const envelope = readEnvelope(payload);

  if (envelope.status === "error") {
    failTurnWith(answer, envelope.message || "The turn failed.");
    return;
  }
  if (payload && payload.stopped) {
    // A stop is not a failure. Reporting it as one teaches the reader that
    // pressing Stop breaks things.
    answer.pending = false;
    setPhase(state.value, STOPPED);
    state.value.notice = noticeText("stopped");
    return;
  }

  answer.pending = false;
  if (payload && payload.answer) answer.content = payload.answer;
  setPhase(state.value, DONE);
}

function failTurnWith(answer, message) {
  answer.pending = false;
  setPhase(state.value, FAILED);
  state.value.error = message;
}

// --------------------------------------------------------------------------
// The reader's decisions.
//
// A question is a choice the assistant cannot make; an approval is a decision
// about a write. They are different cards because collapsing them into "busy"
// is how a reader ends up staring at a spinner when what is wanted is a button.
// --------------------------------------------------------------------------

async function answerQuestion(option) {
  const card = pendingQuestion.value;
  if (!canAnswer(card)) return;

  const message = answerMessage(card, option);
  state.value.messages.push({ role: "user", content: message, pending: false });
  pendingQuestion.value = null;
  setPhase(state.value, "running");

  try {
    await call(ENDPOINTS.answerQuestion, {
      stream_id: conversationId.value,
      answer: message,
    });
  } catch (error) {
    state.value.error = serverMessage(error) || "The answer could not be recorded.";
  }
}

async function resolveApproval(approved) {
  const approval = pendingApproval.value;
  if (!canDecide(approval)) return;

  pendingApproval.value = null;
  setPhase(state.value, "running");

  try {
    await call(ENDPOINTS.resolveApproval, {
      stream_id: conversationId.value,
      request_id: approval.request_id || "",
      approved: approved ? "true" : "false",
    });
  } catch (error) {
    state.value.error = serverMessage(error) || "The decision could not be recorded.";
  }
}

// --------------------------------------------------------------------------
// Stopping.
//
// A client action: the worker keeps running and the answer is still parked, so
// the turn is not lost — it is merely no longer waited for.
// --------------------------------------------------------------------------

function stop() {
  if (!canStop(state.value)) return;
  unsubscribe.value();
  setPhase(state.value, STOPPED);
  state.value.notice = noticeText("stopped");
}

// --------------------------------------------------------------------------
// Lifecycle.
// --------------------------------------------------------------------------

onMounted(() => {
  // The socket is site-wide, so the subscription filters on the stream id —
  // that is what keeps one reader's progress out of another reader's browser.
  if (conversationId.value) {
    unsubscribe.value = subscribe(conversationId.value, onProgress);
  }
});

onBeforeUnmount(() => {
  unsubscribe.value();
});

// Exposed for the launcher, which mounts this panel on the first click.
defineExpose({ state, send, stop, conversationId });
</script>

<template>
  <div class="albanna-ai-chat-panel" :data-phase="state.phase">
    <header class="albanna-ai-chat-panel__head">
      <span class="albanna-ai-chat-panel__status">{{ statusText }}</span>
      <span v-if="state.activity" class="albanna-ai-chat-panel__activity">{{ state.activity }}</span>
    </header>

    <div class="albanna-ai-chat-panel__transcript" role="log" aria-live="polite">
      <div
        v-for="(message, index) in state.messages"
        :key="index"
        class="albanna-ai-chat-turn"
        :class="`albanna-ai-chat-turn--${message.role}`"
      >
        <div class="albanna-ai-chat-turn__body">{{ message.content }}</div>
        <div v-if="message.pending" class="albanna-ai-chat-turn__pending" aria-label="Waiting" />
        <div v-if="message.tools && message.tools.length" class="albanna-ai-chat-turn__tools">
          {{ toolSummary(message) }}
        </div>
      </div>
    </div>

    <!-- A question is a choice the assistant cannot make. -->
    <div v-if="pendingQuestion && canAnswer(pendingQuestion)" class="albanna-ai-chat-card">
      <p class="albanna-ai-chat-card__question">{{ pendingQuestion.question }}</p>
      <button
        v-for="option in pendingQuestion.options"
        :key="option.value"
        class="albanna-ai-chat-card__option"
        @click="answerQuestion(option)"
      >
        {{ option.label }}
      </button>
    </div>

    <!-- An approval is a decision about a write. -->
    <div v-if="pendingApproval && canDecide(pendingApproval)" class="albanna-ai-chat-card">
      <p class="albanna-ai-chat-card__question">
        {{ pendingApproval.name }} — approve this change?
      </p>
      <p v-if="isDestructiveTool(pendingApproval.name)" class="albanna-ai-chat-card__warning">
        {{ destructiveConsequence(pendingApproval.name) }}
      </p>
      <p class="albanna-ai-chat-card__window">
        {{ remainingSeconds(pendingApproval) }}s left to decide
      </p>
      <button class="albanna-ai-chat-card__option" @click="resolveApproval(true)">Approve</button>
      <button class="albanna-ai-chat-card__option" @click="resolveApproval(false)">Refuse</button>
    </div>

    <div v-if="state.error" class="albanna-ai-chat-panel__error" role="alert">
      {{ state.error }}
    </div>
    <div v-else-if="state.notice" class="albanna-ai-chat-panel__notice">
      {{ state.notice }}
    </div>

    <form class="albanna-ai-chat-composer" @submit.prevent="send">
      <textarea
        v-model="draft"
        class="albanna-ai-chat-composer__input"
        rows="2"
        placeholder="Ask about your data…"
        @input="onDraftInput"
      />
      <div class="albanna-ai-chat-composer__actions">
        <span v-if="composerProblem" class="albanna-ai-chat-composer__problem">
          {{ composerProblem }}
        </span>
        <button v-if="busy && !waiting" type="button" @click="stop">Stop</button>
        <button type="submit" :disabled="busy">Ask</button>
      </div>
    </form>
  </div>
</template>
