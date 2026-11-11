"""The model proposes; a human or an explicit rule disposes.

This module is the contract half of the gate that keeps a model's output from
becoming a site's data in one step.  It is Frappe-free for the same reason the
tool contract is: the *rules* about what a proposal is must be checkable
without a site, and the thing that persists one lives behind the port in
:mod:`albanna_ai_chat.services.proposals`.

Why a proposal and not a write
------------------------------
Three of the five reference extensions end in "and then set a field": document
extraction populates a DocType, classification tags a record, generation fills
a text box.  In every case the model is *guessing* — a vision model misreads a
figure, a classifier picks the wrong queue, a generator invents a detail — and
in every case the guess lands somewhere a person will rely on.

So the model's output is a **proposal**: a draft that names what it would
change, how confident it is, and which model and prompt produced it.  Setting
the field on the real document is a separate, permissioned, audited action.
For a submitted document the proposal is the only thing that is ever written,
because a submitted document cannot be edited — it has to be cancelled and
amended, which nothing here does.

What the gate is not
--------------------
It is not a veto.  An operator may declare a policy that auto-accepts above a
confidence threshold, and that is a legitimate configuration for a low-stakes
field.  What the gate forbids is the *silent* version: a model writing straight
to a live record with no draft, no confidence, no provenance and no way to ask
"why is this ticket in this queue" beyond "the model said so, once".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: The states a proposal moves through.  ``PROMOTED`` and ``REJECTED`` are
#: terminal; ``EXPIRED`` is what an unanswered proposal becomes, and it is
#: distinct from a rejection because nobody decided anything.
DRAFT = "draft"
PROMOTED = "promoted"
REJECTED = "rejected"
EXPIRED = "expired"

#: The default confidence below which a proposal always waits for a human.
#:
#: Not a tuned number — a placeholder an operator is expected to replace per
#: extension.  It exists so that "no threshold configured" fails *closed*
#: rather than open: an extension that never set one gets review, not a free
#: pass.
DEFAULT_REVIEW_THRESHOLD = 0.85


class ProposalProblem(str):
    """A proposal the core refuses to record.

    A ``str`` subclass so it reads as the sentence it is when it reaches the
    developer whose extension produced it.
    """


@dataclass(frozen=True)
class Proposal:
    """One thing a model would change, held as a draft.

    ``values`` is the proposed field map, never applied.  ``confidence`` is
    the model's own number when it has one and ``None`` when it does not —
    and ``None`` is *not* treated as high confidence, because a model that
    cannot say how sure it is has not said it is sure.
    """

    extension: str
    doctype: str
    values: dict[str, Any]
    #: The document the proposal would change, or ``""`` for a new record.
    name: str = ""
    confidence: float | None = None
    #: Which model and which prompt version produced this.  Stored with the
    #: proposal so a re-run after a prompt change is visible as a change.
    model_version: str = ""
    prompt_version: str = ""
    #: A hash of the input the proposal was derived from.  The same input
    #: produces the same proposal rather than a second row.
    input_hash: str = ""
    #: One line saying what the proposal would do, for the review queue.
    summary: str = ""
    status: str = DRAFT
    #: Why an irreversible action is nonetheless proposed, when it is.
    reason: str = ""

    @property
    def is_new_record(self) -> bool:
        return not self.name

    def content_hash(self) -> str:
        """A stable hash of what this proposal would change.

        Two proposals with the same extension, target and values are the same
        proposal, and the second one updates the first rather than adding a
        row — which is what makes re-uploading a file idempotent.
        """
        payload = json.dumps(
            {
                "extension": self.extension,
                "doctype": self.doctype,
                "name": self.name,
                "values": self.values,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromotionPolicy:
    """What an operator has declared about auto-accepting proposals.

    ``auto_accept`` is off by default and it is off *deliberately*: the safe
    configuration is the one that requires a decision, so an extension that
    never configured a policy gets review rather than a free pass.

    ``threshold`` only means anything when ``auto_accept`` is on.  A policy
    that auto-accepts with no threshold would accept everything, which is the
    silent write the gate exists to prevent.
    """

    auto_accept: bool = False
    threshold: float = DEFAULT_REVIEW_THRESHOLD
    #: Fields that may never be auto-accepted, whatever the confidence.
    #: Money, identity, anything an operator marks as consequential.
    never_auto: tuple[str, ...] = ()

    def decides(self, proposal: Proposal) -> str:
        """``"auto"``, ``"review"`` or ``"refuse"`` for *proposal*.

        ``"refuse"`` is for a proposal that touches a ``never_auto`` field
        while asking to be auto-accepted: the operator has said this field
        always needs a person, and a policy that contradicts that is a
        configuration error rather than a judgement call.
        """
        if not self.auto_accept:
            return "review"
        if proposal.confidence is None:
            return "review"
        touched = set(proposal.values) & set(self.never_auto)
        if touched:
            return "refuse"
        if proposal.confidence >= self.threshold:
            return "auto"
        return "review"


def input_digest(payload: Any) -> str:
    """A stable digest of the input a proposal was derived from.

    Used for idempotency: the same file content, the same record, the same
    prompt — the same digest, so a re-run updates rather than duplicates.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def review_reason(proposal: Proposal, policy: PromotionPolicy) -> str:
    """Why *proposal* is waiting for a person, in one readable sentence.

    Shown in the review queue beside the proposal.  A queue that says only
    "pending" teaches the reviewer nothing about what they are being asked
    to decide.
    """
    decision = policy.decides(proposal)
    if decision == "refuse":
        touched = ", ".join(sorted(set(proposal.values) & set(policy.never_auto)))
        return (
            f"Touches {touched}, which this site has marked as always needing "
            "a person — auto-accept is refused for it."
        )
    if proposal.confidence is None:
        return "The model gave no confidence, so this waits for a person."
    if decision == "auto":
        return (
            f"Confidence {proposal.confidence:.2f} meets the "
            f"{policy.threshold:.2f} threshold."
        )
    return (
        f"Confidence {proposal.confidence:.2f} is below the "
        f"{policy.threshold:.2f} threshold."
    )


def validate_proposal(proposal: Proposal) -> ProposalProblem | None:
    """Check a proposal before it is recorded.

    An empty ``values`` is refused: a proposal that would change nothing is
    either a bug or a way to smuggle a no-op past the review queue.  A
    confidence outside 0..1 is refused for the same reason a tier outside the
    vocabulary is — a number nobody can interpret disables every gate that
    keys on it.
    """
    if not proposal.values:
        return ProposalProblem("a proposal must name at least one field to change")
    if proposal.confidence is not None and not (0.0 <= proposal.confidence <= 1.0):
        return ProposalProblem(
            f"confidence {proposal.confidence} is outside 0.0–1.0"
        )
    if not proposal.doctype:
        return ProposalProblem("a proposal must name the DocType it targets")
    return None
