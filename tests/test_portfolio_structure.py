"""Every sibling repo is structurally installable.

Stage 6 installed the core and one extension on a real site and found that a
generated extension **cannot be installed**: its module directory has no
``__init__.py`` and its doctype directories have no controllers.  Both are
install-time failures, and neither is visible to a test that validates a
manifest — because a manifest is not a module, a hook, or a doctype controller.

This test closes that gap.  It walks the sibling repos in the workspace and
asserts the structure Frappe needs, so the bug class cannot ship again.  It is
deliberately structural rather than behavioural: it cannot prove an app
*installs*, only that nothing structural stands in the way.
"""

import json
import re
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parent.parent.parent
CORE = Path(__file__).resolve().parent.parent


def sibling_repos() -> list[Path]:
    """Every repo in the workspace that looks like a portfolio extension."""
    repos = []
    for path in sorted(WORKSPACE.iterdir()):
        if not path.is_dir() or not (path / ".git").is_dir():
            continue
        if path == CORE:
            continue
        if not (path / "pyproject.toml").is_file():
            continue
        repos.append(path)
    return repos


REPOS = sibling_repos()
IDS = [r.name for r in REPOS]


def app_name(repo: Path) -> str:
    return repo.name.replace("-", "_")


# ---------------------------------------------------------------------------
# The package layout Frappe needs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_the_module_directory_has_an_init(repo: Path):
    """``<app>/<app>/__init__.py`` must exist.

    Frappe resolves a module as ``<app>.<module>`` and reads its ``__file__``
    to find the doctype folder.  A module directory without an ``__init__.py``
    is a *namespace* package whose ``__file__`` is ``None``, and ``sync_for``
    then fails with ``TypeError: expected str, bytes or os.PathLike object,
    not NoneType``.
    """
    app = app_name(repo)
    module_init = repo / app / app / "__init__.py"
    assert module_init.is_file(), (
        f"{repo.name}: {app}/{app}/__init__.py is missing — Frappe's module "
        "resolution will yield a namespace package with __file__ = None"
    )


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_the_doctype_package_has_an_init(repo: Path):
    app = app_name(repo)
    assert (repo / app / app / "doctype" / "__init__.py").is_file(), (
        f"{repo.name}: {app}/{app}/doctype/__init__.py is missing"
    )


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_every_doctype_directory_has_a_controller(repo: Path):
    """Every doctype directory needs a ``<doctype>.py``.

    Without one, ``import_file_by_path`` fails with ``Module import failed for
    X`` — at install time, and nowhere earlier.
    """
    app = app_name(repo)
    doctype_root = repo / app / app / "doctype"
    if not doctype_root.is_dir():
        pytest.skip(f"{repo.name} has no doctype directory")
    missing = [
        d.name
        for d in sorted(doctype_root.iterdir())
        if d.is_dir() and not (d / f"{d.name}.py").is_file()
    ]
    assert not missing, (
        f"{repo.name}: doctype directories without a controller: {missing}"
    )


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_every_doctype_json_has_a_matching_directory(repo: Path):
    """A ``.json`` whose directory is missing is a doctype that will not load."""
    app = app_name(repo)
    doctype_root = repo / app / app / "doctype"
    if not doctype_root.is_dir():
        pytest.skip(f"{repo.name} has no doctype directory")
    for json_file in sorted(doctype_root.glob("*/*.json")):
        assert json_file.parent.is_dir(), f"{repo.name}: orphaned {json_file.name}"


# ---------------------------------------------------------------------------
# The hook contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_hooks_declare_the_extension_seam(repo: Path):
    """``frappe_mcp_tools`` must point at a module that exists.

    A hook pointing at a module that is not there is an extension whose tools
    silently never load — the failure mode the whole design exists to avoid.
    """
    app = app_name(repo)
    hooks = repo / app / "hooks.py"
    assert hooks.is_file(), f"{repo.name}: no hooks.py"
    text = hooks.read_text(encoding="utf-8")
    match = re.search(r'^frappe_mcp_tools\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, f"{repo.name}: hooks.py does not declare frappe_mcp_tools"
    target = match.group(1)
    module_path = repo / (target.replace(".", "/") + ".py")
    assert module_path.is_file(), (
        f"{repo.name}: frappe_mcp_tools points at {target}, which does not exist"
    )


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_hooks_do_not_declare_required_apps(repo: Path):
    """``required_apps`` cannot express this portfolio's dependency.

    Frappe resolves it through ``installer.parse_app_name``, which for a bare
    name does a GitHub lookup under ``frappe/`` and ``erpnext/`` only, and for
    an ``org/repo`` form returns the *repository* name.  Repos are named
    ``[APP_NAME]-mcp`` while the package inside is ``[APP_NAME]_mcp``, so
    neither form resolves — declaring it fails with ``InvalidRemoteException``,
    which reads as a network fault rather than a naming conflict.
    """
    app = app_name(repo)
    hooks = repo / app / "hooks.py"
    if not hooks.is_file():
        pytest.skip(f"{repo.name}: no hooks.py")
    text = hooks.read_text(encoding="utf-8")
    assert not re.search(r"^required_apps\s*=", text, re.MULTILINE), (
        f"{repo.name}: hooks.py declares required_apps, which cannot resolve "
        "for a hyphenated repo name — check the core dependency in install.py"
    )


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_the_installer_checks_for_the_core(repo: Path):
    """The core dependency is checked explicitly, since ``required_apps`` cannot."""
    app = app_name(repo)
    install = repo / app / "install.py"
    if not install.is_file():
        pytest.skip(f"{repo.name}: no install.py")
    text = install.read_text(encoding="utf-8")
    assert "albanna_ai_chat" in text, (
        f"{repo.name}: install.py does not check for the core app"
    )


# ---------------------------------------------------------------------------
# The manifest contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_the_manifest_declares_requires_core(repo: Path):
    app = app_name(repo)
    hooks = repo / app / "hooks.py"
    if not hooks.is_file():
        pytest.skip(f"{repo.name}: no hooks.py")
    text = hooks.read_text(encoding="utf-8")
    match = re.search(r'^frappe_mcp_tools\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        pytest.skip(f"{repo.name}: no frappe_mcp_tools hook")
    manifest = repo / (match.group(1).replace(".", "/") + ".py")
    if not manifest.is_file():
        pytest.skip(f"{repo.name}: manifest missing")
    source = manifest.read_text(encoding="utf-8")
    assert re.search(r"^REQUIRES_CORE\s*=", source, re.MULTILINE), (
        f"{repo.name}: the manifest does not declare REQUIRES_CORE"
    )


@pytest.mark.parametrize("repo", REPOS, ids=IDS)
def test_the_pyproject_version_matches_the_package(repo: Path):
    """A version in two places that disagree is a release nobody can trust."""
    app = app_name(repo)
    init = repo / app / "__init__.py"
    pyproject = repo / "pyproject.toml"
    if not init.is_file() or not pyproject.is_file():
        pytest.skip(f"{repo.name}: no version to compare")

    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    proj_match = re.search(
        r'(?m)^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8")
    )
    assert init_match and proj_match, f"{repo.name}: a version is missing"
    assert init_match.group(1) == proj_match.group(1), (
        f"{repo.name}: __init__.py says {init_match.group(1)} but pyproject "
        f"says {proj_match.group(1)}"
    )


# ---------------------------------------------------------------------------
# The workspace itself
# ---------------------------------------------------------------------------


def test_there_are_sibling_repos_to_check():
    """A test that walks an empty directory passes, and means nothing."""
    assert len(REPOS) >= 20, (
        f"only {len(REPOS)} sibling repos found — is this running from the "
        "right workspace?"
    )


def test_the_core_is_not_checked_against_itself():
    assert CORE not in REPOS
