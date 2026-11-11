# ADR 0021 — The contract is Frappe-free, and the validator is atomic

## Status

Accepted — Layer 0.

## Context

`albanna-ai-chat` is the `frappe-mcp` core. It is built from zero, using two
existing projects as *references only*: `albanna` (a Frappe app with a chat
side-panel and a thirteen-tool manifest) and `erpnext-mcp` (a standalone MCP
server with 451 tools, an entry-point extension mechanism, and a
compensation inventory).

The core must accept extensions from twenty separate repos. An extension
mechanism is a promise that anyone can add tools, and the promise is only
keepable if something checks what is added.

## Decision

**`albanna_ai_chat/core/` may not import Frappe.** The contract — `ToolSpec`,
`ToolRegistry`, the tier vocabulary, `FlowSpec`, `CompensationSpec`, and the
validator — is pure Python and runs under plain `pytest` with no bench, no
database and no worker.

**The validator is atomic.** `validate_module` runs every check, collects
every problem, and absorbs nothing when the list is non-empty.

**The rules are data, not prose.** `FORBIDDEN_PARAM_NAMES` and
`SQL_PARAM_NAMES` are frozensets read by both the validator and the tests, so
the two cannot drift.

## Consequences

**Good**

- The contract is testable without a site, which is the only way a contract
  shared by twenty repos can be tested at all.
- A broken extension fails at boot with every problem named, rather than
  half-loading and presenting as intermittent.
- The forbidden-parameter rules are enforced mechanically. A rule in a
  comment survives until the first person who did not read the comment.

**Bad**

- Handlers cannot live in `core/`, so the contract and the implementation are
  two places that could drift. Closed by a test asserting the two sets are
  equal in both directions — the same test `albanna` uses.
- The validator runs at boot, so a contract violation is a hard failure. This
  is deliberate: a broken contract is a developer bug, and an environment
  problem (a missing optional dependency) is distinguished by `load_module`,
  which warns and skips instead.

## The rules, and where each came from

| Rule | Source |
|---|---|
| No SQL parameter | `albanna` ADR 0005 excluded `run_sql_query` because it bypasses the permission engine |
| No filesystem path | `albanna`'s `read_file` takes a URL or File record name, never a path |
| Tier must be classified | `erpnext-mcp`'s `register_tools` refuses an unclassified tool |
| No collisions | `erpnext-mcp` rejects a tool shadowing a core or other extension tool |
| Atomic absorption | `erpnext-mcp`: "nothing is absorbed when any check fails" |
| Flow ≥ 2 steps | `erpnext-mcp` ships 451 tools and 11 flows; a one-step flow is a costume |
| Write declares compensation | `erpnext-mcp`'s `tool-compensation.json`, test-enforced |
| Writes out of reach are hidden | `albanna`'s `without_writes_out_of_reach` |

## Alternatives considered

**Entry points (`erpnext_mcp_tools` group), copied verbatim.** Rejected. An
entry point is venv-wide, but a Frappe app is site-scoped. Installing an
extension in the bench venv would make its tools appear on *every* site
running the core, including sites without that extension's app — tools
referencing doctypes that do not exist there. Frappe's own hook system gives
the same extensibility with correct scoping for free.

**No validator; trust the extensions.** Rejected. Twenty repos means twenty
authors, and the first one to add a `path` parameter would not have read this
ADR.
