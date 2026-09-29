"""What the model reads: a life skill, this moment, and what is remembered.

Not a payee-to-account table. A person does not classify by brand; they
classify by what they were doing. The skill is prose they wrote themselves, the
situation is the time and money of this transaction, and the memory is what
similar moments turned into before.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from beancount.core.data import Directive, Transaction

from bean_import.core.advice import Advice
from bean_import.core.situation import UNKNOWN_DAY_PART, WEEKDAYS, Situation

NO_MEMORY = "账本里还没有可回忆的分类。请根据生活说明和这笔交易的时间、金额和渠道判断。"


@dataclass(frozen=True, slots=True)
class LifeContext:
    """The three things put in front of the model, and nothing else."""

    skill: str
    situation: str
    memory: str


def describe_situation(situation: Situation) -> str:
    """Turn the shared feature view into the sentence the model reads."""

    clock = situation.clock or "时间未知"
    part = situation.day_part if situation.day_part != UNKNOWN_DAY_PART else "时段未知"
    return (
        f"{situation.on.isoformat()} 星期{WEEKDAYS[situation.weekday]} {clock}，"
        f"{part}，金额 {situation.amount} {situation.currency}。"
        f"对手：{situation.payee or '未知'}。"
        f"说明：{situation.narration or '无'}。"
        f"平台分类：{situation.source_category or '无'}。"
        f"渠道：{'、'.join(situation.source_types)}。"
    )


def memory_from_advice(advice: Advice) -> str:
    """Retrieved memory: the accounts similar moments actually became."""

    if not advice.candidates:
        return ""
    return "\n".join(
        f"{candidate.account}：{candidate.evidence}"
        f"（相似度权重 {candidate.confidence:.2f}）"
        for candidate in advice.candidates
    )


def memory_from_ledger(
    existing: Sequence[Directive],
    allowed_accounts: set[str],
    *,
    limit: int,
) -> str:
    """Cold-start memory, before the journal has settled anything.

    Coarser than retrieval: it describes each account as a whole rather than
    the moments that resemble this one.
    """

    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for entry in existing:
        if not isinstance(entry, Transaction):
            continue
        for posting in entry.postings:
            if posting.account in allowed_accounts:
                grouped[posting.account].append(entry)
                break
    if not grouped:
        return NO_MEMORY

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
