"""Pure transformation from one source record to one Beancount transaction."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from beancount.core.amount import Amount
from beancount.core.data import Posting, Transaction

from bean_import.config import CsvImportConfig
from bean_import.models import SourceRecord


class MappingError(ValueError):
    """A source record has no safe account mapping."""


def map_record(
    record: SourceRecord,
    config: CsvImportConfig,
    source_file: str | Path,
) -> Transaction:
    """Create a balanced two-posting transaction from a signed bank amount.

    The CSV amount is from the source account's point of view: outflows are
    negative and inflows positive. The bank posting keeps that sign; the
    expense or income posting uses the opposite sign to balance it.
    """

    target_account = config.category_accounts.get(record.category)
    if target_account is None:
        raise MappingError(
            f"Row {record.row_number}: no account mapping for category "
            f"{record.category!r}"
        )
    if record.amount == Decimal("0"):
        raise MappingError(
            f"Row {record.row_number}: zero-amount rows are not importable"
        )

    source_posting = Posting(
        config.source_account,
        Amount(record.amount, config.currency),
        None,
        None,
        None,
        None,
    )
    category_posting = Posting(
        target_account,
        Amount(-record.amount, config.currency),
        None,
        None,
        None,
        None,
    )
    metadata = {
        "filename": str(Path(source_file)),
        "lineno": record.row_number,
        "source_id": record.source_id,
        "source_category": record.category,
        "__source__": " | ".join(record.raw_fields.values()),
    }

    return Transaction(
        metadata,
        record.transaction_date,
        "*",
        record.payee or None,
        record.narration or record.payee,
        frozenset(),
        frozenset(),
        [source_posting, category_posting],
    )
