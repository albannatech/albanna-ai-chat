"""The execution port — how a tool is *run*, without saying how.

The contract in :mod:`albanna_ai_chat.core.tools` says what a tool *is*.  This
module says how one is *called*, and it deliberately stops short of saying
what happens next.

That indirection is the app's central decision made reversible.  Today the
only implementation is :mod:`albanna_ai_chat.tools.files`, which resolves a
File record through Frappe's permission engine and never touches the disk.  A
second implementation — one that spoke to a remote store over HTTP — would
satisfy the same port, and the contract, the authority layer and the
model-facing manifest would not change by a line.

Why the port is Frappe-free
---------------------------
``core/`` may not import Frappe (ADR 0021).  The port is part of ``core/``
because the *shape* of a call is contract, not behaviour: who is calling, on
which site, with which arguments, and what came back.  None of that needs a
database to be expressed, and all of it needs to be testable without one.

What a result carries, and why
------------------------------
``ToolResult`` is not a bare string.  A tool call has four outcomes a model
must be able to tell apart, and collapsing them into "it worked" or "it
didn't" is how an assistant ends up confidently reporting a write that was
refused:

``ok``          the call ran and produced an answer
``denied``      the authority layer refused it — the caller may not do this
``approved``    for a write that waited: True, False, or None when it did not
                wait at all.  A write that waited and was declined is not a
                failure, and reporting it as one teaches the model to retry.
``dry_run``     the write ran and was rolled back, so nothing was saved

``summary`` is the one line the panel shows beside the tool's name, so the
reader can see what was looked up without reading the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from albanna_ai_chat.core.tools import ToolSpec


@dataclass(frozen=True)
class Principal:
    """Who is making the call.

    ``user`` is the Frappe user id.  ``roles`` is a snapshot of that user's
    roles at the moment the turn started — a snapshot, not a live read,
    because a role granted halfway through a turn should not change what the
    turn is allowed to do.
    """

    user: str
    roles: tuple[str, ...] = ()

    def has_role(self, role: str) -> bool:
        return role in self.roles


@dataclass(frozen=True)
class ToolContext:
    """Who is calling, and on which site.

    ``conversation`` is the thread the call belongs to, when there is one.
    The model never fills it in — it is not in any schema — and the backend
    hands it to the handlers that declare it.  A tool that needs to know
    *which thread* it is in asks for it; a tool that does not, ignores it.
    """

    principal: Principal
    site: str
    request_id: str = ""
    conversation: str = ""


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one tool call."""

    ok: bool
    content: str
    data: Any = None
    error: str = ""
    denied: bool = False
    #: For a write that waited for approval: True if approved, False if
    #: declined or timed out, None when the write did not wait at all.
    approved: bool | None = None
    #: One line saying what the call found — "Read 3 files".  It is what the
    #: panel shows beside the tool's name.
    summary: str = ""
    #: True when the write ran under dry-run and was rolled back.
    dry_run: bool = False

    @classmethod
    def success(cls, content: str, data: Any = None, summary: str = "") -> ToolResult:
        return cls(ok=True, content=content, data=data, summary=summary)

    @classmethod
    def failure(cls, content: str, error: str, data: Any = None, summary: str = "") -> ToolResult:
        return cls(ok=False, content=content, error=error, data=data, summary=summary)

    @classmethod
    def refusal(cls, content: str, error: str) -> ToolResult:
        """A refusal is not a failure.

        The authority layer said no.  The model must be able to tell this
        from a tool that broke, because the correct response to a refusal is
        to tell the reader they lack the right — not to retry, and not to
        report an error.
        """
        return cls(ok=False, content=content, error=error, denied=True)


class ToolBackend(Protocol):
    """Runs a tool."""

    def call(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Run one tool and return its result."""
        ...

    def handles(self, name: str) -> bool:
        """Whether this backend can run the named tool at all.

        A backend that cannot run a tool must say so *before* the call,
        because a backend that accepts everything and fails at runtime turns
        a configuration mistake into a confusing tool error the model has to
        interpret.
        """
        ...


class PermissionChecker(Protocol):
    """Asks Frappe what a principal may do.

    This is the only place the authority question is answered, and it lives
    behind a protocol so ``core/`` can state the question without importing
    the thing that answers it.  The Frappe implementation reads the real
    permission matrix; a test implementation returns a fixed answer.
    """

    def reachable(
        self,
        principal: Principal,
        permission: str,
    ) -> bool:
        """Whether *principal* holds *permission* on at least one DocType.

        "At least one" is deliberate and it is the whole of ``albanna``'s
        ADR 0008: a write tool is *visible* when the caller holds the right
        somewhere, and whether they hold it on the *target* of a particular
        call is a separate, per-call question.  Visibility is not permission.
        """
        ...
