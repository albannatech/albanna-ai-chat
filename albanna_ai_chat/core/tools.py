"""The tool contract — what a tool *is*, before anything runs it.

This module is *data and rules*, not behaviour.  It may not import Frappe, and
it may not import any handler.  That constraint is the whole point: the
contract has to be checkable without a site, without a database, and without
a worker, because it is the thing every extension is validated against and
the thing every test asserts.

What lives here
---------------
``ToolSpec``     one tool, as the model and the authority layer both see it
``ToolRegistry`` an ordered, name-addressable collection of specs
``TIER_ORDER``   the closed vocabulary of tiers
the forbidden-parameter rules, as data, so the validator and the tests read
the same list

What does *not* live here
-------------------------
How a tool is executed.  That is the backend's job, behind a port, exactly as
``albanna`` split it — and the split is repeated here deliberately, because a
contract that can call Frappe cannot be tested without one.

The two rules that are not negotiable
-------------------------------------
``FORBIDDEN_PARAM_NAMES`` and ``SQL_PARAM_NAMES`` exist because of two
specific failures, not out of caution:

* A tool that accepts a *filesystem path* is a remote file read/write on the
  host.  ``albanna``'s ``read_file`` takes a URL or a File record *name* and
  resolves it through Frappe's permission engine; it never touches the disk.
  The core's file tools keep that shape.  A parameter called ``path`` is how
  that guarantee is lost, one plausible-looking name at a time.

* A tool that accepts *SQL* bypasses Frappe's permission engine completely,
  including User Permissions and every row-level rule built on them.  A chat
  reachable by ordinary users plus a raw SELECT is a privilege escalation
  with a conversation interface on top.

Both are enforced in :mod:`albanna_ai_chat.core.validate` and asserted in
``tests/test_contract.py``.  A rule that lives only in a comment is a rule
that survives until the first person who did not read the comment.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from albanna_ai_chat.core.flow import CompensationSpec

# --------------------------------------------------------------------------
# Tiers.
#
# A tier is a statement about *what a call does*, never about *who may make
# it*.  The second question belongs to the authority layer, which asks Frappe.
# Conflating the two produces a tool that is "admin only" in a comment and
# "available to everyone" in practice.
# --------------------------------------------------------------------------

READ = "read"
WRITE = "write"

#: The closed tier vocabulary.  A tier outside this set is a contract
#: violation and refuses boot — an unknown tier is a typo that would
#: otherwise silently disable every gate that keys on tier.
TIER_ORDER: tuple[str, ...] = (READ, WRITE)

# --------------------------------------------------------------------------
# Forbidden parameter names.
#
# Matched case-insensitively against a tool's declared parameter names.  A
# match is a hard refusal, not a warning: these are the two shapes that turn
# a chat tool into a host-level primitive.
# --------------------------------------------------------------------------

#: Names that mean "a path on the server's filesystem".
#:
#: ``albanna``'s file tools take a *URL* (``/files/...``,
#: ``/private/files/...``) or the *name of a File record*, and resolve both
#: through Frappe.  A parameter named ``path`` invites a caller to hand over
#: ``/etc/passwd`` or ``../../site_config.json``, and the tool has no way to
#: tell an innocent name from a traversal.
FORBIDDEN_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "path",
        "file_path",
        "filepath",
        "file_name",
        "filename",
        "dir",
        "directory",
        "folder",
        "abs_path",
        "relative_path",
    }
)

#: Names that mean "raw SQL".
#:
#: The one path that legitimately runs SQL in Frappe is Query Reports, which
#: are administrator-authored, guarded by ``check_safe_sql_query`` (select /
#    explain / with only) and parameterised.  That path is not a tool
#: parameter and must never become one.
SQL_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "sql",
        "query",
        "statement",
        "raw_sql",
        "sql_query",
        "db_query",
    }
)

#: The longest tool result handed back to the model, in characters.
#:
#: A tool that returns a 200 KB document set does not become a better answer;
#: it becomes a turn that exhausts the context window before the model has
#: formed a question.  The result is truncated *with a marker that says so*,
# because a silently shortened answer reads as a complete one.
MAX_RESULT_CHARS = 8000

#: The core's own tool names.  An extension may not shadow these.
#:
#: Kept as data rather than derived from a registry so the validator can run
#: before any registry exists — which is the order it has to run in, because
#: the registry is what the validator is protecting.
CORE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
    }
)


@dataclass(frozen=True)
class ToolSpec:
    """One tool, as the model and the authority layer both see it.

    ``description`` is the only thing the model reads before deciding to
    call a tool, so it is written *for a model*, not for a developer: it says
    when to use the tool and when not to, in the reader's own terms.

    ``source`` records provenance — ``"core"`` for the built-in file tools,
    or the installing app's name for an extension tool.  It is what lets the
    Settings surface say *which* extension a tool came from, and what lets an
    uninstall remove exactly that extension's tools and nothing else.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    tier: str = READ
    #: Roles that may call the tool at all.  Empty means "any authenticated
    #: principal" — the authority layer still applies Frappe's own permission
    #: matrix on top, so this narrows and never widens.
    required_roles: tuple[str, ...] = ()
    #: The argument name that carries the target DocType, when the
    #: permission of a call depends on a document the arguments choose.
    doctype_arg: str = ""
    #: Which Frappe permission a write is authorised against.
    write_permission: str = "create"
    max_result_chars: int = MAX_RESULT_CHARS
    enabled: bool = True
    #: ``"core"`` for the built-in file tools, or the installing app's name
    #: for an extension tool.  Empty means "unset" — the validator fills it
    #: with the contributing module's name, which is what lets an uninstall
    #: remove exactly that extension's tools and nothing else.  It is empty
    #: rather than defaulting to ``"core"`` so that a tool which really is
    #: core can say so explicitly and be believed.
    source: str = ""
    #: Set when this tool is a multi-step transactional flow rather than a
    #: single call.  See :mod:`albanna_ai_chat.core.flow`.
    flow: Any = None
    #: How a write is undone, for a *single-step* write.
    #:
    #: Required for every mutating tool, and it is the reason a write does
    #: not have to be a flow.  A flow carries its own compensation (several
    #: calls, several things to undo); a single-step write declares its undo
    #: here.  Declaring both is a contradiction — the validator refuses it,
    #: because two answers to "how is this undone" is the same as none.
    #:
    #: ``None`` on a read tool, which undoes nothing.
    compensation: CompensationSpec | None = None

    @property
    def mutating(self) -> bool:
        """True when a call can change the site."""
        return self.tier == WRITE

    @property
    def is_flow(self) -> bool:
        """True when this tool is a declared multi-step flow."""
        return self.flow is not None

    def to_wire(self) -> dict[str, Any]:
        """The OpenAI-shaped function declaration.

        The schema already forbids unknown arguments — that is what
        ``additionalProperties: false`` means, and it is enforced before a
        call is ever made.  An unexpected argument is a sign the model has
        misread the contract, and rejecting it here costs one round trip
        while passing it through costs a confusing tool error.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """An ordered, name-addressable collection of tool specifications."""

    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self._specs[spec.name] = spec

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self):
        return iter(self._specs.values())

    def names(self) -> tuple[str, ...]:
        """Every known tool name, in manifest order."""
        return tuple(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def all(self) -> list[ToolSpec]:
        """Every known tool, in manifest order."""
        return list(self._specs.values())

    def enabled(self) -> list[ToolSpec]:
        """The tools that are switched on."""
        return [spec for spec in self._specs.values() if spec.enabled]

    def from_source(self, source: str) -> list[ToolSpec]:
        """Every tool contributed by one extension (or ``"core"``).

        This is what makes an uninstall exact: removing an extension removes
        its tools and only its tools, because provenance is recorded rather
        than inferred from a name prefix.
        """
        return [spec for spec in self._specs.values() if spec.source == source]

    def sources(self) -> tuple[str, ...]:
        """Every distinct provenance, in first-seen order."""
        seen: list[str] = []
        for spec in self._specs.values():
            if spec.source not in seen:
                seen.append(spec.source)
        return tuple(seen)

    def without(self, names: Iterable[str]) -> ToolRegistry:
        """A copy with the named tools switched off.

        Used when the operator disables a tool in Settings; the registry the
        model is shown is the result, so a disabled tool is not merely
        refused at call time — it is never mentioned.
        """
        disabled = set(names)
        return self._build(
            {
                spec.name: spec.enabled and spec.name not in disabled
                for spec in self._specs.values()
            }
        )

    def without_writes_out_of_reach(
        self,
        creatable: set[str] | frozenset[str],
        writable: set[str] | frozenset[str],
        submittable: set[str] | frozenset[str] = frozenset(),
        cancellable: set[str] | frozenset[str] = frozenset(),
        amendable: set[str] | frozenset[str] = frozenset(),
        deletable: set[str] | frozenset[str] = frozenset(),
    ) -> ToolRegistry:
        """A copy with the write tools the caller may not make switched off.

        The visibility of a write tool follows the caller's own rights, which
        is what "Frappe decides" means: a person who may create nothing is
        not told ``write_file`` exists, and a person who may change nothing is
        not told ``edit_file`` does.  There is no site-wide switch to
        disagree with the permission matrix, because there is no switch.

        A write tool whose right the caller holds on *no* DocType is switched
        off.  Whether they hold it on the *target* of a particular call is a
        separate question, answered per call by the authority layer — which
        is why a write tool being visible is not the same thing as a write
        being allowed.

        This applies to extension tools exactly as it applies to core tools.
        An extension cannot opt out, because the extension does not own this
        function.
        """
        reachable = {
            "create": bool(creatable),
            "write": bool(writable),
            "submit": bool(submittable),
            "cancel": bool(cancellable),
            "amend": bool(amendable),
            "delete": bool(deletable),
        }
        return self._build(
            {
                spec.name: (not spec.mutating) or reachable.get(spec.write_permission, False)
                for spec in self._specs.values()
            }
        )

    def _build(self, enabled: dict[str, bool]) -> ToolRegistry:
        """A copy of this registry with the given tools switched on or off."""
        return ToolRegistry(
            ToolSpec(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                tier=spec.tier,
                required_roles=spec.required_roles,
                doctype_arg=spec.doctype_arg,
                write_permission=spec.write_permission,
                max_result_chars=spec.max_result_chars,
                enabled=enabled.get(spec.name, spec.enabled),
                source=spec.source,
                flow=spec.flow,
                compensation=spec.compensation,
            )
            for spec in self._specs.values()
        )


def truncate_result(text: str, max_chars: int = MAX_RESULT_CHARS) -> str:
    """Shorten an over-long tool result, and say that it was shortened.

    The marker matters: a truncated answer that does not announce itself is
    indistinguishable from a complete one, and the model will answer as if it
    had seen everything.
    """
    if len(text) <= max_chars:
        return text
    dropped = len(text) - max_chars
    return (
        f"{text[:max_chars]}\n\n"
        f"[truncated: {dropped} more characters. "
        f"Narrow the request — fewer fields, a tighter filter, a smaller limit.]"
    )


def compact_json(value: Any) -> str:
    """Serialise a tool result for the model.

    Compact separators, because every character here is paid for twice: once
    in the request and once in the response.
    """
    return json.dumps(value, separators=(",", ":"), default=str)


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> str | None:
    """Check *arguments* against *spec*'s schema.

    Returns ``None`` when the arguments are acceptable, and a short,
    model-readable sentence when they are not.  The sentence goes back to the
    model as the tool's result, so it has to say what to change rather than
    only that something is wrong.
    """
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - declared dependency
        return None

    validator = jsonschema.Draft202012Validator(spec.parameters)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))
    if not errors:
        return None

    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "(root)"
    return (
        f"Invalid arguments for '{spec.name}' at '{location}': {first.message}. "
        f"Expected: {json.dumps(spec.parameters.get('properties', {}).get(location, {}), default=str)}"
    )


def parse_tool_names(raw: str | None) -> tuple[str, ...]:
    """The operator's list of tool names, in the order they wrote it.

    The settings field is free text: a comma-separated list one way, a line per
    tool another.  Both are read, because an operator who wants to disable
    twelve tools writes one per line and an operator who wants to disable one
    writes it on the same line as nothing else.

    Whitespace separates nothing.  ``read_file edit_file`` is one entry and not
    two, and the entry matches no tool — which is the point: a list that
    quietly reads two tools out of one line the operator thought was a list of
    two is the same silence as a typo.

    A name that appears twice is kept once.  That much is the operator's own
    business and not a thing to tell them about.

    @param raw: the text from the settings field
    @returns: the names, deduplicated, in the order they were written
    """
    text = str(raw or "")
    for separator in (",", "\n"):
        text = text.replace(separator, "\n")

    names: list[str] = []
    for candidate in text.split("\n"):
        name = candidate.strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def unknown_tool_names(raw: str | None, registry: ToolRegistry) -> tuple[str, ...]:
    """The names in the operator's list that are not registered tools.

    A name that matches no tool hides nothing, so the one setting whose whole
    job is to narrow what the assistant may do fails silently — the operator
    believes a tool is disabled and the model still sees it.  Surfacing the
    unknowns is what turns that silence into a message.

    @param raw: the text from the settings field
    @param registry: the registry to check against
    @returns: the names that are not registered, in the order written
    """
    return tuple(name for name in parse_tool_names(raw) if name not in registry)
