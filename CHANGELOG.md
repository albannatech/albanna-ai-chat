# Changelog

All notable changes to Albanna AI Chat are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the app uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
