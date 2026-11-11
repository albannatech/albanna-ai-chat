# ADR 0022 — The four primitives an extension cannot supply itself

## Status

Accepted — Layer 7.

## Context

Five reference extensions were specified, and four of them specified the same
defect in different clothes:

- **Semantic Search** — embed on `after_insert`/`on_update`
- **Auto-classification** — classify on `validate`/`on_submit`
- **Document Intelligence** — extract in a `frappe.enqueue` background job
- **Content Generation** — interpolate record text straight into a prompt

Each one puts a model call, or a model's output, somewhere it does not belong.
The first two make a third-party API a dependency of every document save on the
site: a slow provider makes every write slow, and a down provider makes every
write **fail**, because a hook that raises rolls back the transaction. The
third runs a write with privileges the requester never held. The fourth hands
any user who can edit a record the ability to write instructions a model will
read as instructions.

The instinct is to fix each extension. That is the wrong unit: these are four
instances of one missing primitive, and fixing them one at a time means the
sixteenth extension rediscovers the defect.

## Decision

**The core supplies four primitives, and an extension may not build its own.**

### 1. The async primitive, and a prohibition on model calls in hooks

`core/jobs.py` defines `PrivilegeSnapshot` — what the caller could do, captured
at enqueue time — and `JobRequest`, which is refused by `validate_job` unless it
carries one. `services/jobs.py` runs the job as a dedicated principal with no
roles of its own and checks the snapshot before every write, raising rather
than returning a bool.

The prohibition is enforced, not advised: `core/validate.py` scans an
extension's source and refuses the whole module when it imports a provider.
The core owns the provider layer, so an extension has no provider to call from
a hook — it asks the core to enqueue work.

### 2. The binary file port

`core/file_bytes.py` and `tools/file_bytes.py`. A separate channel from the
three text tools, never a tool the model can see, bounded by a ceiling the
caller names and enforced *during* the read rather than after it. Permission is
checked before a single byte is fetched, and a refusal returns no size and no
content — a refusal that reported the file's size would leak that the file
exists.

### 3. The draft-then-promote gate

`core/proposal.py`. A model's output is a `Proposal`: a draft naming what it
would change, how confident it is, and which model and prompt produced it.
Setting the field on the real document is a separate, permissioned, audited
action. The policy fails **closed** — no policy means review, no confidence
means review, and a field the operator marked consequential is never
auto-accepted.

### 4. Restricted templates and the data fence

`core/template.py`. A prompt template accepts exactly one construct,
`{fieldname}`, validated when the operator saves it. Every record value is
fenced with a standing instruction before it is substituted, so a record field
can never arrive in a prompt as bare prose.

## Consequences

**An extension that cannot be checked is refused, not trusted.** All four
primitives are validated at load time and atomically — nothing is absorbed when
any check fails, because a half-loaded extension reads as "the tool sometimes
works".

**The residual risks are named rather than hidden.** The data fence does not
eliminate prompt injection; nothing does. It moves the risk from certain to
documented-and-mitigated. The vector index is a recall optimisation and never
an authorisation boundary. Both statements belong in the extension's own ADR,
not in a comment.

**The cost is a narrower extension surface.** An extension cannot pick its own
provider, cannot call a model from a hook, cannot write a live field in one
step, and cannot interpolate a record raw. Every one of those is a capability
somebody will ask for, and every one of them is the defect the primitive
exists to prevent.

## Alternatives considered

**Fix each extension as it is written.** Rejected: it makes the fix a
convention, and a convention is what the sixteenth extension breaks.

**Let extensions declare their own permission rules.** Rejected: it inverts the
authority model. `albanna`'s ADR 0008 is that the core decides and Frappe
answers; an extension that decides for itself has granted itself whatever it
declared.

**Make the binary read a fourth file tool.** Rejected: a tool is something the
model may ask for, with model-authored parameters. A port is something the code
asks for with the caller's identity established. Folding them together puts a
binary-read primitive in front of the model.
