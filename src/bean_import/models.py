"""Domain records shared by the CSV prototype and the platform pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

EventKind = Literal["expense", "income", "transfer", "refund", "repayment"]
AccountRole = Literal["expense_account", "income_account"]


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One immutable row as received from an external statement."""

    source_id: str
    row_number: int
    transaction_date: date
    amount: Decimal
    payee: str
    narration: str
    category: str
    raw_fields: Mapping[str, str]
    source_type: str = "csv"
    source_account: str = ""
    currency: str = "CNY"
    funding_method: str = ""
    status: str = ""
    card_tail: str = ""
    counter_account: str = ""
    source_file: str = ""


@dataclass(frozen=True, slots=True)
class AccountingEvent:
    """One economic activity, possibly backed by several source rows."""

    event_id: str
    kind: EventKind
    evidence_ids: tuple[str, ...]
    canonical_date: date
    currency: str
    payee: str
    narration: str
    source_category: str
    source_types: tuple[str, ...]
    postings: tuple[tuple[str, Decimal], ...]
    unresolved_role: AccountRole | None
    link_candidates: tuple[str, ...]
    flags: tuple[str, ...]
    source_files: tuple[str, ...]
    row_numbers: tuple[int, ...]
