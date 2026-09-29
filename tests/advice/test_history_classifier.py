"""Letting history fill an account in, only when the ledger asked for it."""

from __future__ import annotations

import pytest

from bean_import.advice.classifier import HISTORY_MODEL_ID, HistoryClassifier
from bean_import.core.advice import NO_ADVICE, Advice, Candidate
from tests.helpers import make_request


def advice(account: str, confidence: float) -> Advice:
    return Advice((Candidate(account, confidence, 5, "5 笔相似记录"),))


def test_strong_evidence_is_accepted_and_says_where_it_came_from() -> None:
    result = HistoryClassifier(0.6).classify(
        make_request(), advice("Expenses:Food:Quick", 0.8)
    )

    assert result.resolved is True
    assert result.account == "Expenses:Food:Quick"
    assert result.model_id == HISTORY_MODEL_ID
    assert "5 笔相似记录" in result.reason


def test_weak_evidence_is_left_to_the_person() -> None:
    result = HistoryClassifier(0.6).classify(
        make_request(), advice("Expenses:Food:Quick", 0.4)
    )

    assert result.resolved is False
    assert result.account == "Expenses:Unknown"


def test_no_advice_at_all_is_not_a_reason_to_guess() -> None:
    result = HistoryClassifier(0.6).classify(make_request(), NO_ADVICE)

    assert result.resolved is False


def test_a_candidate_outside_the_allowlist_is_refused() -> None:
    result = HistoryClassifier(0.6).classify(
        make_request(), advice("Expenses:Retired", 0.9)
    )

    assert result.resolved is False
    assert "不在允许列表" in result.reason


def test_a_threshold_of_zero_would_mean_always_guessing_so_it_is_rejected() -> None:
    with pytest.raises(ValueError, match="inside"):
        HistoryClassifier(0.0)
