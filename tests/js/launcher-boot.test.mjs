/**
 * Tests for the launcher's pure half — resolving the panel's URL.
 *
 * The failure this is written for is a build that emitted the bundle but
 * never registered it in assets.json: the launcher would inject a script tag
 * pointing at the site's 404 page, the browser would log a syntax error, and
 * nothing on the page would say why the widget was missing.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ALBANNA_PANEL_GLOBAL,
  PANEL_BUNDLE_KEY,
} from "../../albanna_ai_chat/public/js/lib/wire.mjs";
import { panelBundleUrl } from "../../albanna_ai_chat/public/js/albanna-ai-chat.mjs";

describe("panelBundleUrl", () => {
  it("resolves the key the build registers", () => {
    const assets = { [PANEL_BUNDLE_KEY]: "/assets/albanna_ai_chat/dist/js/x.js" };
    assert.equal(panelBundleUrl(assets), "/assets/albanna_ai_chat/dist/js/x.js");
  });

  it("answers null when the build never registered the panel", () => {
    // The caller paints an error naming the command, rather than injecting a
    // script tag that loads the 404 page as JavaScript.
    assert.equal(panelBundleUrl({}), null);
    assert.equal(panelBundleUrl(undefined), null);
    assert.equal(panelBundleUrl(null), null);
  });

  it("answers null for an entry that is not a usable URL", () => {
    assert.equal(panelBundleUrl({ [PANEL_BUNDLE_KEY]: "" }), null);
    assert.equal(panelBundleUrl({ [PANEL_BUNDLE_KEY]: 42 }), null);
  });

  it("uses the key `wire.mjs` names, not one spelled out here", () => {
    // A second spelling of the key is a second spelling that drifts: the
    // build renames it, the launcher keeps looking for the old one, and the
    // panel 404s silently on every page.
    assert.ok(PANEL_BUNDLE_KEY.endsWith(".bundle.js"));
    assert.ok(PANEL_BUNDLE_KEY.startsWith("albanna-ai-chat"));
  });

  it("mounts under a global named in wire.mjs", () => {
    // The name is this app's own: two apps on one Desk sharing a global is
    // two apps mounting into each other's panel.
    assert.equal(ALBANNA_PANEL_GLOBAL, "albannaAiChatPanel");
  });
});
