# Changelog

All notable changes to Albanna AI Chat are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the app uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

**Layer 4a — the frontend build pipeline, written down.**

`albanna` shipped 1.5 MB of built assets in `public/dist/` with no build
config anywhere in the repository: no `package.json`, no bundler, no script,
and `public/dist/` gitignored. The output was reproducible only on the machine
that produced it. This is that machine, as code.

- `build.mjs` — bundles the Desk entry points with esbuild, emits
  `<name>.bundle.<HASH>.<ext>` into `public/dist/`, clears the previous
  bundle for that entry, and writes the name → `/assets/...` mapping into
  `sites/assets/assets.json`. The hash is computed from the bytes actually
  emitted, so it is content-addressed and a no-change rebuild is a no-change
  name.
- `package.json` — esbuild as a declared devDependency, with `build`,
  `build:check` and `clean` scripts.
- The RTL twin. `bundled_asset()` prefixes `rtl_` for right-to-left users and
  looks that up in the merged `assets.json` + `assets-rtl.json`; a missing
  entry falls through to the literal string and the stylesheet 404s — for
  Arabic users, who are the primary audience. The build emits and registers
  the twin every run, and the stylesheet is written with CSS *logical*
  properties so one file serves both directions.
- `tests/test_assets_contract.py` — asserts the two rules whose failure is
  invisible: every declared asset carries `.bundle.` and does not start with
  `/assets`, and every name in `hooks.py` has a matching entry in `build.mjs`.
  A bundle the build does not produce is a name that resolves to nothing, and
  nothing else in the repo notices when the two lists drift.
- `albanna_ai_chat/public/js/albanna-ai-chat.mjs` and
  `albanna_ai_chat/public/css/albanna-ai-chat.css` — minimal entry points that
  prove the pipeline end to end. The real widget is ported behind them in 4b.

### Changed

- `build.mjs` no longer exits when no bench is found. It emits the bundles and
  warns that `assets.json` was not updated, because a standalone clone or a CI
  job can still build and inspect them — and an asset Frappe cannot resolve is
  an asset that does not exist, so the warning says so rather than passing
  quietly.
- `.gitignore` now covers `node_modules/` and `package-lock.json`.

### Notes

- Verified end to end: the emitted names resolve to real files under the
  `sites/assets/<app>` symlink that `bench setup` creates, the rebuild is
  idempotent, and `--check` exits 1 when the output is stale.
- The bench's `assets.json` was restored after verification. The app is not
  installed on this bench, so entries for it would have been inert pollution
  in a file every app on the bench shares.

---

**Layer 3 — the extension seam, consolidated onto one implementation.**

Two parallel implementations of the extension layer had accumulated (one from
each of two sessions). They are now one, keeping the union of what each had:

- `core/extension_state.py` — `ExtensionStatus` with five states, including
  `INSTALLED_INCOMPATIBLE` and `UPDATE_AVAILABLE`, and a small honest semver
  (`parse_version`, `compare_versions`, `version_satisfies`). An extension
  declares `REQUIRES_CORE` and is refused activation when the running core
  does not satisfy it — a visible settings row rather than a runtime surprise.
- `core/toolset.py` — `Reach`, `visible_tools()`, `without_source()`,
  `tools_from()`. The visibility rule in one place: a write tool appears when
  the caller holds the right somewhere, and the operator's list only ever
  narrows it. Extensions are not a special case.
- `services/extensions.py` — `discover()`, `load_registry()`,
  `live_registry()`, `extension_states()`, `activated_apps()`, `core_version()`.
- `api/extensions.py` — the Settings surface's whitelisted API:
  `get_report`, `get_tools`, `activate`, `deactivate`, `reload_extensions`.
  `activate` refuses an app that is not installed and names the bench command
  that will install it, because a Settings screen cannot install a Frappe app
  and a button that pretends otherwise will be clicked and then blamed.

### Changed

- `load_registry()` answers *"what is installed and valid"* and
  `live_registry()` answers *"what a turn is offered"*. They are separate
  functions rather than one with a flag, because the safe path has to be the
  obvious one — a loader whose default silently includes unactivated
  extensions is one careless call site away from exposing tools the operator
  never switched on.
- `extension_states()` reports the union of *declared* and *activated* apps,
  not everything installed. A bench carries `frappe`, `erpnext`, `hrms` and a
  dozen other apps that are not extensions and never will be; reporting them
  would bury the two rows an operator came to read.

### Removed

- `core/activation.py`, `extensions.py` and `tests/test_activation.py` — a
  second, thinner implementation of the same rules. A second copy is a second
  truth, and the two would have diverged the first time one was edited.

### Notes

- Redis caching of the loaded surface was considered and **not** added.
  Measured: 1000 re-imports of an already-loaded module cost 0.49 ms, because
  Python's `sys.modules` already makes a repeated import a dict lookup. The
  only work re-done per call is validation, which is cheap and *should* re-run
  — it is the guard. Caching would have added serialization, staleness bugs
  and invalidation to solve a problem that does not exist.
- `parse_tool_names` / `unknown_tool_names` live in `core/tools.py` as pure
  helpers, so the operator's hide-list rule is testable without a doctype.
  Whitespace separates nothing: `read_file edit_file` is one entry that
  matches no tool, which is the same silence as a typo.
- `disabled_tools` was added to `AI Chat Settings`. It narrows the surface
  regardless of which extension a tool came from, so a *core* tool can be
  hidden too.

### Fixed

- `load_registry()` loaded every discovered extension with no activation
  filter, so an installed-but-not-switched-on app's tools would have gone
  live. `live_registry()` now applies activation, and it is the only loader a
  turn may call.
- `extension_states()` initially reported every installed app, including
  `frappe` and `erpnext`.

### Added

**Layer 1 — the chat runtime.**

- `albanna_ai_chat/chat/message.py` — `Role`, `Message`, `ToolCall`, and the
  canonical provider wire form. A `TOOL` message must name the call it
  answers; an assistant message carrying tool calls still carries `content`,
  because a provider that receives `tool_calls` and no `content` key rejects
  the whole request.
- `albanna_ai_chat/chat/turn.py` — `TurnState`/`TurnEvent` as data, the
  legal-transition table, and `next_action()`: the single question the turn
  loop asks. Illegal transitions raise rather than being ignored, because a
  silently-ignored event is how a turn ends up somewhere nobody intended.
- Two guards that live in the pure layer so they cannot be forgotten:
  `MAX_PROVIDER_CALLS` (a turn that never ends ends by exhausting the context
  window) and `MAX_TOOL_CALLS_PER_RESPONSE` (fifty calls in one response is
  fifty writes before anybody looks).
- A waiting turn owns no worker — the property that lets a parked turn free
  its worker and be resumed after a restart. That is why this is a reducer
  and not a call stack.
- Four doctypes: `AI Chat Conversation`, `AI Chat Message`, `AI Chat Settings`
  (Single), `AI Chat Log`. Their Select options mirror `TurnState` and `Role`,
  and `tests/test_doctypes.py` asserts the two cannot drift.
- `permissions.py` — chat history is private to the reader who started it. A
  System Manager is deliberately not exempt from reading content, because
  running the site and reading somebody's chat are different acts.
- `install.py` — creates the `Albanna Chat User` role and the settings row,
  idempotently, so a site restored from a backup repairs itself on the next
  migrate.
- `services/conversation_service.py` — `last_activity` and `message_count`
  are derived and maintained in exactly one place. The title comes from the
  first reader message and never overwrites one the reader has edited.
- `services/retention.py` — prunes chat *logs* by age; conversations are kept
  until the reader deletes them.
- Settings limits may lower the pure layer's ceilings, never raise them.

### Fixed

- A turn parking on approval did not record *which* write it was waiting on,
  so it could not be resumed after a restart. `Turn.apply` now records the
  pending call before entering `AWAITING_APPROVAL`.

## [0.1.0] — 2026-11-11

### Added

**Layer 2 — the file tools are implemented, not just declared.**

- `albanna_ai_chat/core/file_ref.py` — the Frappe-free half of every promise
  the file tools make in their descriptions: `resolve_file_ref` (a URL or a
  File record name, and nothing else), `bare_filename_problem` (a filename,
  never a path), `unique_replace` (exactly once, or nothing changes), and
  `paginate` (a long file comes back in parts and says where the next starts).
- `albanna_ai_chat/tools/files.py` — `FileToolBackend`, the Frappe
  implementation behind the port. It resolves a reference to a `File` record,
  asks Frappe whether the caller may touch it, and reads or writes the bytes
  through Frappe's own file manager.
- Three guards that run before any file is touched: arguments are validated
  against the spec's schema; the site is asserted, because a bench serves
  several sites from one process; and the actor is asserted with
  `frappe.set_user()`, because Frappe applies the session user's permissions
  to every read and write and a turn in a background worker has no session
  user of its own.
- `tests/test_file_ref.py` and `tests/test_file_backend.py` — 76 new tests.
  The backend tests install a stub `frappe` into `sys.modules`, so the
  security-critical half is verified without a bench.

### Fixed

- A URL beginning with a real prefix but then climbing out of it —
  `/private/files/../../etc/passwd` — was accepted as a file reference. The
  prefix is not a permission; traversal is now checked for URLs as well as
  bare names.

### Notes

- The on-disk path is never the model's. It comes from
  `File.get_full_path()`, which is Frappe's answer derived from the record.
- PDF text extraction is attempted when `pypdf` is installed and refused with
  an actionable sentence when it is not, rather than half-implemented.
