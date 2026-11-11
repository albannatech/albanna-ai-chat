"""The tool set one turn is allowed to use.

One module, because two callers need the same answer and a second copy would
be a second truth: the chat service builds the set it runs the turn with, and
the widget builds the set it tells the browser about.  They are the same set,
and they are computed the same way.

Frappe decides, and it decides per account
------------------------------------------
A write tool appears when the caller holds the right it needs somewhere on the
site — a person who may create a File is offered ``write_file``, and a person
who may change one is offered ``edit_file`` — and it does not appear when they
do not, so the model is never told about a tool it cannot use.

The operator may also hide tools by name.  That list only ever *narrows* the
set.  There is no site-wide switch that can disagree with the permission
matrix, because there is no switch — and that is the whole of the security
model, stated in one place.

Extensions are not a special case
---------------------------------
``without_writes_out_of_reach`` applies to extension specs exactly as it
applies to core specs, using the same ``write_permission`` and ``doctype_arg``
fields.  An extension write tool that cannot be reach-checked was refused at
validation, so by the time a registry reaches this module every write in it is
checkable.
"""

from __future__ import annotations

from collections.abc import Iterable

from albanna_ai_chat.core.tools import ToolRegistry, ToolSpec


class Reach:
    """What one account may do, as the DocTypes they hold each right on.

    Six sets, one per Frappe permission a write tool can be authorised
    against.  "At least one DocType" is deliberate and it is the whole of the
    visibility rule: a write tool is *visible* when the caller holds the right
    somewhere, and whether they hold it on the *target* of a particular call is
    a separate, per-call question.  Visibility is not permission.
    """

    __slots__ = (
        "creatable",
        "writable",
        "submittable",
        "cancellable",
        "amendable",
        "deletable",
    )

    def __init__(
        self,
        creatable: Iterable[str] = (),
        writable: Iterable[str] = (),
        submittable: Iterable[str] = (),
        cancellable: Iterable[str] = (),
        amendable: Iterable[str] = (),
        deletable: Iterable[str] = (),
    ) -> None:
        self.creatable = frozenset(creatable)
        self.writable = frozenset(writable)
        self.submittable = frozenset(submittable)
        self.cancellable = frozenset(cancellable)
        self.amendable = frozenset(amendable)
        self.deletable = frozenset(deletable)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Reach):
            return NotImplemented
        return all(
            getattr(self, slot) == getattr(other, slot) for slot in self.__slots__
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        parts = ", ".join(f"{s}={len(getattr(self, s))}" for s in self.__slots__)
        return f"Reach({parts})"


def visible_tools(
    registry: ToolRegistry,
    reach: Reach,
    disabled: Iterable[str] = (),
) -> ToolRegistry:
    """The tools this account is offered.

    @param registry: every tool known to the site, core and extension
    @param reach: what this account may do, per Frappe's permission matrix
    @param disabled: the operator's list of tool names to hide from everyone
    @returns: a registry with unreachable writes and disabled tools switched off
    """
    base = registry.without_writes_out_of_reach(
        reach.creatable,
        reach.writable,
        reach.submittable,
        reach.cancellable,
        reach.amendable,
        reach.deletable,
    )
    hidden = [name for name in disabled if name]
    if not hidden:
        return base
    return base.without(hidden)


def without_source(registry: ToolRegistry, source: str) -> ToolRegistry:
    """A copy with *source*'s tools removed outright — the uninstall path.

    ``ToolRegistry.without`` switches a tool *off*, which is right for the
    operator's disable list and wrong for an uninstall: a deactivated
    extension's tools must not still be in the registry, or a later extension
    with the same tool name would collide with a tool nobody can see.

    Provenance is what makes this exact.  Removing an extension removes its
    tools and only its tools, which is why ``ToolSpec.source`` is filled in by
    the validator rather than defaulted.
    """
    return ToolRegistry(
        [spec for spec in registry.all() if spec.source != source]
    )


def tools_from(registry: ToolRegistry, *sources: str) -> list[ToolSpec]:
    """Every tool contributed by the named sources, in registry order."""
    wanted = set(sources)
    return [spec for spec in registry.all() if spec.source in wanted]
