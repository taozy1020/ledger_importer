from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bean_import.config import CsvColumns, CsvImportConfig
from bean_import.csv_source import CsvImportError, read_records


@pytest.fixture
def config() -> CsvImportConfig:
    return CsvImportConfig(
        source_account="Assets:Bank:Checking",
        currency="CNY",
        category_accounts={"餐饮": "Expenses:Food"},
    )


def test_read_records_preserves_raw_values_and_uses_id(
    tmp_path: Path, config: CsvImportConfig
) -> None:
    csv_path = tmp_path / "input.csv"
    csv_path.write_text(
        "id,date,amount,payee,narration,category,extra\n"
        "tx-1,2026-09-01,-12.30,店铺,午餐,餐饮,原始值\n",
        encoding="utf-8",
    )

    [record] = read_records(csv_path, config)

    assert record.source_id == "tx-1"
    assert record.row_number == 2
    assert record.transaction_date == date(2026, 9, 1)
    assert record.amount == Decimal("-12.30")
    assert record.raw_fields["extra"] == "原始值"


def test_read_records_creates_repeatable_id_without_id_column(
    tmp_path: Path,
) -> None:
    config = CsvImportConfig(
        source_account="Assets:Bank:Checking",
        currency="CNY",
        category_accounts={"餐饮": "Expenses:Food"},
        columns=CsvColumns(source_id="missing_id"),
    )
    csv_path = tmp_path / "input.csv"
    csv_path.write_text(
        "date,amount,payee,narration,category\n2026-09-01,-12.30,店铺,午餐,餐饮\n",
        encoding="utf-8",
    )

    [first] = read_records(csv_path, config)
    [second] = read_records(csv_path, config)

    assert first.source_id == second.source_id
    assert len(first.source_id) == 64


def test_read_records_reports_bad_row_number(
    tmp_path: Path, config: CsvImportConfig
) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "id,date,amount,payee,narration,category\n"
        "tx-1,not-a-date,12.3,店铺,午餐,餐饮\n",
        encoding="utf-8",
    )

    with pytest.raises(CsvImportError, match="Row 2"):
        read_records(csv_path, config)
