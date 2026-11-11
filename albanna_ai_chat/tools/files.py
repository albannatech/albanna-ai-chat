"""The Frappe half of the file tools — the only place the core touches a site.

``core/`` holds the contract and the promises; this module keeps them.  It
resolves a reference to a ``File`` record, asks Frappe whether the caller may
touch it, and reads or writes the bytes through Frappe's own file manager.

Three rules this module exists to enforce
-----------------------------------------
**The path is never the model's.**  Every argument is a URL or a File record
*name*.  The on-disk path comes from ``File.get_full_path()`` — Frappe's own
answer, derived from the record — and is never assembled from anything the
model supplied.  That is the whole difference between a chat that reads the
site's files and a chat that reads the host.

**The actor is the person who asked.**  Frappe applies the session user's
roles and User Permissions to every read and write, so the tool must run as
that user.  A turn that runs in a background worker has no session user of its
own, and running it as Administrator would make the assistant able to see
everything its caller cannot.  :meth:`_assert_actor` sets the user before any
permission question is asked.

**The site is the one the turn belongs to.**  A bench serves several sites
from one process.  :meth:`_assert_site` refuses a call bound to a different
site rather than letting it read another site's files.

What is deliberately not here
-----------------------------
PDF text extraction is a real feature and a real dependency.  It is attempted
when ``pypdf`` is installed and refused with a sentence the model can act on
when it is not, rather than half-implemented here.
"""

from __future__ import annotations

import mimetypes
from typing import Any

import frappe

from albanna_ai_chat.core.file_ref import (
    FileRefProblem,
    bare_filename_problem,
    paginate,
    read_envelope,
    resolve_file_ref,
    unique_replace,
)
from albanna_ai_chat.core.port import ToolBackend, ToolContext, ToolResult
from albanna_ai_chat.core.tools import ToolSpec, compact_json, validate_arguments

#: The DocType every one of these tools acts on.  A single doctype is what
#: makes the permission question answerable in one place.
FILE_DOCTYPE = "File"

#: The tools this backend can run.  A backend that cannot run a tool must say
#: so *before* the call — see :meth:`handles`.
FILE_TOOL_NAMES = frozenset({"read_file", "write_file", "edit_file"})

#: Encodings tried in order when decoding a file's bytes.  Frappe's own list,
#: because a file written by this framework is decodable by this framework.
ENCODINGS = ("utf-8", "utf-8-sig", "latin-1")


class FileToolBackend:
    """Runs the core's three file tools against Frappe's File layer."""

    def handles(self, name: str) -> bool:
        """Whether this backend can run the named tool at all."""
        return name in FILE_TOOL_NAMES

    # ------------------------------------------------------------------
    # The port
    # ------------------------------------------------------------------

    def call(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Run one file tool and return its result."""
        problem = validate_arguments(spec, arguments)
        if problem:
            return ToolResult.failure(problem, error="invalid_arguments")

        try:
            self._assert_site(spec, context)
            self._assert_actor(spec, context)
        except RuntimeError as exc:
            # A guard that fires is a configuration fault, not a tool error.
            # It must not read to the model as "the file could not be read".
            return ToolResult.refusal(str(exc), error="guard")

        handler = {
            "read_file": self._run_read_file,
            "write_file": self._run_write_file,
            "edit_file": self._run_edit_file,
        }.get(spec.name)

        if handler is None:  # pragma: no cover - handles() gates this
            return ToolResult.failure(
                f"{spec.name!r} is not a file tool.", error="not_a_file_tool"
            )

        try:
            return handler(arguments, context)
        except Exception as exc:  # noqa: BLE001 — a tool must not kill the turn
            frappe.log_error(
                title=f"albanna-ai-chat: {spec.name} raised",
                message=frappe.get_traceback(),
            )
            return ToolResult.failure(
                f"{spec.name} failed: {type(exc).__name__}: {exc}",
                error="exception",
            )

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _assert_site(self, spec: ToolSpec, context: ToolContext) -> None:
        """Refuse to run against a site other than the turn's own."""
        expected = (context.site or "").strip()
        if not expected:
            return
        actual = str(getattr(frappe.local, "site", "") or "").strip()
        if actual and actual != expected:
            raise RuntimeError(
                f"Refusing to run '{spec.name}': this request is bound to site "
                f"'{actual}', not '{expected}'."
            )

    def _assert_actor(self, spec: ToolSpec, context: ToolContext) -> None:
        """Make sure the tool runs as the person who asked."""
        user = (context.principal.user or "").strip()
        if not user:
            raise RuntimeError(
                f"Refusing to run '{spec.name}': no user was resolved for this call."
            )
        current = str(getattr(frappe.session, "user", "") or "").strip()
        if current != user:
            frappe.set_user(user)

    # ------------------------------------------------------------------
    # read_file
    # ------------------------------------------------------------------

    def _run_read_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        ref = resolve_file_ref(arguments.get("file", ""))
        if isinstance(ref, FileRefProblem):
            return ToolResult.failure(str(ref), error="bad_file_reference")

        doc = self._find_file(ref)
        if doc is None:
            return ToolResult.failure(
                f"No file was found at {ref.value!r}.",
                error="not_found",
                summary="File not found",
            )

        label = doc.get("file_url") or doc.name
        if not self._may("read", doc):
            return ToolResult.refusal(
                f"The file '{label}' could not be read: this account may not read it.",
                error="denied",
            )

        mime = str(doc.get("mime_type") or "") or (
            mimetypes.guess_type(label)[0] or ""
        )
        if mime.startswith("image/"):
            return ToolResult.failure(
                f"'{label}' is a picture, and a picture's pixels cannot be read as text.",
                error="not_text",
                summary="Picture, not text",
            )

        try:
            raw = doc.get_content()
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"The file '{label}' could not be read: {exc}",
                error="unreadable",
            )

        text, problem = self._as_text(raw, mime, label)
        if problem:
            return ToolResult.failure(problem, error="not_text", summary="No text extracted")

        offset = arguments.get("offset") or 0
        page = paginate(text, offset=offset, limit=self._read_limit())
        envelope = read_envelope(page, label)
        envelope["text"] = page.chunk

        return ToolResult.success(
            compact_json(envelope),
            data=envelope,
            summary=(
                f"Read {len(page.chunk)} of {page.total_chars} characters"
                if page.next_offset is not None
                else f"Read {page.total_chars} characters"
            ),
        )

    # ------------------------------------------------------------------
    # write_file
    # ------------------------------------------------------------------

    def _run_write_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        problem = bare_filename_problem(arguments.get("name", ""))
        if problem:
            return ToolResult.failure(problem, error="bad_filename")

        if not self._may("create"):
            return ToolResult.refusal(
                "This account may not create files on this site.",
                error="denied",
            )

        attached_to_doctype = (arguments.get("attached_to_doctype") or "").strip()
        attached_to_name = (arguments.get("attached_to_name") or "").strip()
        if attached_to_doctype and not attached_to_name:
            return ToolResult.failure(
                "attached_to_name is required when attached_to_doctype is given.",
                error="missing_argument",
            )
        if attached_to_name and not attached_to_doctype:
            return ToolResult.failure(
                "attached_to_doctype is required when attached_to_name is given.",
                error="missing_argument",
            )

        name = arguments["name"].strip()
        content = arguments.get("content") or ""

        try:
            doc = frappe.new_doc(FILE_DOCTYPE)
            doc.file_name = name
            doc.content = content
            doc.is_private = 1 if arguments.get("is_private") else 0
            if attached_to_doctype:
                doc.attached_to_doctype = attached_to_doctype
                doc.attached_to_name = attached_to_name
            doc.insert()
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"The file '{name}' could not be created: {exc}",
                error="insert_failed",
            )

        return ToolResult.success(
            compact_json(
                {
                    "file": doc.file_url or doc.name,
                    "name": doc.name,
                    "file_name": doc.file_name,
                    "is_private": bool(doc.is_private),
                    "chars": len(content),
                }
            ),
            summary=f"Created {name}",
        )

    # ------------------------------------------------------------------
    # edit_file
    # ------------------------------------------------------------------

    def _run_edit_file(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        ref = resolve_file_ref(arguments.get("file", ""))
        if isinstance(ref, FileRefProblem):
            return ToolResult.failure(str(ref), error="bad_file_reference")

        doc = self._find_file(ref)
        if doc is None:
            return ToolResult.failure(
                f"No file was found at {ref.value!r}.",
                error="not_found",
                summary="File not found",
            )

        label = doc.get("file_url") or doc.name
        if not self._may("write", doc):
            return ToolResult.refusal(
                f"The file '{label}' could not be changed: this account may not write it.",
                error="denied",
            )

        try:
            raw = doc.get_content()
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"The file '{label}' could not be read for editing: {exc}",
                error="unreadable",
            )

        mime = str(doc.get("mime_type") or "") or (mimetypes.guess_type(label)[0] or "")
        text, problem = self._as_text(raw, mime, label)
        if problem:
            return ToolResult.failure(problem, error="not_text", summary="No text extracted")

        new_text, problem = unique_replace(
            text, arguments.get("old_string", ""), arguments.get("new_string", "")
        )
        if problem:
            # Nothing was changed.  Saying so is the point: an edit applied to
            # the wrong occurrence is worse than an edit that did not happen.
            return ToolResult.failure(problem, error="ambiguous_edit", summary="Nothing changed")

        try:
            doc.save_file(content=new_text, overwrite=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"The file '{label}' could not be changed: {exc}",
                error="save_failed",
            )

        return ToolResult.success(
            compact_json(
                {
                    "file": label,
                    "chars_before": len(text),
                    "chars_after": len(new_text),
                    "undo": (
                        "Call edit_file again with old_string and new_string "
                        "swapped to restore this file exactly."
                    ),
                }
            ),
            summary=f"Edited {label}",
        )

    # ------------------------------------------------------------------
    # Frappe helpers
    # ------------------------------------------------------------------

    def _find_file(self, ref):
        """The File document behind a reference, or ``None``.

        A URL is looked up by ``file_url``; a docname by name.  Neither is
        guessed, and a reference that resolves to nothing returns ``None``
        rather than raising — "no such file" is an answer, not a fault.
        """
        try:
            if ref.kind == "url":
                name = frappe.db.get_value(FILE_DOCTYPE, {"file_url": ref.value}, "name")
                if not name:
                    return None
                return frappe.get_doc(FILE_DOCTYPE, name)
            if frappe.db.exists(FILE_DOCTYPE, ref.value):
                return frappe.get_doc(FILE_DOCTYPE, ref.value)
        except Exception:  # noqa: BLE001 — a missing or broken row is not a crash
            frappe.log_error(title="albanna-ai-chat: file lookup failed")
            return None
        return None

    def _may(self, ptype: str, doc=None) -> bool:
        """Whether the session user holds *ptype* on the File doctype.

        A rule that cannot answer has not said yes, so an exception is a
        refusal rather than a pass.
        """
        try:
            return bool(frappe.has_permission(FILE_DOCTYPE, ptype, doc=doc))
        except Exception:  # noqa: BLE001
            frappe.log_error(title="albanna-ai-chat: permission check failed")
            return False

    def _read_limit(self) -> int:
        """How much text one read returns.

        The spec's own ``max_result_chars`` is deliberately higher, so the
        envelope around the text survives the backend's truncation of the
        whole result.
        """
        from albanna_ai_chat.core.tools import MAX_RESULT_CHARS

        return MAX_RESULT_CHARS

    def _as_text(self, raw: Any, mime: str, label: str) -> tuple[str, str | None]:
        """Decode a file's bytes into text, or say why it cannot be.

        Returns ``(text, problem)``.  ``problem`` is ``None`` on success.
        """
        if isinstance(raw, str):
            return raw, None
        if not isinstance(raw, (bytes, bytearray)):
            return "", f"'{label}' did not return readable content."

        for encoding in ENCODINGS:
            try:
                return bytes(raw).decode(encoding), None
            except UnicodeDecodeError:
                continue

        if mime == "application/pdf":
            text = self._pdf_text(bytes(raw))
            if text:
                return text, None
            return "", (
                f"'{label}' is a PDF and no text could be extracted from it. "
                "It may be a scan — pictures of words, which read as no words "
                "at all. Say so as a fact about the file."
            )

        return "", (
            f"'{label}' is not a text file ({mime or 'unknown type'}), so it "
            "cannot be read as text."
        )

    @staticmethod
    def _pdf_text(data: bytes) -> str:
        """Extract text from a PDF when ``pypdf`` is available.

        Optional on purpose: a PDF extractor is a real dependency, and a core
        that hard-requires one is a core that cannot be installed on a site
        that does not want it.
        """
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError
        except ImportError:
            return ""
        try:
            import io

            reader = PdfReader(io.BytesIO(data))
            return "\n".join(
                page.extract_text() or "" for page in reader.pages
            ).strip()
        except Exception:  # noqa: BLE001 — PdfReadError and friends
            return ""
