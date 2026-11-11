"""The Frappe half of the file tools, tested against a stub.

``albanna_ai_chat.tools.files`` imports Frappe, so it cannot run under the
plain ``pytest`` the contract uses.  Rather than leave the security-critical
half untested, this module installs a stub ``frappe`` into ``sys.modules``
before importing it.

The stub is not a mock of convenience — it is the smallest thing that can
answer the three questions the backend asks: *which site is this*, *who is
asking*, and *may they*.  Those three are exactly the guards, and the guards
are exactly what must not be got wrong.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field

import pytest

from albanna_ai_chat.core.file_tools import EDIT_FILE, READ_FILE, WRITE_FILE
from albanna_ai_chat.core.port import Principal, ToolContext, ToolResult


# --------------------------------------------------------------------------
# The stub
# --------------------------------------------------------------------------


class StubFile:
    """A File document with just the surface the backend touches."""

    def __init__(self, name, content=b"", file_url="", is_private=0, mime_type=""):
        self.name = name
        self.file_name = name
        self.file_url = file_url
        self.is_private = is_private
        self.mime_type = mime_type
        self._content = content
        self.fields = {
            "file_url": file_url,
            "mime_type": mime_type,
            "is_private": is_private,
            "name": name,
        }
        self.saved_with = None
        self.inserted = False

    def get(self, key, default=None):
        return self.fields.get(key, default)

    def get_content(self):
        return self._content

    def save_file(self, content=None, **kwargs):
        self.saved_with = (content, kwargs)
        self._content = content.encode("utf-8") if isinstance(content, str) else content

    def insert(self):
        self.inserted = True


@dataclass
class StubFrappe:
    """The three questions, and a place to record what was asked."""

    site: str = "test.localhost"
    user: str = "ahmed@example.com"
    files: dict = field(default_factory=dict)
    #: (doctype, ptype, docname) -> bool.  A missing entry means "no".
    permissions: dict = field(default_factory=dict)
    set_user_calls: list = field(default_factory=list)
    log_error_calls: list = field(default_factory=list)

    # -- session / site -------------------------------------------------
    def get_doc(self, doctype, name):
        if doctype == "File" and name in self.files:
            return self.files[name]
        raise ValueError(f"No {doctype} named {name}")

    def new_doc(self, doctype):
        assert doctype == "File"
        doc = StubFile(name="", content=b"")
        self.files["__pending__"] = doc
        return doc

    # -- db ------------------------------------------------------------
    def get_value(self, doctype, filters, field):
        assert doctype == "File"
        for doc in self.files.values():
            if doc.file_url == filters.get("file_url"):
                return doc.name
        return None

    def exists(self, doctype, name):
        return name if (doctype == "File" and name in self.files) else None

    # -- permissions ---------------------------------------------------
    def has_permission(self, doctype, ptype, doc=None):
        key = (doctype, ptype, getattr(doc, "name", None))
        return self.permissions.get(key, False)

    # -- session -------------------------------------------------------
    def set_user(self, user):
        self.set_user_calls.append(user)
        self.user = user

    def log_error(self, title="", message=""):
        self.log_error_calls.append(title)

    def get_traceback(self):
        return "traceback"


@pytest.fixture
def frappe_stub(monkeypatch):
    """Install a fresh stub and import the backend against it."""
    stub = StubFrappe()
    module = types.ModuleType("frappe")
    for attr in (
        "site",
        "user",
        "files",
        "permissions",
        "set_user_calls",
        "log_error_calls",
        "get_doc",
        "new_doc",
        "get_value",
        "exists",
        "has_permission",
        "set_user",
        "log_error",
        "get_traceback",
    ):
        setattr(module, attr, getattr(stub, attr))

    local = types.SimpleNamespace(site=stub.site)
    session = types.SimpleNamespace(user=stub.user)
    module.local = local
    module.session = session

    monkeypatch.setitem(sys.modules, "frappe", module)
    # frappe.db is a namespace, not a flat attribute — the backend calls
    # frappe.db.get_value / frappe.db.exists.
    module.db = types.SimpleNamespace(get_value=stub.get_value, exists=stub.exists)
    # Drop any previously imported backend so it binds to this stub.
    monkeypatch.delitem(sys.modules, "albanna_ai_chat.tools.files", raising=False)

    from albanna_ai_chat.tools.files import FileToolBackend

    backend = FileToolBackend()
    backend._stub = stub  # type: ignore[attr-defined]
    return backend, stub, local, session


def ctx(user="ahmed@example.com", site="test.localhost"):
    return ToolContext(principal=Principal(user=user, roles=()), site=site)


# --------------------------------------------------------------------------
# handles()
# --------------------------------------------------------------------------


class TestHandles:
    def test_it_claims_the_three_file_tools(self, frappe_stub):
        backend, *_ = frappe_stub
        assert backend.handles("read_file")
        assert backend.handles("write_file")
        assert backend.handles("edit_file")

    def test_it_refuses_everything_else(self, frappe_stub):
        """A backend that accepts everything fails at runtime instead of at config time."""
        backend, *_ = frappe_stub
        for name in ("list_docs", "create_doc", "admit_patient", "nonsense"):
            assert not backend.handles(name), name


# --------------------------------------------------------------------------
# The guards
# --------------------------------------------------------------------------


class TestGuards:
    def test_a_mismatched_site_is_refused(self, frappe_stub):
        """A bench serves several sites from one process."""
        backend, stub, local, _ = frappe_stub
        local.site = "other.localhost"
        result = backend.call(READ_FILE, {"file": "/files/a.txt"}, ctx(site="test.localhost"))
        assert result.denied
        assert "other.localhost" in result.content

    def test_the_actor_is_set_to_the_person_who_asked(self, frappe_stub):
        """Running a turn as Administrator would see everything the caller cannot."""
        backend, stub, _, session = frappe_stub
        session.user = "Administrator"
        stub.files["f1"] = StubFile("f1", content=b"hello", file_url="/files/a.txt")
        stub.permissions[("File", "read", "f1")] = True

        result = backend.call(READ_FILE, {"file": "/files/a.txt"}, ctx(user="ahmed@example.com"))

        assert result.ok
        assert stub.set_user_calls == ["ahmed@example.com"]

    def test_a_call_with_no_user_is_refused(self, frappe_stub):
        backend, *_ = frappe_stub
        result = backend.call(READ_FILE, {"file": "/files/a.txt"}, ctx(user=""))
        assert result.denied
        assert "no user" in result.content

    def test_invalid_arguments_never_reach_frappe(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        result = backend.call(READ_FILE, {"file": 123}, ctx())
        assert not result.ok
        assert result.error == "invalid_arguments"
        assert stub.log_error_calls == []


# --------------------------------------------------------------------------
# read_file
# --------------------------------------------------------------------------


class TestReadFile:
    def test_a_missing_file_is_reported_not_raised(self, frappe_stub):
        backend, *_ = frappe_stub
        result = backend.call(READ_FILE, {"file": "/files/nope.txt"}, ctx())
        assert not result.ok
        assert result.error == "not_found"

    def test_a_path_is_refused_before_any_lookup(self, frappe_stub):
        """The rule that keeps a chat argument from becoming a host path."""
        backend, stub, _, _ = frappe_stub
        result = backend.call(READ_FILE, {"file": "/etc/passwd"}, ctx())
        assert not result.ok
        assert result.error == "bad_file_reference"
        assert stub.files == {}

    def test_a_denied_read_is_a_refusal_not_a_failure(self, frappe_stub):
        """The model must be able to tell a refusal from a broken tool."""
        backend, stub, _, _ = frappe_stub
        stub.files["f1"] = StubFile("f1", content=b"hello", file_url="/files/a.txt")
        stub.permissions[("File", "read", "f1")] = False

        result = backend.call(READ_FILE, {"file": "/files/a.txt"}, ctx())

        assert result.denied
        assert result.error == "denied"
        assert "may not read" in result.content

    def test_a_successful_read_returns_the_text(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        stub.files["f1"] = StubFile("f1", content=b"hello world", file_url="/files/a.txt")
        stub.permissions[("File", "read", "f1")] = True

        result = backend.call(READ_FILE, {"file": "/files/a.txt"}, ctx())

        assert result.ok
        assert "hello world" in result.content
        assert result.summary == "Read 11 characters"

    def test_a_long_file_is_paged_and_says_where_to_continue(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        # Longer than one read, or there is no second page to point at.
        stub.files["f1"] = StubFile("f1", content=b"x" * 20_000, file_url="/files/a.txt")
        stub.permissions[("File", "read", "f1")] = True

        result = backend.call(READ_FILE, {"file": "/files/a.txt", "offset": 0}, ctx())

        assert result.ok
        assert "next_offset" in result.content
        assert "of 20000" in result.summary

    def test_a_picture_is_refused_as_text(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        stub.files["f1"] = StubFile(
            "f1", content=b"\x89PNG", file_url="/files/a.png", mime_type="image/png"
        )
        stub.permissions[("File", "read", "f1")] = True

        result = backend.call(READ_FILE, {"file": "/files/a.png"}, ctx())

        assert not result.ok
        assert result.error == "not_text"
        assert "picture" in result.content

    def test_a_docname_resolves_too(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        stub.files["abc123"] = StubFile("abc123", content=b"by name")
        stub.permissions[("File", "read", "abc123")] = True

        result = backend.call(READ_FILE, {"file": "abc123"}, ctx())

        assert result.ok
        assert "by name" in result.content


# --------------------------------------------------------------------------
# write_file
# --------------------------------------------------------------------------


class TestWriteFile:
    def test_a_path_is_refused(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        result = backend.call(
            WRITE_FILE, {"name": "sub/dir/report.txt", "content": "x"}, ctx()
        )
        assert not result.ok
        assert result.error == "bad_filename"
        assert stub.files == {}

    def test_a_denied_create_is_a_refusal(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        stub.permissions[("File", "create", None)] = False
        result = backend.call(WRITE_FILE, {"name": "a.txt", "content": "x"}, ctx())
        assert result.denied
        assert result.error == "denied"

    def test_a_successful_write_creates_the_record(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        stub.permissions[("File", "create", None)] = True

        result = backend.call(
            WRITE_FILE, {"name": "report.txt", "content": "hello", "is_private": True}, ctx()
        )

        assert result.ok
        doc = stub.files["__pending__"]
        assert doc.inserted
        assert doc.file_name == "report.txt"
        assert doc.is_private == 1
        assert result.summary == "Created report.txt"

    def test_an_attachment_target_needs_both_halves(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        stub.permissions[("File", "create", None)] = True
        result = backend.call(
            WRITE_FILE,
            {"name": "a.txt", "content": "x", "attached_to_doctype": "Sales Order"},
            ctx(),
        )
        assert not result.ok
        assert result.error == "missing_argument"


# --------------------------------------------------------------------------
# edit_file
# --------------------------------------------------------------------------


class TestEditFile:
    def _file(self, stub, content="the quick brown fox"):
        stub.files["f1"] = StubFile("f1", content=content.encode(), file_url="/files/a.txt")
        stub.permissions[("File", "read", "f1")] = True
        stub.permissions[("File", "write", "f1")] = True
        return stub.files["f1"]

    def test_a_unique_edit_is_applied(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        self._file(stub)
        result = backend.call(
            EDIT_FILE,
            {"file": "/files/a.txt", "old_string": "quick", "new_string": "slow"},
            ctx(),
        )
        assert result.ok
        assert stub.files["f1"]._content == b"the slow brown fox"
        assert result.summary.startswith("Edited")

    def test_an_ambiguous_edit_changes_nothing(self, frappe_stub):
        """An edit applied to the wrong occurrence is worse than one that did not happen."""
        backend, stub, _, _ = frappe_stub
        doc = self._file(stub, content="a b a b")
        result = backend.call(
            EDIT_FILE, {"file": "/files/a.txt", "old_string": "a", "new_string": "X"}, ctx()
        )
        assert not result.ok
        assert result.error == "ambiguous_edit"
        assert doc.saved_with is None
        assert result.summary == "Nothing changed"

    def test_an_absent_string_changes_nothing(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        doc = self._file(stub)
        result = backend.call(
            EDIT_FILE, {"file": "/files/a.txt", "old_string": "zzz", "new_string": "X"}, ctx()
        )
        assert not result.ok
        assert doc.saved_with is None

    def test_a_denied_write_is_a_refusal(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        self._file(stub)
        stub.permissions[("File", "write", "f1")] = False
        result = backend.call(
            EDIT_FILE,
            {"file": "/files/a.txt", "old_string": "quick", "new_string": "slow"},
            ctx(),
        )
        assert result.denied
        assert stub.files["f1"].saved_with is None

    def test_the_result_says_how_to_undo(self, frappe_stub):
        """edit_file declares compensation 'reverse' — the result must say so."""
        backend, stub, _, _ = frappe_stub
        self._file(stub)
        result = backend.call(
            EDIT_FILE,
            {"file": "/files/a.txt", "old_string": "quick", "new_string": "slow"},
            ctx(),
        )
        assert result.ok
        assert "swapped" in result.content

    def test_an_edit_is_its_own_inverse(self, frappe_stub):
        backend, stub, _, _ = frappe_stub
        self._file(stub)
        backend.call(
            EDIT_FILE,
            {"file": "/files/a.txt", "old_string": "quick", "new_string": "slow"},
            ctx(),
        )
        result = backend.call(
            EDIT_FILE,
            {"file": "/files/a.txt", "old_string": "slow", "new_string": "quick"},
            ctx(),
        )
        assert result.ok
        assert stub.files["f1"]._content == b"the quick brown fox"


# --------------------------------------------------------------------------
# Drift — the contract and the backend cannot disagree
# --------------------------------------------------------------------------


class TestDrift:
    def test_the_backend_handles_exactly_the_core_tools(self, frappe_stub):
        """A manifest that promises a tool the backend cannot run, or a backend
        that can run a tool the manifest never described, is drift — and drift
        must fail the suite rather than reach a user.
        """
        backend, *_ = frappe_stub
        from albanna_ai_chat.core.file_tools import CORE_TOOLS

        declared = set(CORE_TOOLS.names())
        handled = {name for name in declared if backend.handles(name)}
        assert handled == declared

    def test_the_backend_claims_nothing_outside_the_manifest(self, frappe_stub):
        backend, *_ = frappe_stub
        for name in ("list_docs", "create_doc", "run_report", "admit_patient"):
            assert not backend.handles(name), name

    def test_every_core_tool_is_runnable_end_to_end(self, frappe_stub):
        """Each declared tool has a dispatch entry, not just a handles() claim."""
        backend, stub, _, _ = frappe_stub
        stub.permissions[("File", "create", None)] = True
        stub.files["f1"] = StubFile("f1", content=b"hello", file_url="/files/a.txt")
        stub.permissions[("File", "read", "f1")] = True
        stub.permissions[("File", "write", "f1")] = True

        assert backend.call(READ_FILE, {"file": "/files/a.txt"}, ctx()).ok
        assert backend.call(
            WRITE_FILE, {"name": "b.txt", "content": "x"}, ctx()
        ).ok
        assert backend.call(
            EDIT_FILE,
            {"file": "/files/a.txt", "old_string": "hello", "new_string": "world"},
            ctx(),
        ).ok
