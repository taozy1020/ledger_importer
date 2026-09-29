"""Rendering, and the metadata a reviewer reads before deciding."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bean_import.core.advice import Advice, Candidate
from bean_import.core.classification import accept, unknown
from bean_import.core.models import AccountingEvent
from bean_import.core.render import (
    ADVICE_FULL,
    ADVICE_NONE,
    RenderError,
    render_event,
)
from tests.helpers import accounts_of, make_request


def event(*, unresolved: bool = True) -> AccountingEvent:
    postings = (("Assets:Bank:BOC:Debit", Decimal("-32.00")),)
    if not unresolved:
        postings = (*postings, ("Liabilities:CreditCard:BOC", Decimal("32.00")))
    return AccountingEvent(
        event_id="event",
        kind="expense",
        evidence_ids=("alipay:1",),
        canonical_date=date(2026, 9, 1),
        currency="CNY",
        payee="瑞幸咖啡",
        narration="生椰拿铁",
        source_category="餐饮美食",
        source_types=("alipay",),
        postings=postings,
        unresolved_role="expense_account" if unresolved else None,
        link_candidates=(),
        flags=(),
        source_files=("alipay.csv",),
        row_numbers=(2,),
        occurred_at="2026-09-01 08:00:00",
    )


def advice() -> Advice:
    return Advice(
        (
            Candidate("Expenses:Food:Delivery", 0.62, 7, "7 笔相似记录；中午"),
            Candidate("Expenses:Food:Quick", 0.18, 2, "2 笔相似记录"),
        )
    )


def test_an_unknown_account_carries_the_candidates_that_explain_it() -> None:
    entry = render_event(event(), unknown(make_request(), "没启用模型"), advice())

    assert accounts_of(entry)["Expenses:Unknown"] == "32.00"
    assert entry.meta["candidates"] == (
        "Expenses:Food:Delivery 0.62 | Expenses:Food:Quick 0.18"
    )


def test_the_default_keeps_the_candidates_but_not_the_prose() -> None:
    entry = render_event(event(), unknown(make_request(), "没启用模型"), advice())

    assert "candidate_evidence" not in entry.meta
    assert "confidence" not in entry.meta


def test_why_we_abstained_is_boilerplate_but_why_a_model_chose_is_not() -> None:
    abstained = render_event(event(), unknown(make_request(), "没启用模型"))
    chosen = render_event(event(), accept("Expenses:Food:Quick", "简餐", "demo-model"))

    assert "classification_reason" not in abstained.meta
    assert chosen.meta["classification_reason"] == "简餐"


def test_the_ledger_can_ask_for_everything_or_for_nothing() -> None:
    request = unknown(make_request(), "没启用模型")

    verbose = render_event(event(), request, advice(), ADVICE_FULL)
    silent = render_event(event(), request, advice(), ADVICE_NONE)

    assert verbose.meta["candidate_evidence"] == "7 笔相似记录；中午"
    assert verbose.meta["confidence"] == "0.62"
    assert verbose.meta["classification_reason"] == "没启用模型"
    assert "candidates" not in silent.meta


def test_nothing_is_tagged_for_review_because_the_tag_would_go_stale() -> None:
    unresolved = render_event(event(), unknown(make_request(), "没启用模型"), advice())
    resolved = render_event(
        event(), accept("Expenses:Food:Quick", "简餐", "demo-model")
    )

    assert unresolved.tags == frozenset()
    assert accounts_of(resolved)["Expenses:Food:Quick"] == "32.00"
    assert resolved.meta["classification"] == "demo-model"
    assert resolved.meta["model_id"] == "demo-model"


def test_a_structural_event_needs_no_classification_at_all() -> None:
    entry = render_event(event(unresolved=False), None)

    assert entry.meta["classification"] == "structural"
    assert "confidence" not in entry.meta


def test_an_unresolved_event_without_a_classification_is_a_bug() -> None:
    with pytest.raises(RenderError, match="still needs an account"):
        render_event(event(), None)
