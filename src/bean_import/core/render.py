"""Render an accounting event, a classification, and the advice as one entry.

The metadata is the review surface. When an account was left unknown, the entry
has to carry enough for a person to decide in Fava without reopening the
statement: what we considered, how strongly, and why.

Everything written here is permanent. Fava saves the entry exactly as the
reviewer sees it, so advice that was only useful for one decision would sit in
the ledger forever. `detail` is how much of it the ledger is willing to keep.
Why we abstained is boilerplate repeated on every row and is dropped unless
asked for; why a model chose a particular account is not, and always stays.

There is no `#needs-review` tag: a tag written at import time cannot know that
the person fixed the account in the same breath, whereas filtering on the
unknown account itself is always true.
"""

from __future__ import annotations

from decimal import Decimal

from beancount.core.amount import Amount
from beancount.core.data import Posting, Transaction

from bean_import.core.advice import NO_ADVICE, Advice
from bean_import.core.classification import UNKNOWN, Classification
from bean_import.core.models import AccountingEvent

EVENT_ID = "event_id"
"""The join key. Written here, read back by `learning`, never rewritten."""

ADVICE_NONE = "none"
ADVICE_SHORT = "short"
ADVICE_FULL = "full"
ADVICE_DETAIL = (ADVICE_NONE, ADVICE_SHORT, ADVICE_FULL)


class RenderError(ValueError):
    """An event cannot be rendered as a balanced transaction."""


def render_event(
    event: AccountingEvent,
    classification: Classification | None,
    advice: Advice = NO_ADVICE,
    detail: str = ADVICE_SHORT,
) -> Transaction:
    """Create postings from known amounts, filling one contra account at most."""

    amounts = list(event.postings)
    label = "structural"
    reason = ""
    model_id = ""
    if event.unresolved_role is not None:
        if classification is None:
            raise RenderError(f"{event.event_id} still needs an account")
        total = sum((amount for _, amount in amounts), start=Decimal("0"))
        amounts.append((classification.account, -total))
        label = UNKNOWN if classification.status == UNKNOWN else classification.model_id
        reason = classification.reason
        model_id = classification.model_id

    balance = sum((amount for _, amount in amounts), start=Decimal("0"))
    if balance != 0:
        raise RenderError(f"{event.event_id} does not balance")

    metadata: dict[str, str | int] = {
        "filename": event.source_files[0] if event.source_files else "",
        "lineno": event.row_numbers[0] if event.row_numbers else 0,
        "event_id": event.event_id,
        "event_kind": event.kind,
        "source_id": ",".join(event.evidence_ids),
        "source_category": event.source_category,
        "classification": label,
    }
    if model_id:
        metadata["model_id"] = model_id
    if reason and (model_id or detail == ADVICE_FULL):
        metadata["classification_reason"] = reason
    if advice.candidates and detail != ADVICE_NONE:
        metadata["candidates"] = advice.render()
        if detail == ADVICE_FULL:
            metadata["confidence"] = f"{advice.confidence:.2f}"
            evidence = advice.evidence()
            if evidence:
                metadata["candidate_evidence"] = evidence
    if event.link_candidates:
        metadata["link_candidates"] = ",".join(event.link_candidates)

    tags = {flag.replace("_", "-") for flag in event.flags if flag.replace("_", "-")}
    return Transaction(
        metadata,
        event.canonical_date,
        "*",
        event.payee or None,
        event.narration,
        frozenset(tags),
        frozenset(),
        [
            Posting(account, Amount(amount, event.currency), None, None, None, None)
            for account, amount in amounts
        ],
    )
