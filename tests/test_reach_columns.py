"""``PERMISSION_COLUMNS`` names Reach fields, and ``reach_for`` splats it.

A regression test for a bug that shipped.  ``reach_for`` builds its mapping
from ``PERMISSION_COLUMNS`` and splats it into ``Reach(**sets)`` — so the
first element of each pair must be a *Reach field name*, not a Frappe
permission name.  They differ (``creatable`` versus ``create``), and the
mismatch is a ``TypeError`` on the first call.

No test caught it, because the Frappe-free suite cannot call the Frappe half
and nothing else called ``reach_for``.  It surfaced when a real site ran it.
"""

import pytest

from albanna_ai_chat.core.toolset import Reach
from albanna_ai_chat.services.reach import PERMISSION_COLUMNS


def test_every_name_is_a_reach_field():
    """The first element of each pair must be a field ``Reach`` accepts."""
    fields = set(Reach.__slots__)
    for name, _column in PERMISSION_COLUMNS:
        assert name in fields, (
            f"{name!r} is not a Reach field — Reach accepts {sorted(fields)}"
        )


def test_the_mapping_splats_into_reach():
    """The exact operation ``reach_for`` performs must not raise."""
    sets = {name: set() for name, _column in PERMISSION_COLUMNS}
    reach = Reach(**sets)  # raises TypeError on a mismatched name
    assert reach.creatable == set()


def test_every_frappe_permission_is_covered():
    """All six write permissions have a column, or a tool is unreachable."""
    columns = {column for _name, column in PERMISSION_COLUMNS}
    assert columns == {"create", "write", "submit", "cancel", "amend", "delete"}


def test_the_names_are_not_the_permission_names():
    """Guard the guard: the two vocabularies really do differ.

    If they ever converge, the test above still passes — but this one records
    *why* the mapping exists, so a future reader does not "simplify" it back.
    """
    names = {name for name, _column in PERMISSION_COLUMNS}
    assert names == {
        "creatable", "writable", "submittable",
        "cancellable", "amendable", "deletable",
    }
