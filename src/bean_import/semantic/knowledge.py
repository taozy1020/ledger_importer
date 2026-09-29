"""Life-context skill plus situation and memory extracted for each transaction."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from beancount.core.data import Directive, Transaction

from bean_import.classify import ClassificationRequest

WEEKDAYS = "一二三四五六日"


@dataclass(frozen=True, slots=True)
class LifeContext:
    """What the model should read instead of a payee-to-account table."""

    skill: str
    situation: str
    memory: str


def describe_situation(request: ClassificationRequest) -> str:
    """Turn one request into the time, money, and channel the model reasons over."""

    moment = _moment(request.occurred_at, request.transaction_date)
    weekday = WEEKDAYS[moment.weekday()]
    timed = _has_clock(request.occurred_at)
    clock = moment.strftime("%H:%M") if timed else "时间未知"
    day_part = _day_part(moment.hour) if timed else "时段未知"
    return (
        f"{moment.date().isoformat()} 星期{weekday} {clock}，{day_part}，"
        f"金额 {request.amount} {request.currency}。"
        f"对手：{request.payee or '未知'}。"
        f"说明：{request.narration or '无'}。"
        f"平台分类：{request.source_category or '无'}。"
        f"渠道：{'、'.join(request.source_types)}。"
    )


def memory_from_ledger(
    existing: Sequence[Directive],
    allowed_accounts: set[str],
    *,
    limit: int,
) -> str:
    """Summarize how this person has actually lived in the ledger so far."""

    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for entry in existing:
        if not isinstance(entry, Transaction):
            continue
        for posting in entry.postings:
            if posting.account in allowed_accounts:
                grouped[posting.account].append(entry)
                break
    if not grouped:
        return (
            "账本里还没有可回忆的分类。请根据生活说明和这笔交易的时间、金额和渠道判断。"
        )

    lines: list[str] = []
    ranked = sorted(grouped, key=lambda account: len(grouped[account]), reverse=True)
    for account in ranked[:limit]:
        entries = grouped[account]
        amounts: list[Decimal] = []
        for entry in entries:
            for posting in entry.postings:
                units = posting.units
                number = units.number if units is not None else None
                if posting.account == account and number is not None:
                    amounts.append(abs(number))
        weekdays = sorted({WEEKDAYS[entry.date.weekday()] for entry in entries})
        remembered = _remembered_names(entries)
        amount_text = _amount_span(amounts)
        lines.append(
            f"{account}：{len(entries)} 笔，{amount_text}，"
            f"出现在星期{'、'.join(weekdays)}。记得：{remembered}。"
        )
    return "\n".join(lines)


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


def _has_clock(occurred_at: str) -> bool:
    _, _, time_part = occurred_at.partition(" ")
    return _clock(time_part) is not None


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


def _day_part(hour: int) -> str:
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


def _remembered_names(entries: Sequence[Transaction]) -> str:
    names: list[str] = []
    for entry in entries:
        name = entry.payee or entry.narration or ""
        if name and name not in names:
            names.append(name)
        if len(names) == 3:
            break
    return "、".join(names) if names else "没有留下对手名称"


def _amount_span(amounts: Sequence[Decimal]) -> str:
    if not amounts:
        return "金额不明"
    low = min(amounts)
    high = max(amounts)
    if low == high:
        return f"金额 {low}"
    return f"金额大约 {low}–{high}"
