"""The core's own tools — three of them, and no more.

``read_file``, ``write_file``, ``edit_file``.  That is the whole built-in
surface.  Everything else a chat can do arrives as an extension, which is the
point of the split: the core is a runtime, not a domain expert.

Why files, and why only files
-----------------------------
Files are the one thing every chat user needs regardless of which extensions
are installed.  Asking about a document usually means reading the document,
and the document is a file.  A core that ships no tools is a chat that cannot
look at anything; a core that ships domain tools is a core that has opinions
about which domains matter.  Files are the neutral middle.

Why the parameters look like this
----------------------------------
Every one of these tools takes a *URL or a File record name*, never a path.
That is not a style choice — it is the difference between a tool that goes
through Frappe's permission engine and a tool that reads ``/etc/passwd``.

``albanna``'s ``read_file`` established the shape and it is copied here
deliberately: the argument is called ``file``, it holds either a URL
(``/files/...`` or ``/private/files/...``) or the name of a ``File`` record,
and the handler resolves it through Frappe.  A parameter named ``path``,
``filepath`` or ``filename`` is refused by the validator before the tool ever
reaches a handler (see :data:`~albanna_ai_chat.core.tools.FORBIDDEN_PARAM_NAMES`).

``write_file`` therefore names its argument ``name`` and not ``filename`` —
the blocklist is blunt on purpose, and a blunt rule that is never relaxed is
a rule that keeps working.  The handler validates the value anyway: a name
containing a path separator is refused there too, because a blocklist on
parameter *names* is the first line and not the last.

The tiers, and what they are authorised against
-----------------------------------------------
``read_file``  is a read.  It changes nothing.

``write_file``  is a write authorised against ``create`` — it makes a new
                ``File`` document.  A caller who may create nothing is not
                told the tool exists.

``edit_file``   is a write authorised against ``write`` — it changes a
                ``File`` that already exists.  A caller who may change
                nothing is not told it exists.

Neither is authorised against ``delete``.  There is no ``delete_file`` in the
core, and that is deliberate: deletion is the one file operation with no
undo that the core can offer, and an extension that wants it can declare one
with a compensation entry that says how it is undone.
"""

from __future__ import annotations

from albanna_ai_chat.core.flow import CompensationSpec
from albanna_ai_chat.core.tools import MAX_RESULT_CHARS, READ, WRITE, ToolRegistry, ToolSpec

# --------------------------------------------------------------------------
# read_file
# --------------------------------------------------------------------------

READ_FILE = ToolSpec(
    name="read_file",
    description=(
        "Read the text of a file stored on this site — a document's "
        "attachment, or a file attached in this chat. Pass the file's URL "
        "(/files/... or /private/files/...) or the name of its File record. "
        "A PDF or a text file comes back as text; a picture cannot be read "
        "as text. A long file comes back in parts: read again with the "
        "next_offset the result names to continue."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "file": {
                "type": "string",
                "description": (
                    "The file's URL, e.g. '/private/files/albanna-8f2a1c.pdf', "
                    "or the name of its File record."
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "The character to start reading from, for a file too "
                    "long for one read. Omit to read from the beginning."
                ),
            },
        },
        "required": ["file"],
    },
    tier=READ,
    # The envelope around the text — the counts and the next offset — must
    # survive the truncation of the whole result, so the spec's ceiling is
    # the read's ceiling plus the headroom for it.
    max_result_chars=MAX_RESULT_CHARS + 2000,
    source="core",
)

# --------------------------------------------------------------------------
# write_file
# --------------------------------------------------------------------------

WRITE_FILE = ToolSpec(
    name="write_file",
    description=(
        "Create a new file on this site from text you have. Use this when "
        "the user asks for something to be saved as a file — a draft, a "
        "summary, an export. Give a bare filename such as 'report.txt'; a "
        "path is refused. The file is created as a File record, so it "
        "follows the site's own storage and permission rules. Use "
        "edit_file to change a file that already exists."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "The bare filename to create, e.g. 'report.txt' or "
                    "'meeting-notes.md'. A filename only — never a path, "
                    "and never a directory."
                ),
            },
            "content": {
                "type": "string",
                "description": "The text content of the file.",
            },
            "is_private": {
                "type": "boolean",
                "description": (
                    "When true the file is stored privately and is only "
                    "readable by users who may read it. When false or "
                    "omitted it is a public file. Prefer true unless the "
                    "user asked for the file to be publicly reachable."
                ),
            },
            "attached_to_doctype": {
                "type": "string",
                "description": (
                    "The DocType to attach the file to, e.g. 'Sales Order'. "
                    "Omit for a file that belongs to no document."
                ),
            },
            "attached_to_name": {
                "type": "string",
                "description": (
                    "The name of the document to attach the file to. "
                    "Required when attached_to_doctype is given."
                ),
            },
        },
        "required": ["name", "content"],
    },
    tier=WRITE,
    doctype_arg="",
    write_permission="create",
    source="core",
    # Creating a file is undone by deleting it, and the core deliberately
    # ships no delete_file — deletion is the one file operation with no undo
    # the core can offer.  So this says so, rather than pretending a delete
    # path exists.  An extension that wants one declares it with a real
    # compensation entry.
    compensation=CompensationSpec(
        mechanism="none",
        reason=(
            "The core ships no delete_file tool. A File created in error is "
            "removed by an operator holding delete rights on the File DocType."
        ),
    ),
)

# --------------------------------------------------------------------------
# edit_file
# --------------------------------------------------------------------------

EDIT_FILE = ToolSpec(
    name="edit_file",
    description=(
        "Change part of a text file that already exists, by replacing one "
        "exact string with another. Use this when the user names a file and "
        "asks for something in it to be different. Give only the text to "
        "replace and its replacement; the rest of the file is left exactly "
        "as it is. The string to replace must appear exactly once — if it "
        "appears more than once, or not at all, the tool says so and changes "
        "nothing. A file that is not text cannot be edited this way."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "file": {
                "type": "string",
                "description": (
                    "The file's URL, e.g. '/private/files/albanna-8f2a1c.txt', "
                    "or the name of its File record."
                ),
            },
            "old_string": {
                "type": "string",
                "description": (
                    "The exact text to replace. It must appear exactly once "
                    "in the file."
                ),
            },
            "new_string": {
                "type": "string",
                "description": "The text to put in its place.",
            },
        },
        "required": ["file", "old_string", "new_string"],
    },
    tier=WRITE,
    write_permission="write",
    source="core",
    # An edit is undone by editing back: swap ``old_string`` and
    # ``new_string`` and the file returns to what it was.  That is a genuine
    # inverse, performed by this same tool, which is what ``reverse`` means.
    compensation=CompensationSpec(
        mechanism="reverse",
        undo_with=("edit_file",),
    ),
)


#: Every tool the core ships.
#:
#: Three, and the number is the design.  An extension adds to this registry
#: through the validator; nothing adds to it by editing this file.
CORE_TOOLS = ToolRegistry([READ_FILE, WRITE_FILE, EDIT_FILE])
