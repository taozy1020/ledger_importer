"""Small domain types shared by the CSV adapter and mapping logic."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One immutable row as received from the external CSV source."""

    source_id: str
    row_number: int
    transaction_date: date
    amount: Decimal
    payee: str
    narration: str
    category: str
    raw_fields: Mapping[str, str]
