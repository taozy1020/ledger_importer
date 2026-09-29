"""The decision journal: what we proposed, and what the person did about it.

The ledger keeps the answer but not the question. Once a statement is imported
and deleted, nothing remains that explains why an account was chosen, so there
is nothing to learn from later. The journal keeps the question: the situation as
we saw it and the proposal we made, addressed by `event_id`.

The answer is harvested later from the ledger itself, by matching the same
`event_id` metadata. That join is what makes the loop tool independent: a person
may accept in Fava today and recategorize by hand in six months, and both are
visible to the next harvest.

Everything in this module is pure. Storage lives in `bean_import.journal`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from bean_import.core.advice import NO_ADVICE, Advice
from bean_import.core.situation import Situation

SCHEMA_VERSION = 1

FROM_UNKNOWN = "unknown"
FROM_HISTORY = "history"
FROM_MODEL = "model"

PENDING = "pending"
ACCEPTED = "accepted"
CORRECTED = "corrected"
ABSTAINED = "abstained"
SPLIT = "split"

OUTCOMES = (PENDING, ACCEPTED, CORRECTED, ABSTAINED, SPLIT)
LEARNABLE = (ACCEPTED, CORRECTED)


@dataclass(frozen=True, slots=True)
class Proposal:
    """What the import offered for the one account it could not derive."""

    account: str
    status: str
    origin: str
    confidence: float
    reason: str
    advice: Advice = NO_ADVICE


@dataclass(frozen=True, slots=True)
class Decision:
    """What the ledger says the person settled on."""

    outcome: str
    account: str
    observed_on: date

    @property
    def learnable(self) -> bool:
        return self.outcome in LEARNABLE


@dataclass(frozen=True, slots=True)
class LedgerOutcome:
    """The accounts a ledger transaction ended up with, for one `event_id`."""

    event_id: str
    accounts: tuple[str, ...]
    on: date


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One proposal, and the decision once it is known."""

    situation: Situation
    known_accounts: tuple[str, ...]
    allowed_accounts: tuple[str, ...]
    unknown_account: str
    proposal: Proposal
    recorded_on: date
    decision: Decision | None = None
    version: int = SCHEMA_VERSION

    @property
    def event_id(self) -> str:
        return self.situation.event_id

    @property
    def settled(self) -> bool:
        return self.decision is not None

    def with_decision(self, decision: Decision) -> JournalEntry:
        return replace(self, decision=decision)

    def label(self) -> str:
        """The account to learn from, or an empty string when there is none."""

        decision = self.decision
        if decision is None or not decision.learnable:
            return ""
        return decision.account


def merge(previous: JournalEntry | None, latest: JournalEntry) -> JournalEntry:
    """Reconcile two records of the same event, newest last.

    Re-importing the same folder is normal: Fava previews before it saves, and
    a person may re-run a batch months later. Until the ledger answers, the
    newest proposal wins.

    Once it has answered, the record is frozen. A re-import re-runs the whole
    pipeline, and by then the advisor has learned from that very answer, so it
    proposes the account the person chose — but nobody was ever shown that
    proposal, because Fava lists the row as a duplicate and it is never
    reviewed again. Letting it overwrite the original would grade us on an
    answer we already had, and every re-import would raise our score.
    """

    if previous is None or latest.decision is not None:
        return latest
    return previous if previous.decision is not None else latest


def judge(
    entry: JournalEntry,
    outcome: LedgerOutcome | None,
) -> Decision | None:
    """Compare a proposal with the ledger. `None` means the answer is not in yet.

    The contra account is whatever the ledger holds that the deterministic stage
    did not already put there. Anything other than exactly one such account is a
    split or a rewrite: a real human judgement, but not one a single-label
    learner can copy, so it is recorded and never trained on.
    """

    if outcome is None:
        return None
    known = set(entry.known_accounts)
    contra = tuple(account for account in outcome.accounts if account not in known)
    if len(contra) != 1:
        return Decision(SPLIT, "", outcome.on)
    final = contra[0]
    if final == entry.unknown_account:
        return Decision(ABSTAINED, final, outcome.on)
    if final == entry.proposal.account:
        return Decision(ACCEPTED, final, outcome.on)
    return Decision(CORRECTED, final, outcome.on)
