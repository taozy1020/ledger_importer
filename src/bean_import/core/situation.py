"""The features every later stage reasons over.

A classifier, the advisor, and the journal must all describe a transaction the
same way, otherwise what the model saw and what we later learn from drift apart.
`situation_of` is the single place where a raw request becomes those features.

Nothing here touches a file, a network, or the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from bean_import.core.classification import ClassificationRequest

WEEKDAYS = "一二三四五六日"
UNKNOWN_CLOCK = ""
UNKNOWN_DAY_PART = "时段未知"


@dataclass(frozen=True, slots=True)
class Situation:
    """One transaction as time, money, counterparty, and channel."""

    event_id: str
    kind: str
    role: str
    on: date
    clock: str
    weekday: int
    day_part: str
    is_weekend: bool
    amount: Decimal
    magnitude: Decimal
    currency: str
    payee: str
    narration: str
    source_category: str
    source_types: tuple[str, ...]
    tokens: frozenset[str]

    @property
    def weekday_name(self) -> str:
        return WEEKDAYS[self.weekday]

    @property
    def timed(self) -> bool:
        return self.clock != UNKNOWN_CLOCK


def situation_of(request: ClassificationRequest) -> Situation:
    """Derive the shared feature view of one classification request."""

    moment = _moment(request.occurred_at, request.transaction_date)
    timed = _clock(request.occurred_at.partition(" ")[2]) is not None
    return Situation(
        event_id=request.event_id,
        kind=request.kind,
        role=request.role,
        on=moment.date(),
        clock=moment.strftime("%H:%M") if timed else UNKNOWN_CLOCK,
        weekday=moment.weekday(),
        day_part=day_part(moment.hour) if timed else UNKNOWN_DAY_PART,
        is_weekend=moment.weekday() >= 5,
        amount=request.amount,
        magnitude=abs(request.amount),
        currency=request.currency,
        payee=request.payee,
        narration=request.narration,
        source_category=request.source_category,
        source_types=request.source_types,
        tokens=tokens_of(request.payee, request.narration, request.source_category),
    )


def day_part(hour: int) -> str:
    if hour < 5:
        return "深夜"
    if hour < 10:
        return "早晨"
    if hour < 14:
        return "中午"
    if hour < 17:
        return "下午"
    if hour < 21:
        return "晚上"
    return "深夜"


def tokens_of(*texts: str) -> frozenset[str]:
    """Split mixed Chinese and Latin text into comparable pieces.

    Latin runs become words; Chinese runs become character bigrams, so 瑞幸咖啡
    and 瑞幸咖啡(中关村店) still overlap without a segmentation dependency.
    """

    found: set[str] = set()
    for text in texts:
        for run, is_latin in _runs(text.casefold()):
            if is_latin:
                found.add(run)
            elif len(run) == 1:
                found.add(run)
            else:
                found.update(run[index : index + 2] for index in range(len(run) - 1))
    return frozenset(found)


def _runs(text: str) -> list[tuple[str, bool]]:
    runs: list[tuple[str, bool]] = []
    buffer = ""
    latin = False
    for character in text:
        if character.isalnum():
            is_latin = character.isascii()
            if buffer and is_latin != latin:
                runs.append((buffer, latin))
                buffer = ""
            latin = is_latin
            buffer += character
        elif buffer:
            runs.append((buffer, latin))
            buffer = ""
    if buffer:
        runs.append((buffer, latin))
    return runs


def _moment(occurred_at: str, fallback: date) -> datetime:
    text = occurred_at.strip()
    if not text:
        return datetime(fallback.year, fallback.month, fallback.day)
    date_part, _, time_part = text.partition(" ")
    try:
        day = date.fromisoformat(date_part)
    except ValueError:
        day = fallback
    clock = _clock(time_part)
    if clock is None:
        return datetime(day.year, day.month, day.day)
    return datetime(day.year, day.month, day.day, clock[0], clock[1])


def _clock(value: str) -> tuple[int, int] | None:
    digits = value.strip().replace(":", "")
    if len(digits) == 4 and digits.isdigit():
        digits = f"{digits}00"
    if len(digits) < 4 or not digits[:4].isdigit():
        return None
    hour = int(digits[0:2])
    minute = int(digits[2:4])
    if hour > 23 or minute > 59:
        return None
    return hour, minute
