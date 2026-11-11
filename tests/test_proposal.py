"""Tests for the draft-then-promote contract.

The gate's whole value is that it fails *closed*: no policy means review, no
confidence means review, and a field the operator marked consequential is
never auto-accepted.  Each of those is asserted here, because a gate that
fails open is not a gate.
"""

import pytest

from albanna_ai_chat.core.proposal import (
    DEFAULT_REVIEW_THRESHOLD,
    DRAFT,
    PROMOTED,
    Proposal,
    PromotionPolicy,
    ProposalProblem,
    input_digest,
    review_reason,
    validate_proposal,
)


def make_proposal(**kw):
    base = dict(
        extension="document_intelligence",
        doctype="Sales Invoice",
        name="SINV-0001",
        values={"grand_total": 1200.0},
        confidence=0.95,
    )
    base.update(kw)
    return Proposal(**base)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_a_proposal_with_no_values_is_refused():
    problem = validate_proposal(make_proposal(values={}))
    assert isinstance(problem, ProposalProblem)
    assert "at least one field" in problem


def test_a_confidence_outside_the_range_is_refused():
    problem = validate_proposal(make_proposal(confidence=1.7))
    assert isinstance(problem, ProposalProblem)
    assert "outside" in problem


def test_a_proposal_with_no_doctype_is_refused():
    problem = validate_proposal(make_proposal(doctype=""))
    assert isinstance(problem, ProposalProblem)


def test_a_well_formed_proposal_is_accepted():
    assert validate_proposal(make_proposal()) is None


# ---------------------------------------------------------------------------
# the policy fails closed
# ---------------------------------------------------------------------------


def test_no_policy_means_review():
    policy = PromotionPolicy()
    assert policy.decides(make_proposal()) == "review"


def test_no_confidence_means_review_even_with_auto_accept_on():
    policy = PromotionPolicy(auto_accept=True)
    assert policy.decides(make_proposal(confidence=None)) == "review"


def test_auto_accept_above_threshold():
    policy = PromotionPolicy(auto_accept=True, threshold=0.9)
    assert policy.decides(make_proposal(confidence=0.95)) == "auto"


def test_below_threshold_means_review():
    policy = PromotionPolicy(auto_accept=True, threshold=0.9)
    assert policy.decides(make_proposal(confidence=0.5)) == "review"


def test_a_never_auto_field_refuses_auto_accept():
    policy = PromotionPolicy(
        auto_accept=True, threshold=0.5, never_auto=("grand_total",)
    )
    decision = policy.decides(make_proposal(confidence=0.99))
    assert decision == "refuse"


def test_a_never_auto_field_the_proposal_does_not_touch_is_fine():
    policy = PromotionPolicy(
        auto_accept=True, threshold=0.5, never_auto=("grand_total",)
    )
    decision = policy.decides(
        make_proposal(values={"remarks": "called back"}, confidence=0.99)
    )
    assert decision == "auto"


def test_the_default_threshold_is_the_documented_one():
    assert DEFAULT_REVIEW_THRESHOLD == 0.85


# ---------------------------------------------------------------------------
# the review queue says why
# ---------------------------------------------------------------------------


def test_review_reason_names_the_threshold():
    policy = PromotionPolicy(auto_accept=True, threshold=0.9)
    reason = review_reason(make_proposal(confidence=0.4), policy)
    assert "0.40" in reason and "0.90" in reason


def test_review_reason_says_so_when_there_is_no_confidence():
    reason = review_reason(make_proposal(confidence=None), PromotionPolicy())
    assert "no confidence" in reason


def test_review_reason_names_the_consequential_field():
    policy = PromotionPolicy(auto_accept=True, never_auto=("grand_total",))
    reason = review_reason(make_proposal(confidence=0.99), policy)
    assert "grand_total" in reason
    assert "always needing" in reason


# ---------------------------------------------------------------------------
# idempotency
# ---------------------------------------------------------------------------


def test_the_same_input_digests_the_same():
    assert input_digest({"a": 1, "b": 2}) == input_digest({"b": 2, "a": 1})


def test_a_different_input_digests_differently():
    assert input_digest({"a": 1}) != input_digest({"a": 2})


def test_the_same_proposal_content_hashes_the_same():
    a = make_proposal()
    b = make_proposal(confidence=0.1, model_version="other")
    # Confidence and provenance are not part of *what* would change.
    assert a.content_hash() == b.content_hash()


def test_a_different_target_hashes_differently():
    assert make_proposal(name="SINV-0001").content_hash() != make_proposal(
        name="SINV-0002"
    ).content_hash()


def test_a_new_record_proposal_is_recognised():
    assert make_proposal(name="").is_new_record is True
    assert make_proposal(name="SINV-0001").is_new_record is False


def test_a_proposal_starts_as_a_draft():
    assert make_proposal().status == DRAFT
    assert PROMOTED == "promoted"
