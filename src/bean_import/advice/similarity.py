"""How alike two situations are, as one number between 0 and 1.

Deliberately not a learned model. Every term is something a person can check
against their own memory of the transaction, which matters because the result
is shown to them while they decide.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from bean_import.core.situation import UNKNOWN_DAY_PART, Situation

AMOUNT_SPREAD = math.log(4.0)


@dataclass(frozen=True, slots=True)
class Weights:
    """Relative pull of each feature. Raising one lowers all the others."""

    payee: float = 4.0
    tokens: float = 3.0
    category: float = 1.5
    day_part: float = 1.0
    weekend: float = 0.5
    channel: float = 1.0
    amount: float = 1.5

    @property
    def total(self) -> float:
        return (
            self.payee
            + self.tokens
            + self.category
            + self.day_part
            + self.weekend
            + self.channel
            + self.amount
        )


DEFAULT_WEIGHTS = Weights()


@dataclass(frozen=True, slots=True)
class Similarity:
    """The score and the features that carried it, for the evidence line."""

    score: float
    reasons: tuple[str, ...] = field(default=())


def similarity(
    left: Situation,
    right: Situation,
    weights: Weights = DEFAULT_WEIGHTS,
) -> Similarity:
    """Score two situations, ignoring the accounts they ended up in."""

    reasons: list[str] = []
    earned = 0.0

    if left.payee and _fold(left.payee) == _fold(right.payee):
        earned += weights.payee
        reasons.append("对手相同")

    overlap = _jaccard(left.tokens, right.tokens)
    if overlap > 0.0:
        earned += weights.tokens * overlap
        if overlap >= 0.5:
            reasons.append("名称相近")

    if left.source_category and left.source_category == right.source_category:
        earned += weights.category
        reasons.append("平台分类相同")

    if left.day_part == right.day_part and left.day_part != UNKNOWN_DAY_PART:
        earned += weights.day_part
        reasons.append(left.day_part)

    if left.is_weekend == right.is_weekend:
        earned += weights.weekend
        reasons.append("周末" if left.is_weekend else "工作日")

    channels = _jaccard(frozenset(left.source_types), frozenset(right.source_types))
    earned += weights.channel * channels

    closeness = amount_closeness(left.magnitude, right.magnitude)
    earned += weights.amount * closeness
    if closeness >= 0.7:
        reasons.append("金额相当")

    return Similarity(earned / weights.total, tuple(reasons))


def amount_closeness(left: Decimal, right: Decimal) -> float:
    """1.0 for equal amounts, fading to 0.0 about four times apart."""

    if left <= 0 or right <= 0:
        return 1.0 if left == right else 0.0
    ratio = abs(math.log(float(left) / float(right)))
    return max(0.0, 1.0 - ratio / AMOUNT_SPREAD)


def decay(age_days: int, half_life_days: int) -> float:
    """Halve the weight of an example every `half_life_days`.

    Habits move. A lunch routine from two years ago should not outvote the one
    from last month just because it repeated more often back then.
    """

    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (max(0, age_days) / half_life_days)


def _fold(text: str) -> str:
    return "".join(
        character for character in text.casefold() if not character.isspace()
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0
