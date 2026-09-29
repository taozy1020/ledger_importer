"""One import, from statement files to transactions, with the journal written.

The order is fixed and each step is replaceable:

    read -> normalize -> advise -> classify -> render -> record

Everything before `advise` is deterministic and cannot be influenced by memory
or a model. Everything after is an opinion, and every opinion is written down
so it can be compared with what the person does next.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from beancount.core.data import Directive, Open, Transaction

from bean_import.config.customer import CustomerConfig
from bean_import.core.advice import Advice
from bean_import.core.classification import (
    Classification,
    ClassificationRequest,
    allowed_accounts_for,
)
from bean_import.core.journal import (
    FROM_UNKNOWN,
    JournalEntry,
    Proposal,
)
from bean_import.core.models import AccountingEvent
from bean_import.core.normalize import normalize
from bean_import.core.render import render_event
from bean_import.core.situation import Situation, situation_of
from bean_import.sources import read_platform_file

from .factory import Components, build_components


def import_files(
    paths: Sequence[str | Path],
    config: CustomerConfig,
    existing: Sequence[Directive] = (),
    components: Components | None = None,
) -> list[Transaction]:
    """Parse every statement in the batch and return balanced transactions."""

    parts = components or build_components(config, existing)
    records = [record for path in paths for record in read_platform_file(path, config)]
    events = normalize(records, date_window_days=config.date_window_days)
    opened = {entry.account for entry in existing if isinstance(entry, Open)}

    rendered: list[Transaction] = []
    for event in events:
        if event.unresolved_role is None:
            rendered.append(render_event(event, None))
            continue
        request = _request(event, config, opened)
        situation = situation_of(request)
        advice = parts.advisor.advise(situation, request.allowed_accounts)
        classification = parts.classifier.classify(request, advice)
        rendered.append(
            render_event(event, classification, advice, config.advice.metadata)
        )
        parts.journal.record(
            _journal_entry(request, situation, advice, classification, parts)
        )
    return rendered


def _journal_entry(
    request: ClassificationRequest,
    situation: Situation,
    advice: Advice,
    classification: Classification,
    parts: Components,
) -> JournalEntry:
    return JournalEntry(
        situation=situation,
        known_accounts=request.known_accounts,
        allowed_accounts=request.allowed_accounts,
        unknown_account=request.unknown_account,
        proposal=Proposal(
            account=classification.account,
            status=classification.status,
            origin=classification.model_id or FROM_UNKNOWN,
            confidence=advice.confidence,
            reason=classification.reason,
            advice=advice,
        ),
        recorded_on=parts.clock.today(),
    )


def _request(
    event: AccountingEvent,
    config: CustomerConfig,
    opened: set[str],
) -> ClassificationRequest:
    assert event.unresolved_role is not None
    configured = allowed_accounts_for(
        event.unresolved_role,
        config.expense_accounts,
        config.income_accounts,
    )
    opened_allowed = tuple(account for account in configured if account in opened)
    allowed = opened_allowed or configured
    fallback = (
        config.unknown_income
        if event.unresolved_role == "income_account"
        else config.unknown_expense
    )
    if fallback not in allowed:
        allowed = (*allowed, fallback)
    return ClassificationRequest(
        event_id=event.event_id,
        kind=event.kind,
        role=event.unresolved_role,
        transaction_date=event.canonical_date,
        occurred_at=event.occurred_at,
        amount=event.postings[0][1],
        currency=event.currency,
        payee=event.payee,
        narration=event.narration,
        source_category=event.source_category,
        source_types=event.source_types,
        allowed_accounts=allowed,
        unknown_account=fallback,
        known_accounts=tuple(account for account, _ in event.postings),
    )
