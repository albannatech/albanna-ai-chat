"""The Frappe half of the binary file port.

:mod:`albanna_ai_chat.core.file_bytes` states the rules; this module keeps
them.  It resolves a reference to a ``File`` record, asks Frappe whether the
caller may read it, and streams the bytes back — in that order, because a
permission check that runs after the read is not a permission check.

Nothing here is a tool.  The model never sees this surface, and it is not in
any manifest.  It exists for an extension's *handler*, which is code running
server-side with the caller's identity already established.
"""

from __future__ import annotations

import hashlib
from typing import Any

import frappe

from albanna_ai_chat.core.file_bytes import (
    DEFAULT_MAX_BYTES,
    BytesEnvelope,
    BytesProblem,
    BytesRequest,
    chunk_plan,
    oversize,
    validate_request,
)
from albanna_ai_chat.core.file_ref import FileRefProblem, resolve_file_ref
from albanna_ai_chat.core.port import ToolContext

#: The DocType every read resolves through.  One doctype is what makes the
#: permission question answerable in one place.
FILE_DOCTYPE = "File"


class FileBytesPort:
    """Reads the bytes behind a File record, bounded and permission-checked."""

    def __init__(self, file_doctype: str = FILE_DOCTYPE) -> None:
        self.file_doctype = file_doctype

    # ------------------------------------------------------------------
    # the public surface
    # ------------------------------------------------------------------

    def read(self, request: BytesRequest, context: ToolContext) -> bytes | BytesProblem:
        """The bytes behind ``request.file``, or why they cannot be had.

        Returns raw ``bytes`` on success and a :class:`BytesProblem` on any
        refusal.  The envelope — mime, size, whether it was truncated — is
        available from :meth:`envelope` for the same read, and a handler that
        needs both should call :meth:`read_with_envelope`.
        """
        outcome = self.read_with_envelope(request, context)
        if isinstance(outcome, BytesProblem):
            return outcome
        return outcome[0]

    def read_with_envelope(
        self, request: BytesRequest, context: ToolContext
    ) -> tuple[bytes, BytesEnvelope] | BytesProblem:
        """The bytes and the envelope describing them, or a refusal.

        One call rather than two, because a handler that reads the bytes and
        then asks for the envelope is a handler that can be told the file
        changed in between.
        """
        problem = validate_request(request)
        if problem is not None:
            return problem

        ref = resolve_file_ref(request.file)
        if isinstance(ref, FileRefProblem):  # pragma: no cover - validate caught it
            return BytesProblem(str(ref))

        doc = self._find_file(ref)
        if doc is None:
            return BytesProblem(f"No file was found at {ref.value!r}.")

        label = str(doc.get("file_url") or doc.name)
        if not self._may("read", doc):
            # A refusal returns no size and no content.  A refusal that
            # reported the file's size would leak that the file exists and
            # how big it is, which is information the caller was denied.
            return BytesProblem(
                f"The file '{label}' could not be read: this account may not read it."
            )

        declared = self._declared_size(doc)
        if declared is not None:
            problem = oversize(declared, request.max_bytes)
            if problem is not None:
                return problem

        return self._stream(doc, request, label)

    def envelope(
        self, request: BytesRequest, context: ToolContext
    ) -> BytesEnvelope | BytesProblem:
        """What a read *would* return, without returning the bytes.

        For a handler that needs to decide whether to read at all — a vision
        extractor checking a file is a PDF and under its ceiling before it
        spends the money.
        """
        problem = validate_request(request)
        if problem is not None:
            return problem

        ref = resolve_file_ref(request.file)
        doc = self._find_file(ref)
        if doc is None:
            return BytesProblem(f"No file was found at {ref.value!r}.")

        label = str(doc.get("file_url") or doc.name)
        if not self._may("read", doc):
            return BytesProblem(
                f"The file '{label}' could not be read: this account may not read it."
            )

        declared = self._declared_size(doc)
        size = declared if declared is not None else 0
        problem = oversize(size, request.max_bytes)
        if problem is not None:
            return problem

        return BytesEnvelope(
            mime=str(doc.get("mime_type") or ""),
            size=size,
            truncated=False,
            label=label,
        )

    # ------------------------------------------------------------------
    # Frappe helpers
    # ------------------------------------------------------------------

    def _find_file(self, ref):
        """The File document behind a reference, or ``None``."""
        try:
            if ref.kind == "url":
                name = frappe.db.get_value(
                    self.file_doctype, {"file_url": ref.value}, "name"
                )
                if not name:
                    return None
                return frappe.get_doc(self.file_doctype, name)
            if frappe.db.exists(self.file_doctype, ref.value):
                return frappe.get_doc(self.file_doctype, ref.value)
        except Exception:  # noqa: BLE001 — a missing or broken row is not a crash
            frappe.log_error(title="albanna-ai-chat: binary file lookup failed")
            return None
        return None

    def _may(self, ptype: str, doc=None) -> bool:
        """Whether the session user holds *ptype* on the File doctype.

        A rule that cannot answer has not said yes, so an exception is a
        refusal rather than a pass.
        """
        try:
            return bool(frappe.has_permission(self.file_doctype, ptype, doc=doc))
        except Exception:  # noqa: BLE001
            frappe.log_error(title="albanna-ai-chat: binary permission check failed")
            return False

    def _declared_size(self, doc) -> int | None:
        """The file's size as Frappe recorded it, or ``None`` when unrecorded.

        ``None`` is not zero: a File row with no ``file_size`` is a row whose
        size is unknown, and treating unknown as zero would wave every
        oversize file through the cap.
        """
        try:
            raw = doc.get("file_size")
        except Exception:  # noqa: BLE001
            return None
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _stream(
        self, doc, request: BytesRequest, label: str
    ) -> tuple[bytes, BytesEnvelope] | BytesProblem:
        """Pull the file in chunks, stopping at the ceiling.

        The cap is enforced *during* the read — the loop stops rather than
        finishing and trimming — because a cap applied after the fact has
        already paid the cost it was meant to avoid.
        """
        digest = hashlib.sha256()
        collected: list[bytes] = []
        taken = 0
        truncated = False

        try:
            handle = doc.get_content()
        except Exception as exc:  # noqa: BLE001
            return BytesProblem(f"The file '{label}' could not be read: {exc}")

        # ``get_content`` returns the whole file for most backends; the chunk
        # plan is still applied so the ceiling holds regardless, and a backend
        # that *can* stream gets the same guarantee.
        raw = handle if isinstance(handle, (bytes, bytearray)) else None
        if raw is None:
            return BytesProblem(
                f"'{label}' did not return readable content for a binary read."
            )

        total = len(raw)
        for step in chunk_plan(total, request.max_bytes):
            piece = bytes(raw[taken : taken + step])
            if not piece:
                break
            digest.update(piece)
            collected.append(piece)
            taken += step

        if taken < total:
            truncated = True

        mime = str(doc.get("mime_type") or "")
        envelope = BytesEnvelope(
            mime=mime,
            size=taken,
            truncated=truncated,
            digest=digest.hexdigest(),
            label=label,
        )
        return b"".join(collected), envelope


#: The ceiling a handler gets when it does not name one.  Exported so a
#: handler can show the operator what it will accept before it asks.
DEFAULT_CEILING = DEFAULT_MAX_BYTES


def describe(request: BytesRequest) -> dict[str, Any]:
    """A request as a one-line dict, for an audit row.

    An audit that records only "a binary read happened" cannot answer why
    bytes left the site.  The purpose travels with the request so it can.
    """
    return {
        "file": request.file,
        "max_bytes": request.max_bytes,
        "purpose": request.purpose,
    }
