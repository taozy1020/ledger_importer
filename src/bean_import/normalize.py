"""Pair source rows into accounting events before any semantic classification."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from decimal import Decimal

from bean_import.customer_config import CustomerConfig
from bean_import.models import AccountingEvent, AccountRole, EventKind, SourceRecord

CHANNEL_KEYWORDS = ("支付宝", "微信", "财付通", "快捷支付")
PairPredicate = Callable[[SourceRecord, SourceRecord, int], bool]


class NormalizeError(ValueError):
    """Source rows cannot be assembled into accounting events."""


def normalize(
    records: Sequence[SourceRecord],
    config: CustomerConfig,
) -> list[AccountingEvent]:
    """Merge unique card payments, repayments, and transfers; keep the rest."""

    _reject_duplicate_ids(records)
    consumed: set[str] = set()
    ambiguous: dict[str, set[str]] = defaultdict(set)
    events: list[AccountingEvent] = []

    remaining = list(records)
    events.extend(
        _consume_pairs(
            remaining,
            consumed,
            ambiguous,
            config.date_window_days,
            _repayment_pair,
            _repayment_event,
        )
    )
    remaining = [record for record in remaining if record.source_id not in consumed]
    events.extend(
        _consume_pairs(
            remaining,
            consumed,
            ambiguous,
            config.date_window_days,
            _card_payment_pair,
            _card_payment_event,
        )
    )
    remaining = [record for record in remaining if record.source_id not in consumed]
    events.extend(
        _consume_pairs(
            remaining,
            consumed,
            ambiguous,
            config.date_window_days,
            _transfer_pair,
            _transfer_event,
        )
    )

    for record in remaining:
        if record.source_id in consumed:
            continue
        candidates = tuple(sorted(ambiguous.get(record.source_id, ())))
        structural = bool(record.counter_account) and not candidates
        events.append(_single_event(record, candidates, structural))

    events.sort(key=lambda event: (event.canonical_date, event.event_id))
    return events


def _consume_pairs(
    records: Sequence[SourceRecord],
    consumed: set[str],
    ambiguous: dict[str, set[str]],
    window: int,
    predicate: PairPredicate,
    build: Callable[[SourceRecord, SourceRecord], AccountingEvent],
) -> list[AccountingEvent]:
    available = [record for record in records if record.source_id not in consumed]
    pairs = [
        (left, right)
        for index, left in enumerate(available)
        for right in available[index + 1 :]
        if predicate(left, right, window)
    ]
    left_counts = Counter(left.source_id for left, _ in pairs)
    right_counts = Counter(right.source_id for _, right in pairs)
    events: list[AccountingEvent] = []
    for left, right in pairs:
        unique = left_counts[left.source_id] == 1 and right_counts[right.source_id] == 1
        fresh = left.source_id not in consumed and right.source_id not in consumed
        if unique and fresh:
            consumed.add(left.source_id)
            consumed.add(right.source_id)
            events.append(build(left, right))
            continue
        if left.source_id in consumed or right.source_id in consumed:
            continue
        ambiguous[left.source_id].add(right.source_id)
        ambiguous[right.source_id].add(left.source_id)
    return events


def _repayment_pair(left: SourceRecord, right: SourceRecord, window: int) -> bool:
    debit, credit = (left, right) if left.source_type == "boc_debit" else (right, left)
    if debit.source_type != "boc_debit" or credit.source_type != "boc_credit":
        return False
    if debit.amount >= 0 or credit.amount != -debit.amount:
        return False
    if not _within_window(debit, credit, window):
        return False
    return "还款" in _text(debit, credit)


def _card_payment_pair(left: SourceRecord, right: SourceRecord, window: int) -> bool:
    wallet, bank = (
        (left, right) if left.source_type in {"alipay", "wechat"} else (right, left)
    )
    if wallet.source_type not in {"alipay", "wechat"}:
        return False
    if bank.source_type not in {"boc_debit", "boc_credit"}:
        return False
    if wallet.counter_account or not wallet.card_tail:
        return False
    if wallet.amount != bank.amount or wallet.currency != bank.currency:
        return False
    if not _within_window(wallet, bank, window):
        return False
    if "还款" in _text(bank):
        return False
    same_account = wallet.source_account == bank.source_account
    same_tail = bool(bank.card_tail) and wallet.card_tail == bank.card_tail
    keyword = any(token in _text(bank) for token in CHANNEL_KEYWORDS)
    return (same_account or same_tail) and (keyword or same_tail)


def _transfer_pair(left: SourceRecord, right: SourceRecord, window: int) -> bool:
    origin, other = (left, right) if left.counter_account else (right, left)
    if not origin.counter_account or other.counter_account:
        return False
    return (
        other.source_account == origin.counter_account
        and other.amount == -origin.amount
        and other.currency == origin.currency
        and _within_window(origin, other, window)
    )


def _repayment_event(debit: SourceRecord, credit: SourceRecord) -> AccountingEvent:
    if debit.source_type != "boc_debit":
        debit, credit = credit, debit
    return _event(
        kind="repayment",
        records=(debit, credit),
        payee=debit.payee or credit.payee,
        narration="信用卡还款",
        category=debit.category or credit.category,
        postings=(
            (debit.source_account, debit.amount),
            (credit.source_account, credit.amount),
        ),
        role=None,
        canonical=debit,
    )


def _card_payment_event(wallet: SourceRecord, bank: SourceRecord) -> AccountingEvent:
    if wallet.source_type not in {"alipay", "wechat"}:
        wallet, bank = bank, wallet
    kind, role = _kind_for(bank.amount, _text(wallet, bank))
    return _event(
        kind=kind,
        records=(bank, wallet),
        payee=wallet.payee or bank.payee,
        narration=wallet.narration or bank.narration,
        category=wallet.category or bank.category,
        postings=((bank.source_account, bank.amount),),
        role=role,
        canonical=bank,
    )


def _transfer_event(origin: SourceRecord, other: SourceRecord) -> AccountingEvent:
    if not origin.counter_account:
        origin, other = other, origin
    return _event(
        kind="transfer",
        records=(origin, other),
        payee=origin.payee or other.payee,
        narration=origin.narration or other.narration,
        category=origin.category,
        postings=(
            (origin.source_account, origin.amount),
            (origin.counter_account, -origin.amount),
        ),
        role=None,
        canonical=origin,
    )


def _single_event(
    record: SourceRecord,
    link_candidates: tuple[str, ...],
    structural_transfer: bool,
) -> AccountingEvent:
    if structural_transfer:
        kind: EventKind = "transfer"
        role = None
        postings = (
            (record.source_account, record.amount),
            (record.counter_account, -record.amount),
        )
    else:
        kind, role = _kind_for(record.amount, _text(record))
        postings = ((record.source_account, record.amount),)
    return _event(
        kind=kind,
        records=(record,),
        payee=record.payee,
        narration=record.narration,
        category=record.category,
        postings=postings,
        role=role,
        canonical=record,
        link_candidates=link_candidates,
    )


def _event(
    *,
    kind: EventKind,
    records: tuple[SourceRecord, ...],
    payee: str,
    narration: str,
    category: str,
    postings: tuple[tuple[str, Decimal], ...],
    role: AccountRole | None,
    canonical: SourceRecord,
    link_candidates: tuple[str, ...] = (),
) -> AccountingEvent:
    evidence_ids = tuple(record.source_id for record in records)
    flags = ("ambiguous_link",) if link_candidates else ()
    return AccountingEvent(
        event_id=_event_id(evidence_ids),
        kind=kind,
        evidence_ids=evidence_ids,
        canonical_date=canonical.transaction_date,
        currency=canonical.currency,
        payee=payee,
        narration=narration or payee or kind,
        source_category=category,
        source_types=tuple(record.source_type for record in records),
        postings=postings,
        unresolved_role=role,
        link_candidates=link_candidates,
        flags=flags,
        source_files=tuple(record.source_file for record in records),
        row_numbers=tuple(record.row_number for record in records),
        occurred_at=_occurred_at(records),
    )


def _occurred_at(records: tuple[SourceRecord, ...]) -> str:
    timed = [record.occurred_at for record in records if ":" in record.occurred_at]
    if timed:
        return max(timed, key=len)
    for record in records:
        if record.occurred_at:
            return record.occurred_at
    return ""


def _kind_for(amount: Decimal, text: str) -> tuple[EventKind, AccountRole | None]:
    if amount == 0:
        raise NormalizeError("Zero-amount rows are not importable")
    if "退款" in text:
        return "refund", "expense_account"
    if amount < 0:
        return "expense", "expense_account"
    return "income", "income_account"


def _within_window(left: SourceRecord, right: SourceRecord, window: int) -> bool:
    return abs((left.transaction_date - right.transaction_date).days) <= window


def _text(*records: SourceRecord) -> str:
    return " ".join(
        f"{record.payee} {record.narration} {record.category} {record.status} "
        f"{record.funding_method}"
        for record in records
    )


def _event_id(evidence_ids: tuple[str, ...]) -> str:
    payload = "\n".join(sorted(evidence_ids)) + "\nnormalizer-v1"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reject_duplicate_ids(records: Sequence[SourceRecord]) -> None:
    counts = Counter(record.source_id for record in records)
    duplicates = sorted(source_id for source_id, count in counts.items() if count > 1)
    if duplicates:
        raise NormalizeError(f"Duplicate source IDs: {', '.join(duplicates)}")
