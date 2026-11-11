"""Tests for the async primitive's contract.

The rule the whole module exists for: a job carries a snapshot and nothing
else.  A job with no snapshot is refused, a snapshot that does not hold the
right refuses the write, and a hook that imports a provider is refused with a
sentence naming why.
"""

import pytest

from albanna_ai_chat.core.jobs import (
    PROVIDER_MODULES,
    JobOutcome,
    JobProblem,
    JobRequest,
    PrivilegeSnapshot,
    RetryPolicy,
    hook_prohibition_problem,
    provider_imports,
    snapshot_from_reach,
    validate_job,
)
from albanna_ai_chat.core.toolset import Reach


def make_snapshot(**kw):
    base = dict(
        user="ahmed@example.com",
        roles=("Sales User",),
        creatable=frozenset({"Customer"}),
        writable=frozenset({"Customer"}),
    )
    base.update(kw)
    return PrivilegeSnapshot(**base)


def make_request(**kw):
    base = dict(
        extension="document_intelligence",
        job="extract_invoice",
        payload={"file": "abc123"},
        snapshot=make_snapshot(),
        purpose="Extract fields from an uploaded invoice.",
    )
    base.update(kw)
    return JobRequest(**base)


# ---------------------------------------------------------------------------
# a job without a snapshot is refused — the whole rule
# ---------------------------------------------------------------------------


def test_a_job_with_no_snapshot_is_refused():
    problem = validate_job(make_request(snapshot=None))
    assert isinstance(problem, JobProblem)
    assert "privilege snapshot" in problem


def test_a_snapshot_with_no_user_is_refused():
    problem = validate_job(make_request(snapshot=make_snapshot(user="")))
    assert isinstance(problem, JobProblem)


def test_a_job_with_no_purpose_is_refused():
    problem = validate_job(make_request(purpose="   "))
    assert isinstance(problem, JobProblem)
    assert "why it exists" in problem


def test_a_job_with_no_name_is_refused():
    problem = validate_job(make_request(job=""))
    assert isinstance(problem, JobProblem)


def test_a_well_formed_job_is_accepted():
    assert validate_job(make_request()) is None


# ---------------------------------------------------------------------------
# the snapshot answers the reach question, both ways
# ---------------------------------------------------------------------------


def test_a_snapshot_answers_visibility_without_a_doctype():
    assert make_snapshot().reachable("create") is True
    assert make_snapshot().reachable("delete") is False


def test_a_snapshot_answers_the_target_question():
    snap = make_snapshot()
    assert snap.reachable("create", "Customer") is True
    assert snap.reachable("create", "Sales Invoice") is False


def test_may_write_uses_the_named_permission():
    snap = make_snapshot()
    assert snap.may_write("Customer", "create") is True
    assert snap.may_write("Customer", "delete") is False


def test_an_unknown_permission_is_not_held():
    assert make_snapshot().reachable("teleport") is False


def test_a_snapshot_built_from_reach_carries_every_set():
    reach = Reach(
        creatable={"Customer"},
        writable={"Customer"},
        submittable={"Sales Invoice"},
        cancellable=set(),
        amendable=set(),
        deletable=set(),
    )
    snap = snapshot_from_reach("u@example.com", ("Sales User",), reach)
    assert snap.reachable("create", "Customer") is True
    assert snap.reachable("submit", "Sales Invoice") is True
    assert snap.reachable("delete") is False


# ---------------------------------------------------------------------------
# the retry policy
# ---------------------------------------------------------------------------


def test_the_default_policy_retries_a_few_times():
    policy = RetryPolicy()
    assert policy.attempts == 3
    assert policy.backoff_seconds == 60


def test_a_policy_with_no_attempts_is_refused():
    with pytest.raises(ValueError):
        RetryPolicy(attempts=0)


def test_a_negative_backoff_is_refused():
    with pytest.raises(ValueError):
        RetryPolicy(backoff_seconds=-1)


# ---------------------------------------------------------------------------
# outcomes tell a refusal from a failure
# ---------------------------------------------------------------------------


def test_a_refusal_is_not_a_failure():
    outcome = JobOutcome.refusal("Not permitted", "denied")
    assert outcome.refused is True
    assert outcome.ok is False


def test_a_failure_is_not_a_refusal():
    outcome = JobOutcome.failure("Provider timed out", "timeout")
    assert outcome.refused is False
    assert outcome.ok is False


def test_a_success_records_what_changed():
    outcome = JobOutcome.success("Extracted 6 fields", changed=("SINV-0001",))
    assert outcome.ok is True
    assert outcome.changed == ("SINV-0001",)


# ---------------------------------------------------------------------------
# the hook prohibition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", PROVIDER_MODULES)
def test_every_provider_module_is_detected(module):
    assert provider_imports(f"import {module}\n") == [module]


def test_a_from_import_is_detected():
    assert provider_imports("from openai import OpenAI\n") == ["openai"]


def test_a_similar_name_is_not_a_false_positive():
    assert provider_imports("import not_openai\n") == []
    assert provider_imports("import openai_extra\n") == []


def test_a_clean_module_imports_nothing_forbidden():
    source = "import frappe\nfrom albanna_ai_chat.core.jobs import validate_job\n"
    assert provider_imports(source) == []


def test_the_prohibition_sentence_names_the_module_and_the_reason():
    problem = hook_prohibition_problem("healthcare_mcp.hooks", "openai")
    assert "healthcare_mcp.hooks" in problem
    assert "openai" in problem
    assert "every save" in problem


def test_the_prohibition_is_distinguishable_from_an_ordinary_string():
    assert isinstance(hook_prohibition_problem("m", "openai"), JobProblem)
