"""Feature extraction: every later stage depends on these being stable."""

from __future__ import annotations

from bean_import.core.situation import (
    UNKNOWN_CLOCK,
    UNKNOWN_DAY_PART,
    day_part,
    situation_of,
    tokens_of,
)
from tests.helpers import make_request


def test_a_timestamp_becomes_weekday_clock_and_day_part() -> None:
    situation = situation_of(make_request(occurred_at="2026-09-01 08:00:00"))

    assert situation.weekday_name == "二"
    assert situation.clock == "08:00"
    assert situation.day_part == "早晨"
    assert situation.is_weekend is False
    assert situation.timed is True


def test_a_missing_clock_is_said_out_loud_instead_of_assumed() -> None:
    situation = situation_of(make_request(occurred_at="2026-09-05"))

    assert situation.clock == UNKNOWN_CLOCK
    assert situation.day_part == UNKNOWN_DAY_PART
    assert situation.timed is False
    assert situation.is_weekend is True


def test_the_amount_keeps_its_sign_and_gains_a_magnitude() -> None:
    situation = situation_of(make_request(amount="-32.00"))

    assert str(situation.amount) == "-32.00"
    assert str(situation.magnitude) == "32.00"


def test_day_parts_cover_the_whole_clock() -> None:
    assert [day_part(hour) for hour in (2, 7, 12, 15, 19, 23)] == [
        "深夜",
        "早晨",
        "中午",
        "下午",
        "晚上",
        "深夜",
    ]


def test_chinese_names_overlap_through_bigrams_without_a_segmenter() -> None:
    left = tokens_of("瑞幸咖啡")
    right = tokens_of("瑞幸咖啡(中关村店)")

    assert left <= right
    assert "瑞幸" in left
    assert tokens_of("Luckin Coffee") == {"luckin", "coffee"}
    assert tokens_of("") == frozenset()
