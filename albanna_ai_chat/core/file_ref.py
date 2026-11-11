"""File references, and the text operations the file tools promise.

Every promise the three file tools make in their *descriptions* is enforced
here, in Frappe-free code, because a promise that lives only in a docstring
survives until the first person who did not read it.

The promises, and where each is kept:

``read_file``
    A long file comes back in parts, and the envelope says where the next
    part starts.  A silently shortened answer reads as a complete one.
    → :func:`paginate`

``write_file``
    A *bare filename*, never a path.  The validator blocks a parameter named
    ``path``; this blocks a *value* that is a path, because a blocklist on
    parameter names is the first line and not the last.
    → :func:`bare_filename_problem`

``edit_file``
    The text to replace appears *exactly once*, or nothing changes.  An edit
    applied to the wrong occurrence is worse than an edit that failed.
    → :func:`unique_replace`

The Frappe layer in :mod:`albanna_ai_chat.tools.files` resolves a reference to
a File record and calls these.  It never re-implements them, and a test
asserts the two cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from albanna_ai_chat.core.tools import MAX_RESULT_CHARS

#: The two URL prefixes Frappe serves files under.  A reference that starts
#: with one of these is a URL; anything else is treated as a File docname.
PRIVATE_FILE_PREFIX = "/private/files/"
PUBLIC_FILE_PREFIX = "/files/"


class FileRefProblem(str):
    """A reference the core refuses to resolve.

    A ``str`` subclass so it reads as the sentence it is when it reaches the
    model, while still being distinguishable from an ordinary string by
    ``isinstance``.
    """


@dataclass(frozen=True)
class FileRef:
    """A reference to a File record, in the one of two shapes Frappe allows.

    ``kind`` is ``"url"`` or ``"docname"``.  ``is_private`` is ``True`` or
    ``False`` for a URL — the prefix says so — and ``None`` for a docname,
    where only the record itself knows.
    """

    kind: str
    value: str
    is_private: bool | None = None


def _has_traversal(value: str) -> bool:
    """Whether any segment of *value* is a parent-directory reference.

    Checked for URLs as well as bare names.  A URL that begins with a real
    prefix but then climbs out of it — ``/private/files/../../etc/passwd`` —
    is a traversal wearing a valid prefix, and the prefix is not a permission.
    """
    return ".." in value.split("/")


def resolve_file_ref(raw: str) -> FileRef | FileRefProblem:
    """Turn the model's ``file`` argument into a :class:`FileRef`.

    Accepts exactly two shapes and refuses everything else:

    * a URL beginning ``/private/files/`` or ``/files/``
    * the docname of a ``File`` record

    A value containing a path separator that is not one of those two URL
    prefixes is refused.  That is the rule that keeps a chat argument from
    becoming a host-level path: the model may name a file Frappe already
    knows about, and nothing else.
    """
    value = str(raw or "").strip()
    if not value:
        return FileRefProblem(
            "No file was given. Pass the file's URL (/files/... or "
            "/private/files/...) or the name of its File record."
        )

    if _has_traversal(value):
        return FileRefProblem(
            f"{value!r} is a path that climbs out of the files directory. "
            "Pass the file's URL or the name of its File record, with no "
            "'..' in it."
        )

    if value.startswith(PRIVATE_FILE_PREFIX):
        return FileRef(kind="url", value=value, is_private=True)
    if value.startswith(PUBLIC_FILE_PREFIX):
        return FileRef(kind="url", value=value, is_private=False)

    # Not a URL, so it must be a docname.  A docname never contains a
    # separator, and a value that does is a path wearing a docname's clothes.
    if "/" in value or "\\" in value:
        return FileRefProblem(
            f"{value!r} is a path, not a file. Pass the file's URL "
            "(/files/... or /private/files/...) or the name of its File "
            "record — this tool reaches files through the site's own File "
            "records, never the filesystem."
        )
    if value in {".", ".."} or value.startswith("../"):
        return FileRefProblem(
            f"{value!r} is not a file name. Pass the file's URL or the name "
            "of its File record."
        )

    return FileRef(kind="docname", value=value, is_private=None)


def bare_filename_problem(name: str) -> str | None:
    """Why *name* is not an acceptable bare filename, or ``None`` if it is.

    ``write_file`` creates a File record from a name the model supplies.  The
    name must be a filename and nothing else — no directory, no traversal, no
    separator — because everything after the first separator is a path, and a
    path is the thing this tool exists not to accept.
    """
    value = str(name or "")
    if not value.strip():
        return "No filename was given. Pass a bare filename such as 'report.txt'."
    if value != value.strip():
        return (
            f"The filename {value!r} has leading or trailing whitespace. "
            "Pass the filename exactly, with no spaces around it."
        )
    if "/" in value or "\\" in value:
        return (
            f"{value!r} is a path, not a filename. Pass a bare filename such "
            "as 'report.txt' — this tool creates a File record on the site, "
            "and never writes to a location you name."
        )
    if value in {".", ".."}:
        return f"{value!r} is not a filename."
    if value.startswith("."):
        # A leading dot is a hidden file on most systems and a traversal
        # fragment in a URL.  Neither is what the model was asked for.
        return (
            f"The filename {value!r} starts with a dot. Pass a plain "
            "filename such as 'report.txt'."
        )
    if len(value) > 255:
        return (
            f"The filename is {len(value)} characters; the limit is 255. "
            "Pass a shorter name."
        )
    return None


def unique_replace(text: str, old: str, new: str) -> tuple[str, str | None]:
    """Replace *old* with *new*, but only where it is unambiguous.

    Returns ``(new_text, problem)``.  ``problem`` is ``None`` on success and
    a model-readable sentence otherwise; on any problem ``text`` is returned
    unchanged, because an edit applied to the wrong occurrence is worse than
    an edit that did not happen.

    The rule is *exactly once*.  Zero occurrences means the model guessed at
    the file's contents; more than one means it cannot say which occurrence
    it meant, and neither guess is safe to act on.
    """
    if not old:
        return text, (
            "The text to replace is empty. An empty string matches everywhere "
            "and replaces nothing reliably — give the exact text to change."
        )

    count = text.count(old)
    if count == 0:
        return text, (
            "The text to replace was not found in this file. Read the file "
            "first and pass the exact text as it appears, including "
            "punctuation and spacing."
        )
    if count > 1:
        return text, (
            f"The text to replace appears {count} times in this file, so it "
            "does not say which one you mean. Pass a longer stretch of "
            "surrounding text so it appears exactly once."
        )

    return text.replace(old, new, 1), None


@dataclass(frozen=True)
class Page:
    """One part of a file, and how to get the next one."""

    chunk: str
    #: The offset to pass back for the next part, or ``None`` when this is
    #: the last one.  ``None`` rather than a sentinel number, so a caller
    #: cannot accidentally loop forever on a finished file.
    next_offset: int | None
    total_chars: int


def paginate(text: str, offset: int = 0, limit: int = MAX_RESULT_CHARS) -> Page:
    """Take one part of *text* starting at *offset*.

    A negative offset is clamped to the start rather than refused: an offset
    of ``-1`` meaning "the last character" is a Python convention the model
    did not ask for and would not expect.
    """
    total = len(text)
    start = max(0, int(offset or 0))
    end = min(total, start + max(1, int(limit or MAX_RESULT_CHARS)))
    chunk = text[start:end]
    return Page(
        chunk=chunk,
        next_offset=end if end < total else None,
        total_chars=total,
    )


def read_envelope(page: Page, label: str) -> dict:
    """The JSON envelope ``read_file`` hands back.

    The counts and the next offset must survive the backend's truncation of
    the whole result, which is why they travel in the envelope rather than
    being inferred from the text.
    """
    payload: dict = {
        "file": label,
        "total_chars": page.total_chars,
        "returned_chars": len(page.chunk),
    }
    if page.next_offset is not None:
        payload["next_offset"] = page.next_offset
        payload["hint"] = (
            "The file is longer than one read. Call read_file again with "
            f"offset={page.next_offset} to continue."
        )
    return payload
