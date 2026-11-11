"""What state an extension is in, and what an operator does about it.

The rule under test is the one the board kept having to restate: *installation
is bench work, activation is a settings change, and availability is a report.*
A Settings screen that offers a button for the first is a screen that lies.
"""

import pytest

from albanna_ai_chat.core.extension_state import (
    ACTIONS,
    ACTIVE,
    INSTALLED_INACTIVE,
    INSTALLED_INCOMPATIBLE,
    NOT_INSTALLED,
    UPDATE_AVAILABLE,
    ExtensionStatus,
    compare_versions,
    parse_version,
    version_satisfies,
)


def status(**kw):
    base = {"name": "healthcare-mcp", "installed": True, "activated": True}
    base.update(kw)
    return ExtensionStatus(**base)


# --------------------------------------------------------------------------
# The five states
# --------------------------------------------------------------------------


class TestStates:
    def test_not_installed_when_the_app_is_absent(self):
        assert status(installed=False).state == NOT_INSTALLED

    def test_installed_but_inactive(self):
        assert status(activated=False).state == INSTALLED_INACTIVE

    def test_active_when_installed_and_on(self):
        assert status().state == ACTIVE

    def test_incompatible_outranks_inactive(self):
        """An extension that cannot run is not merely switched off — it is broken,
        and reporting it as 'not active' would send the operator to the wrong place."""
        s = status(activated=False, requires_core=">=2.0", core_version="1.4.0")
        assert s.state == INSTALLED_INCOMPATIBLE

    def test_an_update_is_reported_only_for_an_active_extension(self):
        """An inactive extension's new release is not news — nobody is using it."""
        s = status(
            activated=False, installed_version="1.0.0", available_version="1.1.0"
        )
        assert s.state == INSTALLED_INACTIVE

    def test_an_update_is_reported_for_an_active_one(self):
        s = status(installed_version="1.0.0", available_version="1.1.0")
        assert s.state == UPDATE_AVAILABLE

    def test_no_update_when_versions_match(self):
        s = status(installed_version="1.1.0", available_version="1.1.0")
        assert s.state == ACTIVE

    def test_no_update_when_nothing_is_known_upstream(self):
        """An unreachable release feed must not read as 'you are current'."""
        s = status(installed_version="1.0.0", available_version="")
        assert s.state == ACTIVE


# --------------------------------------------------------------------------
# What the operator does
# --------------------------------------------------------------------------


class TestActions:
    def test_not_installed_means_bench_work(self):
        s = status(installed=False)
        assert s.action == "install"
        assert "bench get-app" in s.command
        assert "install-app healthcare-mcp" in s.command

    def test_activation_needs_no_command(self):
        """It is a settings change. A command here would be a button pretending."""
        s = status(activated=False)
        assert s.action == "activate"
        assert s.command == ""

    def test_incompatibility_names_both_versions(self):
        s = status(requires_core=">=2.0", core_version="1.4.0")
        assert s.action == "resolve_version"
        assert ">=2.0" in s.command
        assert "1.4.0" in s.command

    def test_an_update_names_the_app_and_both_versions(self):
        s = status(installed_version="1.0.0", available_version="1.2.0")
        assert s.action == "update"
        assert "healthcare-mcp" in s.command
        assert "1.0.0" in s.command and "1.2.0" in s.command

    def test_active_needs_nothing(self):
        s = status()
        assert s.action == ""
        assert s.command == ""

    def test_every_state_has_an_action_or_is_active(self):
        assert set(ACTIONS) == {
            NOT_INSTALLED,
            INSTALLED_INACTIVE,
            INSTALLED_INCOMPATIBLE,
            UPDATE_AVAILABLE,
        }


# --------------------------------------------------------------------------
# The one-line summary
# --------------------------------------------------------------------------


class TestSummary:
    def test_each_state_reads_as_a_sentence(self):
        assert status(installed=False).summary == "Not installed"
        assert status(
            activated=False, installed_version="1.0.0"
        ).summary == "Installed (1.0.0), not active"
        assert status(installed_version="1.0.0").summary == "Active (1.0.0)"

    def test_an_update_says_what_is_available(self):
        s = status(installed_version="1.0.0", available_version="1.3.0")
        assert "1.3.0 available" in s.summary

    def test_incompatibility_says_what_is_needed(self):
        s = status(requires_core=">=2.0", core_version="1.4.0")
        assert "needs core >=2.0" in s.summary


# --------------------------------------------------------------------------
# Version comparison
# --------------------------------------------------------------------------


class TestParseVersion:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1.4.2", (1, 4, 2)),
            ("0.0.0", (0, 0, 0)),
            ("10.20.30", (10, 20, 30)),
            ("v1.4.2", (1, 4, 2)),
            (" 1.4.2 ", (1, 4, 2)),
        ],
    )
    def test_a_version_parses(self, text, expected):
        assert parse_version(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["1.4.2.3", "1.4.x", "", "latest", "1.4.2-beta", None],
    )
    def test_what_cannot_be_parsed_is_refused_not_coerced(self, text):
        """A version that parses as 0.0.0 sorts as the oldest thing in the room
        and silently wins every 'is an update available' question."""
        assert parse_version(text) is None

    @pytest.mark.parametrize("text,expected", [("1.4", (1, 4, 0)), ("1", (1, 0, 0))])
    def test_a_short_version_is_padded(self, text, expected):
        """>=1.0 means >=1.0.0, and refusing to read it would fail closed on the
        most natural way to write a range."""
        assert parse_version(text) == expected


class TestCompareVersions:
    def test_ordering(self):
        assert compare_versions("1.0.0", "1.0.1") == -1
        assert compare_versions("1.0.1", "1.0.0") == 1
        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_numeric_not_lexicographic(self):
        """"10.0.0" is newer than "9.0.0", and a string compare says otherwise."""
        assert compare_versions("10.0.0", "9.0.0") == 1

    def test_an_unparseable_version_sorts_highest(self):
        """So it looks like an update is available — a prompt for a human to
        look — rather than like everything is current, which needs no looking."""
        assert compare_versions("weird", "1.0.0") == 1
        assert compare_versions("1.0.0", "weird") == -1

    def test_two_unparseable_versions_are_equal(self):
        assert compare_versions("weird", "also-weird") == 0


# --------------------------------------------------------------------------
# Compatibility
# --------------------------------------------------------------------------


class TestVersionSatisfies:
    def test_an_empty_requirement_is_satisfied_by_anything(self):
        assert version_satisfies("1.0.0", "")

    def test_a_lower_bound(self):
        assert version_satisfies("1.4.0", ">=1.0")
        assert not version_satisfies("0.9.0", ">=1.0")

    def test_an_upper_bound(self):
        assert version_satisfies("1.9.0", "<2.0")
        assert not version_satisfies("2.0.0", "<2.0")

    def test_a_range_is_a_conjunction(self):
        assert version_satisfies("1.4.0", ">=1.0,<2.0")
        assert not version_satisfies("2.1.0", ">=1.0,<2.0")
        assert not version_satisfies("0.9.0", ">=1.0,<2.0")

    def test_an_exact_pin(self):
        assert version_satisfies("1.4.2", "==1.4.2")
        assert not version_satisfies("1.4.3", "==1.4.2")

    def test_a_bare_version_means_exactly_that_one(self):
        assert version_satisfies("1.4.2", "1.4.2")
        assert not version_satisfies("1.4.3", "1.4.2")

    def test_an_unparseable_clause_fails_closed(self):
        """A compatibility gate that fails open is not a gate."""
        assert not version_satisfies("1.0.0", ">=banana")

    def test_an_unparseable_version_fails_closed(self):
        assert not version_satisfies("banana", ">=1.0")

    def test_boundaries_are_inclusive_where_they_say_so(self):
        assert version_satisfies("1.0.0", ">=1.0.0")
        assert version_satisfies("2.0.0", "<=2.0.0")
        assert not version_satisfies("2.0.0", ">2.0.0")


class TestCompatibility:
    def test_no_requirement_means_compatible(self):
        assert status(requires_core="", core_version="1.0.0").compatible

    def test_a_satisfied_requirement_is_compatible(self):
        s = status(requires_core=">=1.0,<2.0", core_version="1.4.0")
        assert s.compatible

    def test_an_unsatisfied_requirement_is_not(self):
        s = status(requires_core=">=2.0", core_version="1.4.0")
        assert not s.compatible
