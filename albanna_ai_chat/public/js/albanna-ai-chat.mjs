/**
 * The Desk entry point — the launcher.
 *
 * Stage 4a established the build pipeline. Stage 4b ports the pure layer
 * behind it: the formatting, the refusal unwrapping, the render coalescing
 * and the turn state machine now live in `lib/`, are tested under plain
 * node, and are imported here so the bundle actually contains them.
 *
 * Stage 4c adds the two remaining pure modules: the access decision the
 * launcher and the form button must share, and the attachment rules checked
 * before the bytes leave the browser.
 *
 * Stage 4d adds the transport — the socket fast path with the poll as the
 * delivery guarantee. Its poll ramp is pure and tested under plain node; its
 * two `window.frappe` calls are the only contract-bound parts, and they read
 * their event name and endpoints from `lib/wire.mjs` rather than spelling them
 * out.
 *
 * Stage 4f adds the reader's language: `lib/i18n.mjs` is the one guard that
 * keeps a module with a sentence in it importable under plain node, and
 * `lib/tool-labels.mjs` / `lib/notices.mjs` are the sentences themselves. The
 * label table is rewritten for this core's three file tools rather than ported
 * from `albanna`'s thirteen, and an extension declares its own labels through
 * `EXTENSION_LABELS` rather than through a hardcoded list.
 *
 * Stage 4g adds the three modules the panel cannot be built without: the
 * question card, the composer's rules, and the write-safety list. The
 * destructive list is read from this core's own contract rather than guessed —
 * `edit_file` declares `mechanism="reverse"` so it is *not* warned about, and
 * `write_file` declares `mechanism="none"` so it is — and a Python test asserts
 * the frontend's set and the contract's irreversible set cannot drift.
 *
 * Stage 4i makes the launcher *real*: it asks the server whether the widget
 * should render, places a button and an empty panel on the page, and fetches
 * the panel bundle on the first click — resolving the hashed URL from
 * `frappe.boot.assets_json` and injecting a classic `<script>`, which is
 * `albanna`'s own pattern. What is left in this file is state, wiring and DOM;
 * the rules live in `lib/`.
 *
 * Note what is *not* here: no `frappe` import, no socket connection, no tool
 * names. Those are the contract-bound adapters, and they are rewritten against
 * this core's own contract rather than copied from `albanna`'s — see
 * `lib/wire.mjs`, which is the one place the frontend's assumptions about the
 * server live.
 */

import {
  ACCESS_EVENT,
  ACCESS_GLOBAL,
  chatAllowed,
  onAccessDecision,
  publishAccess,
} from "./lib/access.mjs";
import {
  REFUSED_SIZE,
  REFUSED_TYPE,
  checkAttachment,
  makeAttachment,
  storeAll,
  turnAttachments,
} from "./lib/attachments.mjs";
import { translate } from "./lib/i18n.mjs";
import { noticeKeys, noticeText } from "./lib/notices.mjs";
import {
  PENDING,
  ANSWERED,
  answerMessage,
  canAnswer,
  questionCard,
} from "./lib/question.mjs";
import {
  DEFAULT_QUESTION_LENGTH,
  REASONS,
  refusalText,
  submitDecision,
} from "./lib/submit.mjs";
import {
  DESTRUCTIVE_TOOLS,
  declareDestructive,
  destructiveConsequence,
  diffValue,
  isDestructiveTool,
} from "./lib/write-safety.mjs";
import {
  describeTool,
  statusLabel,
  toolAction,
  toolLabel,
  toolSummary,
} from "./lib/tool-labels.mjs";
import {
  ALBANNA_PANEL_GLOBAL,
  APP_NAME,
  ENDPOINTS,
  PANEL_BUNDLE_KEY,
  ROOT_ID,
  STREAM_EVENT,
} from "./lib/wire.mjs";
import { STATES, initialState } from "./lib/turn-state.mjs";
import {
  FIRST_POLL_MS,
  STATUS_POLL_MAX_MS,
  call,
  nextPollDelay,
  runTurn,
  subscribe,
  waitForTurn,
} from "./lib/transport.mjs";

export {
  APP_NAME,
  STREAM_EVENT,
  STATES,
  initialState,
  ACCESS_EVENT,
  ACCESS_GLOBAL,
  chatAllowed,
  onAccessDecision,
  publishAccess,
  REFUSED_SIZE,
  REFUSED_TYPE,
  checkAttachment,
  makeAttachment,
  storeAll,
  turnAttachments,
  translate,
  noticeKeys,
  noticeText,
  PENDING,
  ANSWERED,
  answerMessage,
  canAnswer,
  questionCard,
  DEFAULT_QUESTION_LENGTH,
  REASONS,
  refusalText,
  submitDecision,
  DESTRUCTIVE_TOOLS,
  declareDestructive,
  destructiveConsequence,
  diffValue,
  isDestructiveTool,
  describeTool,
  statusLabel,
  toolAction,
  toolLabel,
  toolSummary,
  FIRST_POLL_MS,
  STATUS_POLL_MAX_MS,
  call,
  nextPollDelay,
  runTurn,
  subscribe,
  waitForTurn,
};

export const VERSION = "0.1.0";

// --------------------------------------------------------------------------
// Resolving the panel's URL.
//
// The panel is fetched on demand, and the URL it is fetched from is the one
// the build wrote into assets.json. A URL spelled out here would be right
// until the first rebuild changed the hash — and then the panel would 404 on
// every page, silently, forever. So it is read from boot, which Frappe
// refreshes with the assets map on every page load.
// --------------------------------------------------------------------------

/**
 * The panel's URL, from the assets map Frappe hands the page.
 *
 * Pure, and tested under plain node: the failure it is written for is a build
 * that emitted the bundle but never registered it, which is a panel that
 * 404s silently. A missing entry answers `null` and the caller paints an
 * error naming the command that fixes it — rather than injecting a script
 * tag that loads the site's 404 page as JavaScript.
 *
 * @param {object} assets the `frappe.boot.assets_json` map
 * @returns {string|null} the bundle's URL, or null when it is not registered
 */
export function panelBundleUrl(assets) {
  const map = assets && typeof assets === "object" ? assets : {};
  const url = map[PANEL_BUNDLE_KEY];
  return typeof url === "string" && url ? url : null;
}

// --------------------------------------------------------------------------
// The boot.
//
// This is the DOM-coupled half, and it is the reason the pure half exists:
// everything above `boot` is testable without a browser, and what is here is
// only placement and wiring.
// --------------------------------------------------------------------------

function paintBootError(el) {
  el.innerHTML = "";
  const box = document.createElement("div");
  box.className = "albanna-ai-chat-boot-error";
  box.setAttribute("role", "alert");
  box.textContent = translate(
    "The assistant panel could not load. Run: bench build --app albanna_ai_chat",
  );
  el.appendChild(box);
}

/** Inject the panel bundle once, then mount it into *root*. */
function loadPanel(root) {
  const already = window[ALBANNA_PANEL_GLOBAL];
  if (already && typeof already.mount === "function") {
    already.mount(root);
    return;
  }

  const url = panelBundleUrl(
    (window.frappe && window.frappe.boot && window.frappe.boot.assets_json) || {},
  );
  if (!url) {
    // A missing registration is a build that never ran, not a network
    // failure — so the message names the command rather than a retry button.
    paintBootError(root);
    return;
  }

  const script = document.createElement("script");
  script.src = url;
  script.onload = () => {
    const panel = window[ALBANNA_PANEL_GLOBAL];
    if (panel && typeof panel.mount === "function") {
      panel.mount(root);
    } else {
      paintBootError(root);
    }
  };
  script.onerror = () => paintBootError(root);
  document.head.appendChild(script);
}

/** Ask the server whether the widget should exist, and place it if so. */
export async function boot() {
  if (typeof document === "undefined" || !document.body) return;
  if (typeof window.frappe === "undefined") return;
  if (document.getElementById(ROOT_ID)) return;

  const root = document.createElement("div");
  root.id = ROOT_ID;
  root.className = "albanna-ai-chat-panel";

  let config = null;
  try {
    const result = await window.frappe.call({
      method: ENDPOINTS.access,
      args: {},
      silent: true,
    });
    config = result && typeof result.message === "object" ? result.message : null;
  } catch (error) {
    // The answer did not arrive, so there is no widget — and the bundles
    // that wait for one are told so, rather than left waiting for a
    // decision that has already been made.
    publishAccess(null, { window, document });
    if (window.console && window.console.warn) {
      window.console.warn("albanna-ai-chat: unavailable", error);
    }
    return;
  }

  // Published before the early return below: "no widget" is an answer too.
  publishAccess(config, { window, document });

  if (!config || config.visible !== true) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "albanna-ai-chat-launcher";
  button.textContent = translate("Ask Albanna AI");
  button.setAttribute("aria-expanded", "false");

  button.addEventListener("click", () => {
    const open = root.getAttribute("data-open") === "true";
    if (!open && !window[ALBANNA_PANEL_GLOBAL]) {
      // The first click pays for the framework. The attribute is set by the
      // panel's own mount, so the button only records the intent.
      button.setAttribute("aria-expanded", "true");
      loadPanel(root);
      return;
    }
    root.setAttribute("data-open", open ? "false" : "true");
    button.setAttribute("aria-expanded", open ? "false" : "true");
  });

  document.body.appendChild(root);
  document.body.appendChild(button);
}

// The bundle is included on every Desk page. Under plain node — where the
// tests import the pure half — there is no document, so the guard is what
// makes the same file safe in both places.
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      boot().catch((error) => {
        if (window.console && window.console.warn) {
          window.console.warn("albanna-ai-chat: boot failed", error);
        }
      });
    });
  } else {
    boot().catch((error) => {
      if (window.console && window.console.warn) {
        window.console.warn("albanna-ai-chat: boot failed", error);
      }
    });
  }
}
