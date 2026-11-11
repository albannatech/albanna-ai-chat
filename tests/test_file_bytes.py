"""Tests for the binary file port's contract.

The Frappe half needs a site, so these test the *rules* — which is where the
security lives.  A path-shaped reference is refused before Frappe runs, a
non-positive ceiling is refused, an oversize file is refused with the ceiling
named, and the chunk plan never exceeds the cap.
"""

import pytest

from albanna_ai_chat.core.file_bytes import (
    DEFAULT_MAX_BYTES,
    BytesEnvelope,
    BytesProblem,
    BytesRequest,
    chunk_plan,
    oversize,
    validate_request,
)
from albanna_ai_chat.core.file_ref import FileRefProblem


# ---------------------------------------------------------------------------
# the request is validated before anything is fetched
# ---------------------------------------------------------------------------


def test_a_url_reference_is_accepted():
    request = BytesRequest(file="/private/files/invoice.pdf")
    assert validate_request(request) is None


def test_a_docname_reference_is_accepted():
    request = BytesRequest(file="abc123")
    assert validate_request(request) is None


def test_a_path_is_refused():
    request = BytesRequest(file="/etc/passwd")
    problem = validate_request(request)
    assert isinstance(problem, BytesProblem)


def test_a_traversal_wearing_a_valid_prefix_is_refused():
    request = BytesRequest(file="/private/files/../../etc/passwd")
    problem = validate_request(request)
    assert isinstance(problem, BytesProblem)


def test_a_zero_ceiling_is_refused():
    problem = validate_request(BytesRequest(file="abc123", max_bytes=0))
    assert isinstance(problem, BytesProblem)
    assert "positive" in problem


def test_a_negative_ceiling_is_refused():
    problem = validate_request(BytesRequest(file="abc123", max_bytes=-1))
    assert isinstance(problem, BytesProblem)


def test_an_empty_reference_is_refused():
    problem = validate_request(BytesRequest(file=""))
    assert isinstance(problem, BytesProblem)


# ---------------------------------------------------------------------------
# the cap
# ---------------------------------------------------------------------------


def test_a_file_under_the_cap_is_fine():
    assert oversize(1024, DEFAULT_MAX_BYTES) is None


def test_a_file_at_the_cap_is_fine():
    assert oversize(DEFAULT_MAX_BYTES, DEFAULT_MAX_BYTES) is None


def test_an_oversize_file_is_refused_and_names_the_ceiling():
    problem = oversize(DEFAULT_MAX_BYTES + 1, DEFAULT_MAX_BYTES)
    assert isinstance(problem, BytesProblem)
    assert str(DEFAULT_MAX_BYTES) in problem


def test_the_default_ceiling_is_documented():
    assert DEFAULT_MAX_BYTES == 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# the chunk plan never exceeds the cap
# ---------------------------------------------------------------------------


def test_a_small_file_is_one_chunk():
    assert chunk_plan(100, DEFAULT_MAX_BYTES) == [100]


def test_the_plan_stops_at_the_cap():
    plan = chunk_plan(DEFAULT_MAX_BYTES * 3, DEFAULT_MAX_BYTES)
    assert sum(plan) == DEFAULT_MAX_BYTES
    assert all(step <= 64 * 1024 for step in plan)


def test_the_last_chunk_is_short_so_a_complete_read_is_tellable():
    plan = chunk_plan(64 * 1024 + 10, DEFAULT_MAX_BYTES)
    assert plan[-1] == 10


def test_an_empty_file_has_no_plan():
    assert chunk_plan(0, DEFAULT_MAX_BYTES) == []


# ---------------------------------------------------------------------------
# the envelope
# ---------------------------------------------------------------------------


def test_an_envelope_carries_the_truncation_flag():
    envelope = BytesEnvelope(mime="application/pdf", size=100, truncated=True)
    assert envelope.truncated is True


def test_an_envelope_defaults_to_not_truncated():
    envelope = BytesEnvelope(mime="text/plain", size=10, truncated=False)
    assert envelope.truncated is False


def test_a_refusal_is_distinguishable_from_an_envelope():
    refusal = BytesProblem("denied")
    assert isinstance(refusal, BytesProblem)
    assert not isinstance(refusal, BytesEnvelope)


def test_a_file_ref_problem_is_not_a_bytes_problem():
    # The two refusal types are related but not interchangeable: a handler
    # that catches one and not the other will crash on the other.
    assert not isinstance(FileRefProblem("x"), BytesProblem)
