"""Tests for the hook prohibition as the validator enforces it.

The prohibition is only worth having if it actually refuses a module.  These
build real modules from real source *files* — so ``inspect.getsource`` reads
what an extension would actually have written — without executing them, because
executing ``import openai`` on a machine without ``openai`` installed is not a
test of the guard, it is a test of pip.
"""

import textwrap
import types
from pathlib import Path

import pytest

from albanna_ai_chat.core.tools import READ, ToolSpec
from albanna_ai_chat.core.validate import (
    ContractViolation,
    provider_import_problems,
    validate_module,
)

#: Where the synthetic extension sources live.  A real path, because
#: ``inspect.getsource`` reads from disk and a module with no file has no
#: source to scan.
SOURCE_DIR = Path("/tmp/opencode/hook-prohibition-sources")


def make_module(name, source, tools=None, tiers=None):
    """A module whose *source file* contains *source*, without running it."""
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCE_DIR / f"{name}.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")

    module = types.ModuleType(name)
    module.__file__ = str(path)
    if tools is not None:
        module.TOOLS = tools
    if tiers is not None:
        module.TIERS = tiers
    return module


def spec(name):
    return ToolSpec(
        name=name,
        description=f"Does {name}.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        tier=READ,
    )


CLEAN_SOURCE = """
    import frappe
    from albanna_ai_chat.core.jobs import validate_job

    TOOLS = []
    TIERS = {}
"""

PROVIDER_SOURCE = """
    import openai

    TOOLS = []
    TIERS = {}
"""


# ---------------------------------------------------------------------------
# the guard, on its own
# ---------------------------------------------------------------------------


def test_a_clean_module_has_no_provider_problems():
    module = make_module("clean_ext", CLEAN_SOURCE)
    assert provider_import_problems(module) == []


def test_a_module_importing_a_provider_is_flagged():
    module = make_module("leaky_ext", PROVIDER_SOURCE)
    problems = provider_import_problems(module)
    assert len(problems) == 1
    assert "openai" in problems[0]
    assert "every save" in problems[0]


def test_a_from_import_is_flagged():
    module = make_module("leaky_from_ext", "from anthropic import Anthropic\n")
    problems = provider_import_problems(module)
    assert len(problems) == 1
    assert "anthropic" in problems[0]


def test_a_module_whose_source_cannot_be_read_is_not_refused():
    # A compiled wheel or a REPL module.  The guard is a net, not a wall.
    module = types.ModuleType("opaque_ext")
    module.TOOLS = []
    module.TIERS = {}
    assert provider_import_problems(module) == []


# ---------------------------------------------------------------------------
# the guard, as the validator applies it
# ---------------------------------------------------------------------------


def test_a_clean_extension_validates():
    module = make_module(
        "clean_ext",
        CLEAN_SOURCE,
        tools=[spec("list_patients")],
        tiers={"list_patients": READ},
    )
    validated = validate_module(module)
    assert [s.name for s in validated] == ["list_patients"]


def test_an_extension_importing_a_provider_is_refused_whole():
    module = make_module(
        "leaky_ext",
        PROVIDER_SOURCE,
        tools=[spec("list_patients")],
        tiers={"list_patients": READ},
    )
    with pytest.raises(ContractViolation) as excinfo:
        validate_module(module)
    assert "openai" in str(excinfo.value)


def test_the_refusal_is_atomic_nothing_is_absorbed():
    # A module that breaks *two* rules is refused once, naming both — and
    # returns nothing, because a partially-absorbed extension reads as
    # "the tool sometimes works".
    module = make_module(
        "doubly_broken",
        "import openai\n",
        tools=[spec("unclassified_tool")],
        tiers={},
    )
    with pytest.raises(ContractViolation) as excinfo:
        validate_module(module)
    message = str(excinfo.value)
    assert "openai" in message
    assert "unclassified_tool" in message


def test_the_prohibition_does_not_fire_on_the_core_itself():
    # The core legitimately imports its own provider port.  The guard scans an
    # *extension's* source, and the core is not an extension.
    import albanna_ai_chat.core.provider as provider_module

    assert provider_import_problems(provider_module) == []
