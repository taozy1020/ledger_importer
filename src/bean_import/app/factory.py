"""Build the parts an import needs, from configuration alone.

This is the only module allowed to name more than one adapter. Everything it
returns is behind a protocol, so a test or an experiment can hand the pipeline
a different set without touching the pipeline.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from beancount.core.data import Directive

from bean_import.advice.classifier import HistoryClassifier
from bean_import.advice.history import AdvicePolicy, HistoryAdvisor, NullAdvisor
from bean_import.clock import SystemClock
from bean_import.config.customer import CustomerConfig
from bean_import.core.classifiers import FirstResolved, UnknownClassifier
from bean_import.core.ports import (
    AccountAdvisor,
    Clock,
    DecisionJournal,
    SemanticClassifier,
)
from bean_import.journal.jsonl import JsonlJournal
from bean_import.journal.memory import NullJournal


@dataclass(frozen=True, slots=True)
class Components:
    """Everything the pipeline talks to, assembled once per run."""

    classifier: SemanticClassifier
    advisor: AccountAdvisor
    journal: DecisionJournal
    clock: Clock


def build_components(
    config: CustomerConfig,
    existing: Sequence[Directive] = (),
    *,
    clock: Clock | None = None,
) -> Components:
    """Assemble the default stack for one ledger."""

    ticking = clock or SystemClock()
    journal = build_journal(config)
    advisor = build_advisor(config, journal, ticking)
    return Components(
        classifier=build_classifier(config, existing),
        advisor=advisor,
        journal=journal,
        clock=ticking,
    )


def build_journal(config: CustomerConfig) -> DecisionJournal:
    """A file journal unless the ledger turned recording off."""

    if not config.journal.enabled:
        return NullJournal()
    return JsonlJournal(config.journal.path)


def build_advisor(
    config: CustomerConfig,
    journal: DecisionJournal,
    clock: Clock,
) -> AccountAdvisor:
    """History advice, or silence when nothing is being recorded."""

    if not config.journal.enabled:
        return NullAdvisor()
    return HistoryAdvisor(journal, clock, advice_policy(config))


def advice_policy(config: CustomerConfig) -> AdvicePolicy:
    settings = config.advice
    return AdvicePolicy(
        half_life_days=settings.half_life_days,
        max_candidates=settings.max_candidates,
        min_similarity=settings.min_similarity,
        min_support=settings.min_support,
        correction_weight=settings.correction_weight,
        acceptance_weight=settings.acceptance_weight,
    )


def build_classifier(
    config: CustomerConfig,
    existing: Sequence[Directive] = (),
) -> SemanticClassifier:
    """Chain whatever the ledger enabled, ending in the honest unknown.

    Milestone 1 configures neither history auto-accept nor a model, so the
    chain is one link long and no `bean_import.semantic` import ever happens.
    """

    chain: list[SemanticClassifier] = []
    if config.advice.auto_accept_above > 0.0:
        chain.append(HistoryClassifier(config.advice.auto_accept_above))
    model = _model_classifier(config, existing)
    if model is not None:
        chain.append(model)
    chain.append(UnknownClassifier())
    if len(chain) == 1:
        return chain[0]
    return FirstResolved(*chain)


def _model_classifier(
    config: CustomerConfig,
    existing: Sequence[Directive],
) -> SemanticClassifier | None:
    semantic = config.semantic
    if semantic is None:
        return None

    from bean_import.semantic import OpenAICompatibleClassifier, memory_from_ledger

    allowed = set(config.expense_accounts) | set(config.income_accounts)
    return OpenAICompatibleClassifier(
        semantic.endpoint,
        semantic.model,
        os.environ.get(semantic.api_key_env, ""),
        skill=semantic.skill_text,
        memory=memory_from_ledger(existing, allowed, limit=semantic.max_memories),
    )
