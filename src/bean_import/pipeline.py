"""Compose adapters, normalization, and one classifier into a single import.

This is the only module that knows both layers. Everything up to `render_event`
is deterministic; the classifier is whatever implements `SemanticClassifier`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from beancount.core.data import Directive, Open, Transaction

from bean_import.classify import (
    ClassificationRequest,
    SemanticClassifier,
    UnknownClassifier,
    allowed_accounts_for,
)
from bean_import.customer_config import CustomerConfig
from bean_import.models import AccountingEvent
from bean_import.normalize import normalize
from bean_import.render import render_event
from bean_import.sources import read_platform_file


def build_classifier(
    config: CustomerConfig,
    existing: Sequence[Directive] = (),
) -> SemanticClassifier:
    """Stay on milestone 1 until the ledger configures a `[semantic]` model."""

    semantic = config.semantic
    if semantic is None:
        return UnknownClassifier()

    from bean_import.semantic import OpenAICompatibleClassifier, memory_from_ledger

    allowed = set(config.expense_accounts) | set(config.income_accounts)
    return OpenAICompatibleClassifier(
        semantic.endpoint,
        semantic.model,
        os.environ.get(semantic.api_key_env, ""),
        skill=semantic.skill_text,
        memory=memory_from_ledger(existing, allowed, limit=semantic.max_memories),
    )


def import_files(
    paths: Sequence[str | Path],
    config: CustomerConfig,
    existing: Sequence[Directive] = (),
    classifier: SemanticClassifier | None = None,
) -> list[Transaction]:
    """Parse every statement in the batch and return balanced transactions."""

    records = [record for path in paths for record in read_platform_file(path, config)]
    events = normalize(records, config)
    chosen = classifier or build_classifier(config, existing)
    opened = {entry.account for entry in existing if isinstance(entry, Open)}
    return [
        render_event(event, None)
        if event.unresolved_role is None
        else render_event(event, chosen.classify(_request(event, config, opened)))
        for event in events
    ]


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
        unknown_account=fallback if fallback in allowed else allowed[0],
    )
