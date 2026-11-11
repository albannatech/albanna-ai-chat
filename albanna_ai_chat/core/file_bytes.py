"""Reading a file's *bytes*, for the handlers that need them.

The three file tools the model sees are text tools: ``read_file`` returns
characters, and it says plainly that *"a picture cannot be read as text."*
That is correct for a model and useless for a vision extractor, which needs
the actual bytes to send to a provider.

So this is a second, deliberately separate channel.  It is **not** a tool —
the model never sees it, and it is not in any manifest.  It is a port an
extension's *handler* calls, server-side, when it has a legitimate need for
the bytes behind a File record.

Why it is separate and not a fourth tool
----------------------------------------
A tool is something the model may ask for, which means its parameters are
model-authored and its reach is whatever the authority layer grants.  A port
is something the *code* asks for, with the caller's identity already
established.  Folding the two together would put a binary-read primitive in
front of the model, and the validator's rule against path-shaped parameters
exists precisely to keep that from happening.

The four rules, and why each is load-bearing
--------------------------------------------
**Never a path.**  A reference is resolved by :func:`resolve_file_ref`, which
accepts a ``/files/...`` URL or a File docname and refuses everything else.
The same rule the text tools keep, kept here rather than assumed.

**Permission before bytes.**  The Frappe half asks Frappe whether the caller
may read the record *before* a single byte is fetched.  A refusal returns no
content at all — not a truncated read, not an error that leaks the size.

**Capped, and the cap is stated.**  A 40-page PDF at vision prices is not a
free operation.  The caller names a ceiling; the port refuses to exceed it and
says what the ceiling was, so the caller can ask for less or escalate
deliberately.

**Streamed.**  The Frappe half reads in chunks rather than materialising the
whole file, because a cap that is enforced after the fact is not a cap.
"""

from __future__ import annotations

from dataclasses import dataclass

from albanna_ai_chat.core.file_ref import FileRefProblem, resolve_file_ref

#: The default ceiling on one binary read, in bytes.
#:
#: 8 MiB.  Large enough for a scanned invoice or a multi-page PDF, small
#: enough that a single read cannot exhaust a worker's memory.  An extension
#: that needs more asks for more explicitly and is refused by the port rather
#: than silently granted.
DEFAULT_MAX_BYTES = 8 * 1024 * 1024

#: The chunk a streamed read pulls at a time.  Small enough that the cap is
#: enforced *during* the read rather than after it.
CHUNK_BYTES = 64 * 1024


class BytesProblem(str):
    """A binary read the core refuses.

    A ``str`` subclass so it reads as the sentence it is when it reaches the
    handler that asked, while still being distinguishable by ``isinstance``.
    """


@dataclass(frozen=True)
class BytesRequest:
    """What a handler is asking for.

    ``max_bytes`` is the ceiling the caller is willing to accept.  It is not
    a hint: the port refuses to return more than this, and a caller that
    needs more must say so.
    """

    file: str
    max_bytes: int = DEFAULT_MAX_BYTES
    #: What the bytes are for, in one line.  Recorded with the read so an
    #: audit can answer "why did this leave the site" without guessing.
    purpose: str = ""


@dataclass(frozen=True)
class BytesEnvelope:
    """What a binary read returns.

    ``truncated`` is True when the file was larger than the ceiling and the
    read stopped.  A handler that ignores it will send a partial document to
    a provider and get a partial answer, so the flag travels with the bytes
    rather than being left for the handler to notice.
    """

    mime: str
    size: int
    truncated: bool
    #: A digest of what was actually returned, so a re-read of the same file
    #: is recognisable as the same input — which is what makes extraction
    #: idempotent.
    digest: str = ""
    label: str = ""


def oversize(size: int, cap: int) -> BytesProblem | None:
    """Whether *size* exceeds *cap*, as a sentence the handler can act on."""
    if size <= cap:
        return None
    return BytesProblem(
        f"The file is {size} bytes, which exceeds the {cap}-byte ceiling for "
        "one read. Ask for a smaller file, or raise the ceiling deliberately "
        "— a cap enforced after the fact is not a cap."
    )


def validate_request(request: BytesRequest) -> BytesProblem | None:
    """Check a request before anything is fetched.

    The reference is resolved here, in Frappe-free code, so a path-shaped
    value is refused before the Frappe half ever runs.  A non-positive
    ceiling is refused too: a cap of zero would make every read a refusal and
    a negative one would make the comparison meaningless.
    """
    if request.max_bytes <= 0:
        return BytesProblem(
            f"A binary read needs a positive ceiling, got {request.max_bytes}."
        )
    ref = resolve_file_ref(request.file)
    if isinstance(ref, FileRefProblem):
        return BytesProblem(str(ref))
    return None


def chunk_plan(total: int, cap: int, chunk: int = CHUNK_BYTES) -> list[int]:
    """The chunk sizes a streamed read pulls, in order.

    The plan never exceeds *cap*, and its last chunk is short — which is how
    the caller can tell a complete read from a truncated one without counting
    bytes by hand.
    """
    if total <= 0:
        return []
    limit = min(total, cap)
    sizes: list[int] = []
    remaining = limit
    while remaining > 0:
        step = min(chunk, remaining)
        sizes.append(step)
        remaining -= step
    return sizes
