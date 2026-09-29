"""Scoring two situations against each other."""

from __future__ import annotations

from decimal import Decimal

from bean_import.advice.similarity import amount_closeness, decay, similarity
from tests.helpers import make_situation


def test_the_same_moment_scores_one() -> None:
    situation = make_situation()

    assert similarity(situation, situation).score == 1.0


def test_a_different_counterparty_at_a_different_hour_scores_low() -> None:
    lunch = make_situation()
    rent = make_situation(
        payee="房东",
        narration="房租",
        amount="-3200.00",
        occurred_at="2026-09-05 22:00:00",
        source_category="生活服务",
    )

    assert similarity(lunch, rent).score < 0.2


def test_the_same_shop_at_a_different_hour_still_resembles_itself() -> None:
    morning = make_situation()
    evening = make_situation(occurred_at="2026-09-01 19:30:00")

    match = similarity(morning, evening)

    assert 0.6 < match.score < 1.0
    assert "对手相同" in match.reasons


def test_the_reasons_are_the_words_shown_to_the_reviewer() -> None:
    match = similarity(make_situation(), make_situation())

    assert "对手相同" in match.reasons
    assert "早晨" in match.reasons
    assert "工作日" in match.reasons
    assert "金额相当" in match.reasons


def test_amounts_fade_with_the_ratio_not_the_difference() -> None:
    assert amount_closeness(Decimal("32"), Decimal("32")) == 1.0
    assert amount_closeness(Decimal("32"), Decimal("128")) == 0.0
    assert 0.4 < amount_closeness(Decimal("32"), Decimal("64")) < 0.6
    assert amount_closeness(Decimal("0"), Decimal("32")) == 0.0


def test_habits_age_out_by_halves() -> None:
    assert decay(0, 180) == 1.0
    assert decay(180, 180) == 0.5
    assert decay(360, 180) == 0.25
    assert decay(1000, 0) == 1.0
