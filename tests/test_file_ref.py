"""The promises the file tools make, enforced in Frappe-free code.

Each test names the promise it defends.  A promise that lives only in a
docstring survives until the first person who did not read it, so the
docstrings point here.
"""

import pytest

from albanna_ai_chat.core.file_ref import (
    PUBLIC_FILE_PREFIX,
    FileRef,
    FileRefProblem,
    bare_filename_problem,
    paginate,
    read_envelope,
    resolve_file_ref,
    unique_replace,
)
from albanna_ai_chat.core.tools import MAX_RESULT_CHARS


# --------------------------------------------------------------------------
# resolve_file_ref — a URL or a docname, and nothing else
# --------------------------------------------------------------------------

class TestResolveFileRef:
    def test_a_private_url_is_private(self):
        ref = resolve_file_ref("/private/files/report-8f2a1c.txt")
        assert ref == FileRef(kind="url", value="/private/files/report-8f2a1c.txt", is_private=True)

    def test_a_public_url_is_public(self):
        ref = resolve_file_ref("/files/report-8f2a1c.txt")
        assert ref == FileRef(kind="url", value="/files/report-8f2a1c.txt", is_private=False)

    def test_a_docname_is_a_docname(self):
        ref = resolve_file_ref("abc123def")
        assert ref == FileRef(kind="docname", value="abc123def", is_private=None)

    def test_surrounding_whitespace_is_stripped(self):
        ref = resolve_file_ref("  /files/a.txt  ")
        assert ref.kind == "url"
        assert ref.value == "/files/a.txt"

    def test_an_empty_reference_is_refused(self):
        problem = resolve_file_ref("")
        assert isinstance(problem, FileRefProblem)
        assert "No file was given" in problem

    def test_a_whitespace_only_reference_is_refused(self):
        assert isinstance(resolve_file_ref("   "), FileRefProblem)

    @pytest.mark.parametrize(
        "value",
        [
            "/etc/passwd",
            "../../etc/passwd",
            "/home/frappe/secrets.txt",
            "files/report.txt",
            "/private/files/../../etc/passwd",
            "C:\\Windows\\system32\\config\\sam",
        ],
    )
    def test_a_path_is_refused(self, value):
        """The rule that keeps a chat argument from becoming a host path."""
        problem = resolve_file_ref(value)
        assert isinstance(problem, FileRefProblem), value
        assert "path" in problem.lower()

    def test_a_dot_is_refused(self):
        assert isinstance(resolve_file_ref("."), FileRefProblem)

    def test_dotdot_is_refused(self):
        assert isinstance(resolve_file_ref(".."), FileRefProblem)

    def test_a_traversal_docname_is_refused(self):
        assert isinstance(resolve_file_ref("../secret"), FileRefProblem)


# --------------------------------------------------------------------------
# bare_filename_problem — write_file takes a filename, never a path
# --------------------------------------------------------------------------

class TestBareFilename:
    @pytest.mark.parametrize(
        "name",
        ["report.txt", "meeting-notes.md", "a", "REPORT.PDF", "notes 2026.txt", "x.y.z"],
    )
    def test_a_plain_filename_is_accepted(self, name):
        assert bare_filename_problem(name) is None

    def test_empty_is_refused(self):
        problem = bare_filename_problem("")
        assert problem is not None
        assert "No filename" in problem

    def test_whitespace_only_is_refused(self):
        assert bare_filename_problem("   ") is not None

    @pytest.mark.parametrize(
        "name",
        [
            "/etc/cron.d/backdoor",
            "subdir/report.txt",
            "../report.txt",
            "..\\report.txt",
            "a/b/c.txt",
        ],
    )
    def test_a_path_is_refused(self, name):
        problem = bare_filename_problem(name)
        assert problem is not None, name
        assert "path" in problem.lower()

    def test_leading_and_trailing_whitespace_is_refused(self):
        problem = bare_filename_problem(" report.txt ")
        assert problem is not None
        assert "whitespace" in problem

    def test_a_leading_dot_is_refused(self):
        """.hidden is a hidden file and a traversal fragment; neither was asked for."""
        problem = bare_filename_problem(".hidden")
        assert problem is not None
        assert "dot" in problem

    def test_an_over_long_name_is_refused(self):
        problem = bare_filename_problem("a" * 256 + ".txt")
        assert problem is not None
        assert "255" in problem

    def test_a_name_at_the_limit_is_accepted(self):
        assert bare_filename_problem("a" * 251 + ".txt") is None


# --------------------------------------------------------------------------
# unique_replace — exactly once, or nothing changes
# --------------------------------------------------------------------------

class TestUniqueReplace:
    def test_a_unique_occurrence_is_replaced(self):
        text, problem = unique_replace("hello world", "world", "there")
        assert problem is None
        assert text == "hello there"

    def test_a_single_occurrence_is_replaced(self):
        """Exactly one occurrence, so there is nothing to disambiguate."""
        text, problem = unique_replace("a b c", "b", "X")
        assert problem is None
        assert text == "a X c"

    def test_an_absent_string_changes_nothing(self):
        text, problem = unique_replace("hello", "goodbye", "x")
        assert problem is not None
        assert text == "hello"
        assert "not found" in problem

    def test_an_ambiguous_string_changes_nothing(self):
        text, problem = unique_replace("a b a b", "a", "X")
        assert problem is not None
        assert text == "a b a b"
        assert "2 times" in problem

    def test_an_empty_old_string_changes_nothing(self):
        text, problem = unique_replace("hello", "", "x")
        assert problem is not None
        assert text == "hello"
        assert "empty" in problem

    def test_replacing_with_an_empty_string_is_a_deletion(self):
        """Deleting a stretch of text is a legitimate edit."""
        text, problem = unique_replace("hello world", " world", "")
        assert problem is None
        assert text == "hello"

    def test_the_problem_says_how_to_fix_it(self):
        """A refusal the model cannot act on is a refusal it will retry blindly."""
        _, problem = unique_replace("a b a b", "a", "X")
        assert "longer stretch" in problem

    def test_an_edit_is_its_own_inverse(self):
        """edit_file declares compensation 'reverse' — this is what that means."""
        original = "the quick brown fox"
        edited, problem = unique_replace(original, "quick", "slow")
        assert problem is None
        restored, problem = unique_replace(edited, "slow", "quick")
        assert problem is None
        assert restored == original


# --------------------------------------------------------------------------
# paginate — a long file comes back in parts, and says where the next starts
# --------------------------------------------------------------------------

class TestPaginate:
    def test_a_short_file_is_one_page(self):
        page = paginate("hello", offset=0, limit=100)
        assert page.chunk == "hello"
        assert page.next_offset is None
        assert page.total_chars == 5

    def test_a_long_file_reports_where_to_continue(self):
        page = paginate("abcdefghij", offset=0, limit=4)
        assert page.chunk == "abcd"
        assert page.next_offset == 4
        assert page.total_chars == 10

    def test_paging_walks_the_whole_file(self):
        text = "x" * 25
        seen = []
        offset = 0
        while True:
            page = paginate(text, offset=offset, limit=10)
            seen.append(page.chunk)
            if page.next_offset is None:
                break
            offset = page.next_offset
        assert "".join(seen) == text
        assert len(seen) == 3

    def test_the_last_page_has_no_next_offset(self):
        page = paginate("abcdefghij", offset=8, limit=10)
        assert page.chunk == "ij"
        assert page.next_offset is None

    def test_an_offset_past_the_end_is_empty_and_finished(self):
        page = paginate("abc", offset=99, limit=10)
        assert page.chunk == ""
        assert page.next_offset is None

    def test_a_negative_offset_is_clamped_not_refused(self):
        page = paginate("abc", offset=-5, limit=10)
        assert page.chunk == "abc"

    def test_the_default_limit_is_the_result_ceiling(self):
        text = "y" * (MAX_RESULT_CHARS + 500)
        page = paginate(text)
        assert len(page.chunk) == MAX_RESULT_CHARS
        assert page.next_offset == MAX_RESULT_CHARS


# --------------------------------------------------------------------------
# read_envelope — the counts survive truncation of the whole result
# --------------------------------------------------------------------------

class TestReadEnvelope:
    def test_a_finished_file_carries_no_next_offset(self):
        page = paginate("hello", limit=100)
        envelope = read_envelope(page, "a.txt")
        assert envelope["total_chars"] == 5
        assert envelope["returned_chars"] == 5
        assert "next_offset" not in envelope

    def test_an_unfinished_file_says_where_to_continue(self):
        page = paginate("abcdefghij", limit=4)
        envelope = read_envelope(page, "a.txt")
        assert envelope["next_offset"] == 4
        assert "offset=4" in envelope["hint"]

    def test_the_envelope_names_the_file(self):
        page = paginate("hello", limit=100)
        assert read_envelope(page, "/files/a.txt")["file"] == "/files/a.txt"
