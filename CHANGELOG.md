# Changelog

All notable changes to Albanna AI Chat are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the app uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
