"""Builders shared by the test tree.

Tests should say what is different about their case and nothing else, so the
defaults here are one concrete transaction: a 32 CNY coffee bought with Alipay
on a Tuesday morning.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from beancount.core.amount import Amount
from beancount.core.data import Posting, Transaction

from bean_import.core.advice import NO_ADVICE, Advice
from bean_import.core.classification import ClassificationRequest
from bean_import.core.journal import ACCEPTED, Decision, JournalEntry, Proposal
from bean_import.core.situation import Situation, situation_of

PROTOTYPE = Path(__file__).resolve().parents[1] / "examples" / "prototype"
STATEMENTS = PROTOTYPE / "statements"
LEDGER = PROTOTYPE / "ledger.toml"
LEDGER_WITH_MODEL = PROTOTYPE / "ledger-with-model.toml"

UNKNOWN_EXPENSE = "Expenses:Unknown"
ALLOWED = (
    "Expenses:Food:Delivery",
    "Expenses:Food:Quick",
    UNKNOWN_EXPENSE,
)


def make_request(
    *,
    event_id: str = "event",
    payee: str = "瑞幸咖啡",
    narration: str = "生椰拿铁",
    amount: str = "-32.00",
    occurred_at: str = "2026-09-01 08:00:00",
    source_category: str = "餐饮美食",
    source_types: tuple[str, ...] = ("alipay",),
    allowed_accounts: tuple[str, ...] = ALLOWED,
    role: str = "expense_account",
    kind: str = "expense",
) -> ClassificationRequest:
    return ClassificationRequest(
        event_id=event_id,
        kind=kind,
        role=role,
        transaction_date=date.fromisoformat(occurred_at.split(" ")[0]),
        occurred_at=occurred_at,
        amount=Decimal(amount),
        currency="CNY",
        payee=payee,
        narration=narration,
        source_category=source_category,
        source_types=source_types,
        allowed_accounts=allowed_accounts,
        unknown_account=UNKNOWN_EXPENSE,
        known_accounts=("Assets:Bank:BOC:Debit",),
    )


def make_situation(**changes: object) -> Situation:
    return situation_of(make_request(**changes))  # pyright: ignore[reportArgumentType]


def make_entry(
    *,
    account: str = "Expenses:Food:Delivery",
    outcome: str | None = ACCEPTED,
    proposed: str = UNKNOWN_EXPENSE,
    advice: Advice = NO_ADVICE,
    **changes: object,
) -> JournalEntry:
    request = make_request(**changes)  # pyright: ignore[reportArgumentType]
    situation = situation_of(request)
    return JournalEntry(
        situation=situation,
        known_accounts=request.known_accounts,
        allowed_accounts=request.allowed_accounts,
        unknown_account=request.unknown_account,
        proposal=Proposal(
            account=proposed,
            status="unknown" if proposed == UNKNOWN_EXPENSE else "accepted",
            origin="unknown",
            confidence=advice.confidence,
            reason="测试",
            advice=advice,
        ),
        recorded_on=situation.on,
        decision=None if outcome is None else Decision(outcome, account, situation.on),
    )


def make_transaction(
    event_id: str,
    accounts: dict[str, str],
    *,
    on: date = date(2026, 9, 1),
) -> Transaction:
    return Transaction(
        {"event_id": event_id},
        on,
        "*",
        "瑞幸咖啡",
        "生椰拿铁",
        frozenset(),
        frozenset(),
        [
            Posting(account, Amount(Decimal(number), "CNY"), None, None, None, None)
            for account, number in accounts.items()
        ],
    )


def accounts_of(entry: Transaction) -> dict[str, str]:
    return {
        posting.account: str(posting.units.number)
        for posting in entry.postings
        if posting.units is not None
    }
