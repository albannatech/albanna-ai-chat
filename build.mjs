/**
 * The frontend build pipeline — the piece that was never written down.
 *
 * `albanna` shipped 1.5 MB of built assets in `public/dist/` with no build
 * config anywhere in the repo: no `package.json`, no bundler, no script. The
 * output was reproducible only on the machine that produced it. This file is
 * that machine, written down.
 *
 * What Frappe actually needs
 * --------------------------
 * `app_include_js = ["albanna-ai-chat.bundle.js"]` is not a path. Frappe
 * resolves it through `bundled_asset()` (frappe/utils/jinja_globals.py), which
 * requires the name to contain `.bundle.` and not start with `/assets`, then
 * looks the name up in `sites/assets/assets.json`. So a build has two jobs:
 *
 *   1. emit `<name>.bundle.<HASH>.<ext>` into the app's `public/dist/`
 *   2. write `<name>.bundle.<ext>` -> `/assets/<app>/dist/...` into assets.json
 *
 * Miss the second and the asset 404s from the site root, the browser logs it,
 * and nothing on the page says so — the feature is simply absent, on every
 * page, for every user, forever. That failure mode is why this script exists
 * as code rather than as a note in a README.
 *
 * The hash is content-addressed: it is computed from the bytes actually
 * emitted, so a rebuild that changes nothing produces the same name and a
 * rebuild that changes anything produces a new one. That is what makes the
 * one-year `max-age` on `/assets/` safe.
 *
 * RTL
 * ---
 * `bundled_asset()` prefixes `rtl_` for CSS when the user's language is
 * right-to-left, and looks *that* up in the merged assets.json +
 * assets-rtl.json. If the entry is missing the lookup falls through to the
 * literal string and the stylesheet 404s — for Arabic users, which is the
 * primary audience. So the RTL bundle is not optional and is emitted every
 * build. The source uses CSS logical properties (`inline-start`, `margin-inline`)
 * so one file serves both directions; a future `rtlcss` pass can replace the
 * copy without changing the contract.
 *
 * Usage
 * -----
 *   node build.mjs              build, and update assets.json
 *   node build.mjs --check      exit 1 if the committed output is stale (CI)
 *   node build.mjs --clean      remove dist/ and the assets.json entries
 */

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, join, basename } from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_NAME = "albanna_ai_chat";
const PUBLIC_DIR = join(HERE, APP_NAME, "public");
const DIST_DIR = join(PUBLIC_DIR, "dist");

/** The bundles this app ships. `css` entries also get an RTL twin. */
const ENTRIES = [
  { name: "albanna-ai-chat", kind: "js", from: "js/albanna-ai-chat.mjs" },
  { name: "albanna-ai-chat", kind: "css", from: "css/albanna-ai-chat.css" },
];

const args = new Set(process.argv.slice(2));
const CHECK_ONLY = args.has("--check");
const CLEAN = args.has("--clean");

// --------------------------------------------------------------------------
// Finding the bench.
//
// The build writes into `sites/assets/assets.json`, which lives at the bench
// root, not in the app. Walking up from the app until `sites/assets` exists
// means the script works from a bench checkout, from a standalone clone, and
// from CI, without a flag.
// --------------------------------------------------------------------------

function findBenchRoot(start = HERE) {
  // An explicit override wins, because a workspace that is not inside the
  // bench (a standalone clone, a CI checkout) still has to build against a
  // bench's sites/assets.
  const override = process.env.FRAPPE_BENCH_ROOT;
  if (override && existsSync(join(override, "sites", "assets"))) {
    return override;
  }

  let dir = start;
  for (let i = 0; i < 8; i += 1) {
    if (existsSync(join(dir, "sites", "assets"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

const BENCH_ROOT = findBenchRoot();
const ASSETS_JSON = BENCH_ROOT
  ? join(BENCH_ROOT, "sites", "assets", "assets.json")
  : null;
const ASSETS_RTL_JSON = BENCH_ROOT
  ? join(BENCH_ROOT, "sites", "assets", "assets-rtl.json")
  : null;

// --------------------------------------------------------------------------
// Hashing.
//
// Eight uppercase alphanumerics, matching the shape `albanna`'s committed
// assets used. The alphabet is unambiguous — no `0/O` or `1/I` — because a
// hash a human has to read out loud is a hash that gets mistyped.
// --------------------------------------------------------------------------

const HASH_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";

function contentHash(buffer) {
  const digest = createHash("sha256").update(buffer).digest();
  let out = "";
  for (let i = 0; i < 8; i += 1) {
    out += HASH_ALPHABET[digest[i] % HASH_ALPHABET.length];
  }
  return out;
}

function bundleName(entry, hash) {
  return `${entry.name}.bundle.${hash}.${entry.kind}`;
}

function assetUrl(entry, hash) {
  return `/assets/${APP_NAME}/dist/${entry.kind === "js" ? "js" : "css"}/${bundleName(entry, hash)}`;
}

// --------------------------------------------------------------------------
// Reading and writing assets.json.
//
// The file is shared by every app on the bench, so it is read, merged and
// written back rather than replaced. A build that clobbers another app's
// entries breaks that app's Desk, and the failure looks like nothing to do
// with this one.
// --------------------------------------------------------------------------

async function readJson(path) {
  if (!path || !existsSync(path)) return {};
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    return {};
  }
}

async function writeJson(path, value) {
  if (!path) return;
  await mkdir(dirname(path), { recursive: true });
  const body = `${JSON.stringify(value, null, 2)}\n`;
  await writeFile(path, body);
}

/** Remove every previously emitted bundle for one entry name. */
async function clearStale(entry) {
  const dir = join(DIST_DIR, entry.kind === "js" ? "js" : "css");
  if (!existsSync(dir)) return;
  const prefix = `${entry.name}.bundle.`;
  for (const file of await readdir(dir)) {
    if (file.startsWith(prefix)) {
      await rm(join(dir, file), { force: true });
    }
  }
}

// --------------------------------------------------------------------------
// The build.
// --------------------------------------------------------------------------

async function buildOne(entry) {
  const source = join(PUBLIC_DIR, entry.from);
  if (!existsSync(source)) {
    throw new Error(`missing entry point: ${entry.from}`);
  }

  const outdir = join(DIST_DIR, entry.kind === "js" ? "js" : "css");
  await mkdir(outdir, { recursive: true });

  const result = await esbuild.build({
    entryPoints: [source],
    bundle: true,
    outdir,
    entryNames: "[name]", // hashed by hand below, so the name is exact
    loader: entry.kind === "css" ? { ".css": "css" } : undefined,
    minify: !args.has("--no-minify"),
    sourcemap: true,
    target: ["es2020"],
    format: "esm",
    write: false,
    logLevel: "silent",
  });

  // esbuild appends the extension to `entryNames: "[name]"`, so the emitted
  // file is `albanna-ai-chat.js` / `.css`. Match on the basename rather than
  // a suffix, so a future entry name containing a dot cannot break the lookup.
  const wanted = `${entry.name}.${entry.kind}`;
  const file = result.outputFiles.find(
    (f) => basename(f.path) === wanted && !f.path.endsWith(".map"),
  );
  if (!file) {
    const seen = result.outputFiles.map((f) => basename(f.path)).join(", ");
    throw new Error(`esbuild produced no ${wanted} (got: ${seen || "nothing"})`);
  }

  const hash = contentHash(file.contents);
  const finalName = bundleName(entry, hash);
  const finalPath = join(outdir, finalName);

  await clearStale(entry);
  await writeFile(finalPath, file.contents);

  const map = result.outputFiles.find((f) => f.path.endsWith(`/${entry.name}.map`));
  if (map) {
    await writeFile(`${finalPath}.map`, map.contents);
  }

  return { entry, hash, finalName, finalPath };
}

async function main() {
  if (CLEAN) {
    await rm(DIST_DIR, { recursive: true, force: true });
    for (const path of [ASSETS_JSON, ASSETS_RTL_JSON]) {
      if (!path || !existsSync(path)) continue;
      const json = await readJson(path);
      let changed = false;
      for (const key of Object.keys(json)) {
        if (json[key]?.includes(`/assets/${APP_NAME}/`)) {
          delete json[key];
          changed = true;
        }
      }
      if (changed) await writeJson(path, json);
    }
    console.log(`[build] cleaned ${APP_NAME} dist and assets.json entries`);
    return;
  }

  if (!BENCH_ROOT) {
    // Not fatal. The bundles are still worth emitting — a standalone clone
    // or a CI job can build and inspect them — but assets.json cannot be
    // updated, and an asset Frappe cannot resolve is an asset that does not
    // exist, so this says so loudly rather than exiting quietly.
    console.warn(
      "[build] no bench found (no sites/assets above this directory, and " +
        "FRAPPE_BENCH_ROOT unset). Bundles emitted; assets.json NOT updated.",
    );
  }

  const built = [];
  for (const entry of ENTRIES) {
    built.push(await buildOne(entry));
  }

  // The RTL twin: same bytes, separate name, registered under assets-rtl.json.
  // See the module docstring for why this is not optional.
  const css = built.find((b) => b.entry.kind === "css");
  let rtlHash = null;
  if (css) {
    const rtlName = `rtl_${css.finalName}`;
    const rtlPath = join(DIST_DIR, "css", rtlName);
    await writeFile(rtlPath, await readFile(css.finalPath));
    rtlHash = css.hash;
  }

  // --- assets.json ------------------------------------------------------
  const assets = await readJson(ASSETS_JSON);
  const rtlAssets = await readJson(ASSETS_RTL_JSON);

  for (const { entry, hash } of built) {
    if (entry.kind === "css") continue; // CSS is registered below, with RTL
    assets[`${entry.name}.bundle.${entry.kind}`] = assetUrl(entry, hash);
  }
  if (css) {
    assets["albanna-ai-chat.bundle.css"] = assetUrl(css.entry, css.hash);
  }
  if (rtlHash) {
    rtlAssets["rtl_albanna-ai-chat.bundle.css"] = `/assets/${APP_NAME}/dist/css/rtl_albanna-ai-chat.bundle.${rtlHash}.css`;
  }

  if (CHECK_ONLY) {
    if (!BENCH_ROOT) {
      console.error("[build] --check needs a bench to compare against");
      process.exit(2);
    }
    const expected = JSON.stringify({ assets, rtlAssets }, null, 2);
    const actual = JSON.stringify(
      {
        assets: await readJson(ASSETS_JSON),
        rtlAssets: await readJson(ASSETS_RTL_JSON),
      },
      null,
      2,
    );
    if (expected !== actual) {
      console.error("[build] assets are stale — run `npm run build`");
      process.exit(1);
    }
    console.log("[build] assets are current");
    return;
  }

  if (BENCH_ROOT) {
    await writeJson(ASSETS_JSON, assets);
    await writeJson(ASSETS_RTL_JSON, rtlAssets);
  }

  for (const { entry, finalName } of built) {
    console.log(`[build] ${entry.kind}: ${finalName}`);
  }
  if (rtlHash) console.log(`[build] css (rtl): rtl_albanna-ai-chat.bundle.${rtlHash}.css`);
  if (BENCH_ROOT) {
    console.log(`[build] assets.json updated at ${BENCH_ROOT}/sites/assets/`);
  }
}

main().catch((error) => {
  console.error(`[build] ${error.message}`);
  process.exit(1);
});
