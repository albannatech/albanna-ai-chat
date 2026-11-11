# Albanna AI Chat

**The `frappe-mcp` core.** A Frappe app that provides the chat runtime, the
file tools, and the seam every other `-mcp` repo plugs into.

> **Status: Layers 0, 1 and 2 complete.**
> The contract is frozen, the chat runtime's state machine is decided and
> tested, and the core's three file tools are declared *and implemented* —
> they read, create and edit File records through Frappe's permission engine,
> with the site and actor guards that make "Frappe decides" true. 230 tests,
> plain `pytest`, no bench required. The provider adapters, the turn loop's
> Frappe service, the Settings activation surface and the frontend port are
> not built yet. See *Roadmap* below.

---

## What this is

One core, minimal on purpose:

| Responsibility | What it means |
|---|---|
| **Chat** | Conversations, messages, providers, streaming, the turn loop |
| **File tools** | `read_file`, `write_file`, `edit_file` — the entire built-in tool surface |
| **The extension seam** | The contract, the validator, and the registry every `-mcp` repo contributes to |

Everything else — domain tools, permissions, configurations, agents, prompts —
arrives as an **extension**. Install `healthcare-mcp` and the chat gains a
healthcare agent that knows about patients and carries its own rules. Install
nothing and you have a chat that can read and write files.

## The architecture in one paragraph

The core owns the **contract** and the **authority**; extensions own their
**tools** and their **content**. An extension declares what it can do; the
core decides who may do it, by asking Frappe. There is no extension-level
override, because there is no switch. That split is the whole security model,
and it is why `core/` may not import Frappe — a contract that can call Frappe
cannot be tested without a site.

## The contract

`albanna_ai_chat/core/` is Frappe-free and runs under plain `pytest`.

- **`tools.py`** — `ToolSpec`, `ToolRegistry`, the closed tier vocabulary
  (`read`, `write`), and the two forbidden-parameter rules as *data*.
- **`file_tools.py`** — the core's entire built-in surface: `read_file`,
  `write_file`, `edit_file`, each with its tier, its `write_permission`, and
  its compensation declaration.
- **`flow.py`** — `FlowSpec`, `FlowStep`, `CompensationSpec`. A flow is
  several tool calls with a transaction of its own; single-step is the
  default and a flow must declare at least two steps.
- **`port.py`** — `ToolBackend`, `ToolContext`, `ToolResult`, `Principal`,
  `PermissionChecker`. How a tool is *called*, without saying what happens
  next.
- **`validate.py`** — the atomic extension validator. Every check runs, every
  problem is reported, and nothing is absorbed when any check fails.

### Single-step is the default, and compensation is not optional

A write tool does **not** have to be a flow. It declares how it is undone in
one of exactly two places — on the spec itself, or through its flow — and
declaring both is refused, because two answers to "how is this undone" is the
same as none. `erpnext-mcp` ships 451 tools and eleven flows; a rule that
turns all of them into flows is not that ratio.

`write_file` is the honest case: the core ships no `delete_file`, so its
compensation is `none` *with a reason*. `edit_file` is `reverse` — swapping
`old_string` and `new_string` restores the file exactly.

### The rules that are not negotiable

Each is asserted in `tests/test_contract.py`, because a rule that lives only
in a docstring survives until the first person who did not read it.

1. **No SQL-shaped parameter.** A raw query bypasses Frappe's permission
   engine completely, including User Permissions and every row-level rule
   built on them.
2. **No filesystem-path parameter.** File tools take a URL or a File record
   *name*, resolved through Frappe. A `path` parameter is a host-level
   read/write primitive.
3. **Every tool is tier-classified**, and the spec's tier and the module's
   `TIERS` entry must agree.
4. **No collisions.** An extension may not shadow a core tool or another
   extension's tool.
5. **Atomic absorption.** A partially-absorbed extension reads as *"the tool
   sometimes works"*, which is the hardest bug to reproduce.
6. **A flow has at least two steps.** A one-step flow is a tool wearing a
   costume.
7. **Every write declares its compensation** — a mechanism from a closed set,
   or `none` *with a reason*. An irreversible action must say why.
8. **Writes out of reach are hidden, not refused.** A caller who may create
   nothing is not told the tool exists.

## Provenance

Every tool records where it came from — `"core"`, or the installing app's
name. That is what makes an uninstall exact: removing an extension removes
its tools and only its tools.

## Roadmap

| Layer | Status |
|---|---|
| **0 — Contract** | ✅ Frozen and tested |
| **1 — Chat runtime** | ✅ State machine, message model, doctypes, permissions, services |
| **2 — File tools** | ✅ Specs, port, Frappe handlers and guards — implemented and tested |
| **3 — Extension seam** | ✅ Hook, atomic validation, activation, Settings API, version compatibility |
| **4 — Frontend port** | pure logic reused, contract adapters rewritten, build pipeline recovered |
| **5 — `healthcare-mcp`** | the reference extension, with one real transactional flow |

### How a file tool actually runs

`albanna_ai_chat/tools/files.py` is the only module in the app that imports
Frappe. A call passes three gates before anything is read or written:

1. **Arguments** are validated against the spec's schema, so a malformed call
   never reaches the site.
2. **The site** is asserted — a bench serves several sites from one process,
   and a turn bound to one site must not read another's files.
3. **The actor** is asserted — `frappe.set_user()` puts the call in the
   session of the person who asked, because Frappe applies that user's roles
   and User Permissions to every read and write. A turn running in a
   background worker has no session user of its own, and running it as
   Administrator would let the assistant see everything its caller cannot.

Then the reference is resolved — a URL or a File record *name*, never a path —
and the on-disk location comes from `File.get_full_path()`, which is Frappe's
answer and never assembled from anything the model supplied.

## Conventions

- `core/` may not import Frappe.
- Handlers live behind a port; the contract never calls them.
- Every destructive action declares how it is undone.
- Extensions declare intent; the core decides.

## License

MIT
