"""Run adapters, normalization, and semantic classification as one import."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from beancount.core.data import Directive, Open, Transaction

from bean_import.classify import (
    ClassificationRequest,
    KnowledgeClassifier,
    OpenAICompatibleClassifier,
    SemanticClassifier,
    allowed_accounts_for,
)
from bean_import.customer_config import CustomerConfig
from bean_import.knowledge import (
    KnowledgeExample,
    examples_from_ledger,
    select_examples,
    select_guides,
)
from bean_import.models import AccountingEvent
from bean_import.normalize import normalize
from bean_import.render import render_event
from bean_import.sources import read_platform_file


def build_classifier(config: CustomerConfig) -> SemanticClassifier:
    """Use the knowledge base alone until the customer sets an endpoint."""

    if not config.endpoint:
        return KnowledgeClassifier()
    api_key = os.environ.get(config.api_key_env, "")
    return OpenAICompatibleClassifier(config.endpoint, config.model, api_key)


def import_files(
    paths: Sequence[str | Path],
    config: CustomerConfig,
    existing: Sequence[Directive] = (),
    classifier: SemanticClassifier | None = None,
) -> list[Transaction]:
    """Parse every statement in the batch and return balanced transactions."""

    records = [record for path in paths for record in read_platform_file(path, config)]
    events = normalize(records, config)
    chosen = classifier or build_classifier(config)
    allowed = set(config.expense_accounts) | set(config.income_accounts)
    ledger_examples = examples_from_ledger(existing, allowed)
    opened = {entry.account for entry in existing if isinstance(entry, Open)}
    return [
        render_event(event, None)
        if event.unresolved_role is None
        else render_event(
            event,
            chosen.classify(_request(event, config, ledger_examples, opened)),
        )
        for event in events
    ]


def _request(
    event: AccountingEvent,
    config: CustomerConfig,
    ledger_examples: tuple[KnowledgeExample, ...],
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
    suspense = (
        config.suspense_income
        if event.unresolved_role == "income_account"
        else config.suspense_expense
    )
    return ClassificationRequest(
        event_id=event.event_id,
        kind=event.kind,
        role=event.unresolved_role,
        transaction_date=event.canonical_date,
        amount=event.postings[0][1],
        currency=event.currency,
        payee=event.payee,
        narration=event.narration,
        source_category=event.source_category,
        source_types=event.source_types,
        allowed_accounts=allowed,
        suspense_account=suspense if suspense in allowed else allowed[0],
        examples=select_examples(
            payee=event.payee,
            narration=event.narration,
            source_category=event.source_category,
            curated=config.examples,
            ledger=ledger_examples,
            limit=config.max_examples,
        ),
        guides=select_guides(
            payee=event.payee,
            narration=event.narration,
            source_category=event.source_category,
            guides=config.guides,
        ),
    )
