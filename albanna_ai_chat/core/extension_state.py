"""What state an extension is in, and what an operator does about it.

Three words this module exists to keep apart, because collapsing them is how
a Settings screen ends up with a button that cannot work:

**installed**   the app is present on this site.  Done by an operator with
                bench access: ``bench get-app`` then ``bench --site <site>
                install-app``.  A web page cannot do this — it writes to
                ``sites/apps.txt``, runs patches and migrates the schema.

**activated**  the extension is switched on in Settings.  A settings change,
                checkable in-process, reversible in one click.

**available**  a newer release exists upstream.  A *report*, never an action.

The Settings surface reports all three and runs only the second.  For the
other two it shows the exact command, because a button that pretends is worse
than a command an operator can read.

Version compatibility is checked here too, and it is checked against
*activation* rather than installation: an extension whose declared core
version range does not include the running core is reported as incompatible
and refused activation, which is a visible settings row rather than a runtime
surprise.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The states an extension can be in, in the order they are reported.
NOT_INSTALLED = "not_installed"
INSTALLED_INACTIVE = "installed_inactive"
INSTALLED_INCOMPATIBLE = "installed_incompatible"
UPDATE_AVAILABLE = "update_available"
ACTIVE = "active"

#: What the operator does, per state.  ``ACTIVE`` needs nothing, which is why
#: it is absent here rather than mapped to an empty string.
ACTIONS = {
    NOT_INSTALLED: "install",
    INSTALLED_INACTIVE: "activate",
    INSTALLED_INCOMPATIBLE: "resolve_version",
    UPDATE_AVAILABLE: "update",
}


@dataclass(frozen=True)
class ExtensionStatus:
    """One extension, as the Settings surface sees it."""

    name: str
    #: The app is present on this site.
    installed: bool = False
    #: Switched on in Settings.
    activated: bool = False
    #: The version installed on this site, or ``""`` when not installed.
    installed_version: str = ""
    #: The latest release known upstream, or ``""`` when unknown.
    available_version: str = ""
    #: The core version range this extension declares it needs.
    requires_core: str = ""
    #: The core version actually running.
    core_version: str = ""
    #: Why the extension cannot be activated, when it cannot.
    reason: str = ""

    @property
    def compatible(self) -> bool:
        """Whether the running core satisfies this extension's requirement."""
        if not self.requires_core:
            # An extension that declares no requirement is assumed to need the
            # core it was built against, which is the core that is running.
            return True
        return version_satisfies(self.core_version, self.requires_core)

    @property
    def state(self) -> str:
        if not self.installed:
            return NOT_INSTALLED
        if not self.compatible:
            return INSTALLED_INCOMPATIBLE
        if not self.activated:
            return INSTALLED_INACTIVE
        if self._update_available:
            return UPDATE_AVAILABLE
        return ACTIVE

    @property
    def _update_available(self) -> bool:
        if not self.available_version or not self.installed_version:
            return False
        return compare_versions(self.available_version, self.installed_version) > 0

    @property
    def action(self) -> str:
        """What the operator does next, or ``""`` when nothing is needed."""
        return ACTIONS.get(self.state, "")

    @property
    def command(self) -> str:
        """The exact bench command, or ``""`` when Settings can do it alone.

        Activation is deliberately absent: it is a settings change and needs
        no command.  Everything else is bench work and says so.
        """
        if self.state == NOT_INSTALLED:
            return (
                f"bench get-app https://github.com/albannatech/{self.name}.git "
                f"&& bench --site <site> install-app {self.name}"
            )
        if self.state == INSTALLED_INCOMPATIBLE:
            return (
                f"# {self.name} needs core {self.requires_core or '(unstated)'} "
                f"but {self.core_version or '(unknown)'} is running — "
                f"upgrade the core or the extension, then activate"
            )
        if self.state == UPDATE_AVAILABLE:
            return (
                f"bench --site <site> update --app {self.name} "
                f"# {self.installed_version} → {self.available_version}"
            )
        return ""

    @property
    def summary(self) -> str:
        """One line for the Settings list."""
        if self.state == NOT_INSTALLED:
            return "Not installed"
        if self.state == INSTALLED_INCOMPATIBLE:
            return f"Incompatible — needs core {self.requires_core}"
        if self.state == INSTALLED_INACTIVE:
            return f"Installed ({self.installed_version}), not active"
        if self.state == UPDATE_AVAILABLE:
            return (
                f"Active ({self.installed_version}) — "
                f"{self.available_version} available"
            )
        return f"Active ({self.installed_version})"


# --------------------------------------------------------------------------
# A small, honest semver
# --------------------------------------------------------------------------
#
# Not a full implementation of the spec: no pre-release or build metadata,
# because a release channel that needs them is a release channel this module
# should not be guessing about.  What it does do is compare the three numbers
# correctly and refuse a version it cannot parse rather than treating it as
# zero — a version that parses as 0.0.0 sorts as the oldest thing in the room
# and silently wins every "is an update available" question.


def parse_version(version: str) -> tuple[int, int, int] | None:
    """``"1.4.2"`` → ``(1, 4, 2)``, or ``None`` when it cannot be parsed.

    One to three parts are accepted and padded with zeros, because a
    requirement written ``>=1.0`` means ``>=1.0.0`` and refusing it would fail
    closed on the most natural way to write a range.  A leading ``v`` is
    accepted because people write it.  Anything else — four parts, a
    pre-release suffix, a word — is refused rather than coerced.
    """
    text = str(version or "").strip()
    if text.startswith(("v", "V")):
        text = text[1:]
    parts = text.split(".")
    if not 1 <= len(parts) <= 3:
        return None
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


def compare_versions(left: str, right: str) -> int:
    """``-1``, ``0`` or ``1``.  An unparseable version sorts *highest*.

    Highest rather than lowest, and deliberately: an extension reporting a
    version this module cannot read should look like an update is available —
    a prompt for a human to look — rather than like everything is current,
    which is the answer that needs no looking.
    """
    a, b = parse_version(left), parse_version(right)
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    return (a > b) - (a < b)


def version_satisfies(version: str, requirement: str) -> bool:
    """Whether *version* satisfies a requirement such as ``">=1.0,<2.0"``.

    Comma-separated clauses are a conjunction — every one must hold, which is
    what a range means.  An empty requirement is satisfied by anything, and a
    clause this module cannot parse is *not* satisfied, because a compatibility
    gate that fails open is not a gate.
    """
    requirement = str(requirement or "").strip()
    if not requirement:
        return True

    have = parse_version(version)
    if have is None:
        return False

    for clause in requirement.split(","):
        clause = clause.strip()
        if not clause:
            continue
        operator, wanted = _split_clause(clause)
        target = parse_version(wanted)
        if target is None:
            return False
        if not _apply(have, operator, target):
            return False
    return True


def _split_clause(clause: str) -> tuple[str, str]:
    for operator in (">=", "<=", "==", "!=", ">", "<"):
        if clause.startswith(operator):
            return operator, clause[len(operator) :].strip()
    # A bare version means "exactly this one".
    return "==", clause


def _apply(have: tuple[int, int, int], operator: str, want: tuple[int, int, int]) -> bool:
    if operator == ">=":
        return have >= want
    if operator == "<=":
        return have <= want
    if operator == ">":
        return have > want
    if operator == "<":
        return have < want
    if operator == "==":
        return have == want
    if operator == "!=":
        return have != want
    return False
