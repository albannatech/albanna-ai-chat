"""What one account may do, as Frappe's permission matrix says.

``core/toolset.Reach`` is the *shape* — six sets, one per permission a write
tool can be authorised against.  This module fills it from Frappe, and it is
the only place that translation happens.

Why "at least one DocType" is the whole rule
--------------------------------------------
A write tool is *visible* when the caller holds the right somewhere on the
site.  Whether they hold it on the *target* of a particular call is a separate,
per-call question, answered by the authority layer when the call is made.

That distinction is not a shortcut, it is the only thing that scales.  A
registry that hid ``write_file`` unless the caller could write *every* file
would hide it from almost everyone; one that showed it unless they could write
*some* file would show it to people who can write nothing.  "Somewhere" is the
line between a tool set that is useful and one that is either useless or a lie.

Why DocPerm and not ``frappe.has_permission``
---------------------------------------------
``frappe.has_permission`` answers for one doctype, and the question here is
about *all* of them — there is no doctype to name in advance, because an
extension's tools act on doctypes this module has never heard of.  DocPerm is
the table the permission engine itself reads, so asking it directly is asking
the same question the engine asks, without pretending to know the answer.

What this deliberately does not do
----------------------------------
It does not apply User Permissions, and it does not apply ``if_owner``.  Both
narrow what a *particular call* may touch, and both are enforced per call by
the authority layer.  A visibility rule that tried to anticipate them would be
a second, weaker copy of the permission engine — and two copies of a security
rule is one copy too many.
"""

from __future__ import annotations

import frappe

from albanna_ai_chat.core.toolset import Reach

#: The six Frappe permissions a write tool can be authorised against, and the
#: DocPerm column each one is stored under.
#:
#: The first element is the :class:`~albanna_ai_chat.core.toolset.Reach` field
#: name, **not** the Frappe permission name.  They differ — ``creatable``
#: versus ``create`` — and ``reach_for`` splats this mapping straight into
#: ``Reach(**sets)``, so a permission name here is a ``TypeError`` at the first
#: call.  That bug shipped: ``reach_for`` had no test that called it, because
#: the Frappe-free suite cannot call the Frappe half, and it surfaced only
#: when a real site ran it.
PERMISSION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("creatable", "create"),
    ("writable", "write"),
    ("submittable", "submit"),
    ("cancellable", "cancel"),
    ("amendable", "amend"),
    ("deletable", "delete"),
)


def _roles(user: str) -> list[str]:
    """The user's roles, as Frappe reports them."""
    try:
        return list(frappe.get_roles(user))
    except Exception:  # noqa: BLE001 — no site, no roles
        return []


def _doctypes_with(user: str, column: str) -> set[str]:
    """Every DocType the user's roles hold *column* on.

    Read from DocPerm, which is the table the permission engine itself reads.
    A doctype with no DocPerm row for any of the user's roles is a doctype they
    hold no such right on, which is the answer rather than an error.
    """
    roles = _roles(user)
    if not roles:
        return set()
    try:
        return set(
            frappe.get_all(
                "DocPerm",
                filters={
                    "parenttype": "DocType",
                    "parent": ["!=", ""],
                    column: 1,
                    "role": ["in", roles],
                },
                pluck="parent",
                limit_page_length=0,
            )
        )
    except Exception:  # noqa: BLE001 — an unreadable table means no rights
        return set()


def reach_for(user: str) -> Reach:
    """What *user* may do, as the DocTypes they hold each right on.

    @param user: the Frappe user id
    @returns: a :class:`~albanna_ai_chat.core.toolset.Reach`
    """
    sets = {name: _doctypes_with(user, column) for name, column in PERMISSION_COLUMNS}
    return Reach(**sets)


def reach_summary(reach: Reach) -> dict[str, int]:
    """How many DocTypes each right is held on — for the Settings surface.

    A count rather than a list, because the question an operator asks is "can
    this person write anything", not "which of the four hundred doctypes".
    """
    return {name: len(getattr(reach, name)) for name, _ in PERMISSION_COLUMNS}
