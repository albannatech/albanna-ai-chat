"""Background jobs that never inherit privileges.

A background job has no Frappe session.  It runs as a service principal, or as
whatever user was stored alongside it — and either way it is *not* the person
who asked.  That single fact is what makes naive background work dangerous:
extract a document, classify a ticket, embed a record, and the write lands with
rights the requester never held.

So a job carries a **snapshot**: what the caller could do, captured at enqueue
time, and nothing more.  The job runs as a principal with no independent
rights and may write only what the snapshot permits.  If the person who
uploaded the file could not create the target DocType, the job cannot either —
it fails, and it says so.

Why a snapshot and not the user
-------------------------------
Storing the user and re-reading their permissions at job time is the obvious
approach and it is wrong twice over.  Permissions may have changed between
enqueue and run, so the job would act on rights the caller no longer holds; and
a role granted *after* the request would silently widen what a queued job may
do.  A snapshot answers both: it is what was true when the person asked, which
is the only thing they actually authorised.

The prohibition this module exists to make enforceable
------------------------------------------------------
``validate``, ``on_submit``, ``after_insert`` and ``on_update`` all run inside
a document's transaction.  A model call in any of them makes a third-party API
a dependency of every save on the site: a slow provider makes every write slow,
and a down provider makes every write **fail**, because a hook that raises
rolls back.  Three of the five reference extensions specified exactly that.

The core therefore owns the provider layer and the queue.  An extension asks
the core to enqueue work; it never calls a provider from a hook, because it has
no provider to call.  :data:`PROVIDER_MODULES` is the list the validator
refuses, and :func:`hook_prohibition_problem` is the sentence it refuses with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from albanna_ai_chat.core.tools import WRITE

#: An ``import x`` or ``from x`` line, capturing the dotted name it names.
#: Anchored so a mention inside a string or a comment is not read as an import.
_IMPORT_LINE = re.compile(r"^(?:import|from)\s+([A-Za-z_][A-Za-z0-9_.]*)")

#: The six Frappe permissions a write can be authorised against.  The same
#: vocabulary :mod:`albanna_ai_chat.core.toolset` uses, because a snapshot that
#: spoke a different language would be a snapshot the reach check could not
#: read.
PERMISSIONS = ("create", "write", "submit", "cancel", "amend", "delete")

#: Modules an extension may not import.  The core owns the provider layer; an
#: extension that reaches past it has built a second one, and the second one
#: is the one nobody audited.
PROVIDER_MODULES = (
    "anthropic",
    "openai",
    "ollama",
    "google.generativeai",
    "cohere",
    "mistralai",
    "httpx",
    "requests",
    "urllib.request",
    "aiohttp",
)


class JobProblem(str):
    """A job the core refuses to enqueue.

    A ``str`` subclass so it reads as the sentence it is when it reaches the
    developer whose extension produced it.
    """


@dataclass(frozen=True)
class PrivilegeSnapshot:
    """What one account could do, at the moment they asked.

    Six sets of DocType names, one per permission.  "At least one DocType" is
    the visibility rule from ADR 0008 carried into the async world: a job may
    *attempt* a write the caller could reach somewhere, and whether it may
    reach the *target* is a separate, per-call question the job answers
    against the same snapshot.
    """

    user: str
    roles: tuple[str, ...] = ()
    creatable: frozenset[str] = frozenset()
    writable: frozenset[str] = frozenset()
    submittable: frozenset[str] = frozenset()
    cancellable: frozenset[str] = frozenset()
    amendable: frozenset[str] = frozenset()
    deletable: frozenset[str] = frozenset()

    def reachable(self, permission: str, doctype: str = "") -> bool:
        """Whether this snapshot holds *permission*, optionally on *doctype*.

        With no doctype this is the visibility question — "could they do this
        anywhere".  With one it is the target question.  A job checks the
        second before it writes, because a snapshot that permitted the first
        has not permitted the second.
        """
        sets = {
            "create": self.creatable,
            "write": self.writable,
            "submit": self.submittable,
            "cancel": self.cancellable,
            "amend": self.amendable,
            "delete": self.deletable,
        }
        held = sets.get(permission)
        if held is None:
            return False
        if not doctype:
            return bool(held)
        return doctype in held

    def may_write(self, doctype: str, permission: str = "create") -> bool:
        """Whether a job holding this snapshot may write *doctype*."""
        return self.reachable(permission, doctype)


@dataclass(frozen=True)
class RetryPolicy:
    """How a failed job is retried.

    ``attempts`` counts the *first* try, so 1 means no retry.  The default is
    deliberately small: a job that calls a provider is a job that can be
    rate-limited, and a retry storm against a rate limiter is a way to turn a
    transient failure into a longer one.
    """

    attempts: int = 3
    backoff_seconds: int = 60

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("a retry policy needs at least one attempt")
        if self.backoff_seconds < 0:
            raise ValueError("backoff cannot be negative")


@dataclass(frozen=True)
class JobRequest:
    """One unit of background work, and the snapshot that authorises it.

    ``purpose`` is one line saying why this job exists.  It is recorded with
    the audit row, because an audit that says only "a job ran" cannot answer
    why bytes left the site or why a record changed.
    """

    extension: str
    job: str
    payload: dict = field(default_factory=dict)
    snapshot: PrivilegeSnapshot | None = None
    purpose: str = ""
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    @property
    def key(self) -> str:
        """A stable identity for this job, for idempotency."""
        return f"{self.extension}:{self.job}"


@dataclass(frozen=True)
class JobOutcome:
    """What a job did.

    ``refused`` is distinct from ``failed`` for the same reason a tool refusal
    is: the snapshot said no, which is an answer, not a fault.  A job that
    reports a refusal as a failure teaches the operator to retry something
    that will never succeed.
    """

    ok: bool
    summary: str = ""
    error: str = ""
    refused: bool = False
    #: What the job actually changed, for the audit row.  Empty when it
    #: changed nothing, which is the common case for a read-only job.
    changed: tuple[str, ...] = ()

    @classmethod
    def success(cls, summary: str, changed: tuple[str, ...] = ()) -> "JobOutcome":
        return cls(ok=True, summary=summary, changed=changed)

    @classmethod
    def failure(cls, summary: str, error: str) -> "JobOutcome":
        return cls(ok=False, summary=summary, error=error)

    @classmethod
    def refusal(cls, summary: str, error: str) -> "JobOutcome":
        return cls(ok=False, summary=summary, error=error, refused=True)


def validate_job(request: JobRequest) -> JobProblem | None:
    """Check a job before it is enqueued.

    A job with no snapshot is refused outright — that is the whole rule, and a
    job that ran without one would run as a service principal with the site's
    full rights.  A job with no purpose is refused too, because an
    unaccountable job is one whose audit row says nothing.
    """
    if not request.extension:
        return JobProblem("a job must name the extension that queued it")
    if not request.job:
        return JobProblem("a job must name what it does")
    if request.snapshot is None:
        return JobProblem(
            "a job must carry a privilege snapshot — a job without one runs "
            "with rights nobody authorised"
        )
    if not request.snapshot.user:
        return JobProblem("a snapshot must name the user it was taken from")
    if not request.purpose.strip():
        return JobProblem(
            "a job must say why it exists — an unaccountable job is one whose "
            "audit row explains nothing"
        )
    return None


def hook_prohibition_problem(module_name: str, imported: str) -> JobProblem:
    """The sentence the validator refuses an extension with.

    Named rather than inline so the wording lives in one place and the test
    asserts against it.
    """
    return JobProblem(
        f"extension {module_name!r} imports {imported!r}. The core owns the "
        "provider layer and the queue; an extension asks the core to enqueue "
        "work and never calls a model from a document hook. A hook that calls "
        "a provider makes a third-party API a dependency of every save on the "
        "site — a slow provider makes every write slow and a down provider "
        "makes every write fail."
    )


def provider_imports(source: str) -> list[str]:
    """The provider modules *source* imports, if any.

    A line-based scan rather than an AST walk, deliberately: it runs on an
    extension's source at validation time, where being approximately right
    and cheap beats being exactly right and needing the module to be
    importable first.

    The imported name is matched as a *whole dotted name*, not a substring.
    A substring match refuses ``import openai_extra`` for containing
    ``openai``, which is a false positive that blocks a legitimate import —
    and a guard that cries wolf is a guard operators learn to bypass.
    """
    found: list[str] = []
    for line in str(source or "").splitlines():
        match = _IMPORT_LINE.match(line.strip())
        if not match:
            continue
        root = match.group(1)
        for module in PROVIDER_MODULES:
            if root == module or root.startswith(module + "."):
                if module not in found:
                    found.append(module)
    return found


def snapshot_from_reach(user: str, roles, reach) -> PrivilegeSnapshot:
    """Build a snapshot from a :class:`~albanna_ai_chat.core.toolset.Reach`.

    The one place a snapshot is constructed, so the mapping from reach sets to
    snapshot fields exists once rather than in every caller.
    """
    return PrivilegeSnapshot(
        user=user,
        roles=tuple(roles or ()),
        creatable=frozenset(reach.creatable),
        writable=frozenset(reach.writable),
        submittable=frozenset(reach.submittable),
        cancellable=frozenset(reach.cancellable),
        amendable=frozenset(reach.amendable),
        deletable=frozenset(reach.deletable),
    )


#: The tier a job's writes are checked against.  A job that only reads needs
#: no snapshot at all beyond the user, which is why ``validate_job`` insists on
#: the snapshot rather than on any particular permission being held.
JOB_WRITE_TIER = WRITE
