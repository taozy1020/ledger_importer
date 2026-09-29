"""Parse CSV rows into source records without making accounting decisions."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from bean_import.core.models import SourceRecord
from bean_import.csv_demo.config import CsvImportConfig


class CsvImportError(ValueError):
    """A CSV row cannot be interpreted using the configured column schema."""


def _read_dict_reader(file: TextIO, config: CsvImportConfig) -> csv.DictReader[str]:
    reader = csv.DictReader(file)
    if reader.fieldnames is None:
        raise CsvImportError("CSV has no header row")

    required = {
        config.columns.date,
        config.columns.amount,
        config.columns.payee,
        config.columns.narration,
        config.columns.category,
    }
    missing = required.difference(reader.fieldnames)
    if missing:
        missing_columns = ", ".join(sorted(missing))
        raise CsvImportError(f"CSV is missing required columns: {missing_columns}")
    return reader


def can_read(path: str | Path, config: CsvImportConfig) -> bool:
    """Return whether the file header contains the configured required columns."""

    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as csv_file:
            _read_dict_reader(csv_file, config)
    except (OSError, UnicodeError, CsvImportError):
        return False
    return True


def read_records(path: str | Path, config: CsvImportConfig) -> list[SourceRecord]:
    """Read records while retaining every source column and its original text."""

    records: list[SourceRecord] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as csv_file:
        reader = _read_dict_reader(csv_file, config)
        assert reader.fieldnames is not None

        for row_number, row in enumerate(reader, start=2):
            raw_fields = {
                field: row.get(field, "") or "" for field in reader.fieldnames
            }
            try:
                transaction_date = date.fromisoformat(
                    raw_fields[config.columns.date].strip()
                )
                amount = Decimal(raw_fields[config.columns.amount].strip())
            except (ValueError, InvalidOperation) as error:
                raise CsvImportError(
                    f"Row {row_number}: invalid ISO date or decimal amount"
                ) from error

            raw_id = raw_fields.get(config.columns.source_id, "").strip()
            source_id = raw_id or _fingerprint(raw_fields)
            records.append(
                SourceRecord(
                    source_id=source_id,
                    row_number=row_number,
                    transaction_date=transaction_date,
                    amount=amount,
                    payee=raw_fields[config.columns.payee].strip(),
                    narration=raw_fields[config.columns.narration].strip(),
                    category=raw_fields[config.columns.category].strip(),
                    raw_fields=raw_fields,
                )
            )
    return records


def _fingerprint(raw_fields: dict[str, str]) -> str:
    """Build a stable row ID when the source CSV has no transaction ID."""

    canonical_row = json.dumps(
        raw_fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_row.encode("utf-8")).hexdigest()
