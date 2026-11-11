"""The drift guard between the Python contract and the frontend's warning.

`albanna`'s `write-safety.mjs` carried this warning in a comment: *"a tool added
to the manifest tomorrow would delete data without the card saying so, and
nothing would fail."* That is the failure this test exists to close.

The frontend's `DESTRUCTIVE_TOOLS` set and the Python contract's
`mechanism === "none"` tools are one fact written down twice — once for the
reader's card and once for the runtime's compensation inventory. Two copies of
one fact drift, and the drift is silent: the card stops warning about a write
that cannot be undone, and nothing fails until a reader loses data.

So the two are compared here, at build time, rather than trusted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from albanna_ai_chat.core.file_tools import CORE_TOOLS
from albanna_ai_chat.core.flow import CompensationSpec

HERE = Path(__file__).resolve().parent.parent
WRITE_SAFETY = HERE / "albanna_ai_chat" / "public" / "js" / "lib" / "write-safety.mjs"


def compensation_of(spec):
    """How *spec* is undone, whichever kind of write it is.

    A single-step write declares its undo on the spec itself; a flow carries its
    own, because several calls means several things to undo. Declaring both is a
    contradiction the validator refuses, so exactly one of these is set — and a
    reader of this function has to check both to answer the question at all.
    """
    if spec.flow is not None:
        return spec.flow.compensation
    return spec.compensation


def irreversible_core_tools() -> set[str]:
    """Every core tool whose compensation is ``none`` — no undo exists."""
    irreversible = set()
    for spec in CORE_TOOLS.all():
        compensation = compensation_of(spec)
        if isinstance(compensation, CompensationSpec) and compensation.mechanism == "none":
            irreversible.add(spec.name)
    return irreversible


def frontend_destructive_tools() -> set[str]:
    """The tools the frontend's card warns about, read out of the source."""
    source = WRITE_SAFETY.read_text(encoding="utf-8")
    match = re.search(r"DESTRUCTIVE_TOOLS\s*=\s*new Set\(\[([^\]]*)\]\)", source)
    assert match, "could not find DESTRUCTIVE_TOOLS in write-safety.mjs"
    return {name.strip().strip("\"'") for name in match.group(1).split(",") if name.strip()}


def test_the_frontend_warns_about_exactly_the_irreversible_writes():
    """The card and the compensation inventory are one fact."""
    assert frontend_destructive_tools() == irreversible_core_tools()


def test_the_core_has_at_least_one_irreversible_write():
    """A guard with nothing to guard is a guard that has already drifted to nothing."""
    assert irreversible_core_tools(), (
        "no core tool declares mechanism='none' — either every write became "
        "reversible (update this test) or the compensations were dropped"
    )


def test_a_reversible_write_is_not_warned_about():
    """A card that warns about a recoverable write is a card read past."""
    reversible = set()
    for spec in CORE_TOOLS.all():
        compensation = compensation_of(spec)
        if isinstance(compensation, CompensationSpec) and compensation.mechanism != "none":
            reversible.add(spec.name)
    warned = frontend_destructive_tools()
    assert not (warned & reversible), (
        f"these writes are reversible but the card warns about them: {sorted(warned & reversible)}"
    )


def test_every_warned_tool_is_a_real_core_tool():
    """A warning about a tool that does not exist is a warning nobody can act on."""
    warned = frontend_destructive_tools()
    known = set(CORE_TOOLS.names())
    unknown = warned - known
    assert not unknown, f"the card warns about tools that are not registered: {sorted(unknown)}"


def test_every_warned_tool_has_a_sentence():
    """A tool marked destructive with no sentence is a card that warns and then
    says nothing."""
    source = WRITE_SAFETY.read_text(encoding="utf-8")
    for name in frontend_destructive_tools():
        assert f"{name}:" in source, f"no CONSEQUENCES entry for {name}"
