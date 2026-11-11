"""The Frappe half of the async primitive.

:mod:`albanna_ai_chat.core.jobs` states the rules; this module keeps them.  It
takes a snapshot at enqueue time, hands the job to Frappe's queue, and runs it
as a principal with no independent rights — checking the snapshot before every
write rather than trusting the queue to have preserved anything.

The one thing this module will not do
--------------------------------------
It will not let a job write something the snapshot does not permit.  Not
"probably will not" — the check is in :meth:`JobRunner.assert_may_write`, which
a handler calls before it touches a document, and which raises rather than
returning a bool.  A handler that skips the check is a handler that has opted
out of the security model, and the opt-out should be loud.
"""

from __future__ import annotations

from typing import Any, Callable

import frappe

from albanna_ai_chat.core.jobs import (
    JobOutcome,
    JobProblem,
    JobRequest,
    PrivilegeSnapshot,
    validate_job,
)
from albanna_ai_chat.core.toolset import Reach
from albanna_ai_chat.services.reach import reach_for

#: The user a queued job runs as.  A dedicated principal with no roles of its
#: own, so a job's rights are exactly its snapshot's and nothing else.
#:
#: Not ``Administrator``.  A job running as Administrator has every right on
#: the site, and the snapshot becomes decoration.
JOB_USER = "albanna-ai-chat-job@system"


class SnapshotViolation(RuntimeError):
    """A job tried to write something its snapshot does not permit.

    Raised rather than returned, because a handler that could ignore a ``False``
    would ignore it — and the whole value of the snapshot is that it cannot be
    walked past.
    """


def snapshot_for(user: str) -> PrivilegeSnapshot:
    """What *user* may do right now, as a snapshot.

    Taken at enqueue time and never refreshed.  That is the point: it is what
    was true when the person asked, which is the only thing they authorised.
    A role granted after the request does not widen a queued job.
    """
    reach: Reach = reach_for(user)
    roles = frappe.get_roles(user) if frappe.db.exists("User", user) else ()
    from albanna_ai_chat.core.jobs import snapshot_from_reach

    return snapshot_from_reach(user, roles, reach)


def enqueue(request: JobRequest, handler: str) -> str | JobProblem:
    """Queue *request* to run *handler*, or refuse it with a reason.

    *handler* is the dotted path of the function the worker will call with the
    request.  It is resolved by Frappe's own queue machinery rather than
    imported here, so a job that cannot be imported fails in the worker with a
    traceback rather than silently never running.

    @returns: the job id, or a :class:`JobProblem` naming why it was refused
    """
    problem = validate_job(request)
    if problem is not None:
        return problem

    job_id = frappe.enqueue(
        handler,
        queue="long",
        job_name=request.key,
        **{"request": request},
    )
    return str(job_id)


class JobRunner:
    """Runs one job, checking the snapshot before every write.

    Constructed by the worker entry point with the request it was given.  A
    handler receives it and calls :meth:`assert_may_write` before it changes
    anything — which is the only way a job's write is authorised.
    """

    def __init__(self, request: JobRequest) -> None:
        self.request = request
        self.snapshot: PrivilegeSnapshot = request.snapshot  # type: ignore[assignment]
        self._changed: list[str] = []

    def assert_may_write(self, doctype: str, permission: str = "create") -> None:
        """Refuse unless the snapshot permits *permission* on *doctype*.

        Raises :class:`SnapshotViolation` rather than returning ``False``.  A
        handler that could carry on after a ``False`` would carry on, and the
        snapshot would be advice rather than a gate.
        """
        if not self.snapshot.reachable(permission, doctype):
            raise SnapshotViolation(
                f"This job may not {permission} {doctype}: the account that "
                f"queued it ({self.snapshot.user}) does not hold that right. "
                "The job carries a snapshot of what they could do, and nothing "
                "more."
            )

    def record_change(self, doctype: str, name: str) -> None:
        """Note what this job changed, for the audit row."""
        self._changed.append(f"{doctype}/{name}")

    def outcome(self, ok: bool, summary: str, error: str = "") -> JobOutcome:
        """Build the outcome, carrying what changed."""
        if ok:
            return JobOutcome.success(summary, changed=tuple(self._changed))
        return JobOutcome.failure(summary, error)


def run(request: JobRequest, handler: Callable[[JobRunner], JobOutcome]) -> JobOutcome:
    """Run *handler* under *request*'s snapshot, as the job principal.

    The worker entry point calls this.  It sets the session user to the job
    principal — so Frappe's own permission checks see an account with no roles
    — and restores the previous user afterwards, because a worker process is
    long-lived and the next job must not inherit this one's session.
    """
    problem = validate_job(request)
    if problem is not None:
        return JobOutcome.refusal(str(problem), "invalid_job")

    previous = str(getattr(frappe.session, "user", "") or "")
    try:
        frappe.set_user(JOB_USER)
        runner = JobRunner(request)
        return handler(runner)
    except SnapshotViolation as exc:
        # A refusal, not a failure: the snapshot said no, which is an answer.
        return JobOutcome.refusal(str(exc), "snapshot_denied")
    except Exception as exc:  # noqa: BLE001 — a job must report, not crash the worker
        frappe.log_error(title=f"albanna-ai-chat: job {request.key} failed")
        return JobOutcome.failure(
            f"The job {request.job!r} failed.", f"{type(exc).__name__}: {exc}"
        )
    finally:
        if previous:
            frappe.set_user(previous)


def audit(request: JobRequest, outcome: JobOutcome) -> None:
    """Write one row saying what the job did, whether it worked or not.

    On failure as well as success, because a job that failed silently is a job
    nobody can account for tomorrow.  The purpose travels with the request so
    the row can answer why bytes left the site.
    """
    try:
        frappe.get_doc(
            {
                "doctype": "AI Chat Log",
                "kind": "job",
                "extension": request.extension,
                "job": request.job,
                "user": request.snapshot.user if request.snapshot else "",
                "purpose": request.purpose,
                "ok": 1 if outcome.ok else 0,
                "refused": 1 if outcome.refused else 0,
                "summary": outcome.summary,
                "error": outcome.error,
                "changed": ", ".join(outcome.changed),
            }
        ).insert(ignore_permissions=True)
    except Exception:  # noqa: BLE001 — an audit failure must not fail the job
        frappe.log_error(title="albanna-ai-chat: job audit row failed")


def describe(request: JobRequest) -> dict[str, Any]:
    """A request as a dict, for a log line or a Settings row."""
    snapshot = request.snapshot
    return {
        "extension": request.extension,
        "job": request.job,
        "purpose": request.purpose,
        "user": snapshot.user if snapshot else "",
        "attempts": request.retry.attempts,
    }
