"""Render an accounting event and a validated suggestion as one transaction."""

from __future__ import annotations

from decimal import Decimal

from beancount.core.amount import Amount
from beancount.core.data import Posting, Transaction

from bean_import.classify import UNKNOWN, Classification
from bean_import.models import AccountingEvent


class RenderError(ValueError):
    """An event cannot be rendered as a balanced transaction."""


def render_event(
    event: AccountingEvent,
    classification: Classification | None,
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
    if reason:
        metadata["classification_reason"] = reason
    if event.link_candidates:
        metadata["link_candidates"] = ",".join(event.link_candidates)

    tags = frozenset(
        flag.replace("_", "-") for flag in event.flags if flag.replace("_", "-")
    )
    return Transaction(
        metadata,
        event.canonical_date,
        "*",
        event.payee or None,
        event.narration,
        tags,
        frozenset(),
        [
            Posting(account, Amount(amount, event.currency), None, None, None, None)
            for account, amount in amounts
        ],
    )
