from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from beancount.core.data import Transaction
from beangulp.exceptions import Error as BeangulpError
from beangulp.identify import (
    identify as _identify_importer,  # pyright: ignore[reportUnknownVariableType]
)
from beangulp.importer import Importer

from bean_import.config import CsvImportConfig
from bean_import.importer import CsvMappingImporter

identify_importer: Callable[[list[Importer], str], Importer | None] = cast(
    Callable[[list[Importer], str], Importer | None], _identify_importer
)


def test_importer_matches_extracts_and_identifies_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(
        "id,date,amount,payee,narration,category\n"
        "row-1,2026-09-01,-3.50,Cafe,coffee,餐饮\n",
        encoding="utf-8",
    )
    importer = CsvMappingImporter(
        CsvImportConfig(
            source_account="Assets:Bank:Checking",
            currency="CNY",
            category_accounts={"餐饮": "Expenses:Food"},
        )
    )

    assert importer.identify(str(csv_path))
    assert importer.account(str(csv_path)) == "Assets:Bank:Checking"
    assert importer.date(str(csv_path)) == date(2026, 9, 1)
    assert importer.filename(str(csv_path)) == "transactions.csv"
    [entry] = importer.extract(str(csv_path), existing=[])
    assert isinstance(entry, Transaction)
    assert entry.meta["source_id"] == "row-1"
    assert entry.postings[0].units is not None
    assert entry.postings[0].units.number == Decimal("-3.50")


def test_two_profiles_can_match_but_cli_rejects_the_ambiguity(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(
        "id,date,amount,payee,narration,category\n"
        "row-1,2026-09-01,-3.50,Cafe,coffee,餐饮\n",
        encoding="utf-8",
    )
    bank = CsvMappingImporter(
        CsvImportConfig(
            source_account="Assets:Bank:Checking",
            currency="CNY",
            category_accounts={"餐饮": "Expenses:Food"},
            importer_name="Bank CSV profile",
        )
    )
    wallet = CsvMappingImporter(
        CsvImportConfig(
            source_account="Assets:Wallet:Balance",
            currency="CNY",
            category_accounts={"餐饮": "Expenses:Food"},
            importer_name="Wallet CSV profile",
        )
    )

    assert bank.name != wallet.name
    assert bank.identify(str(csv_path))
    assert wallet.identify(str(csv_path))
    with pytest.raises(BeangulpError, match="more than one importer"):
        identify_importer([bank, wallet], str(csv_path))


def test_default_deduplicate_marks_a_match_without_merging(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(
        "id,date,amount,payee,narration,category\n"
        "row-1,2026-09-01,-3.50,Cafe,coffee,餐饮\n",
        encoding="utf-8",
    )
    config = CsvImportConfig(
        source_account="Assets:Bank:Checking",
        currency="CNY",
        category_accounts={"餐饮": "Expenses:Food"},
    )
    importer = CsvMappingImporter(config)
    [existing] = importer.extract(str(csv_path), existing=[])
    [new] = importer.extract(str(csv_path), existing=[])
    imported_entries = [new]

    importer.deduplicate(imported_entries, [existing])

    assert imported_entries == [new]
    assert new.meta["__duplicate__"] is existing
    assert new.meta["source_id"] == existing.meta["source_id"]
    assert new is not existing


def test_different_source_account_is_not_merged_as_duplicate(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(
        "id,date,amount,payee,narration,category\n"
        "row-1,2026-09-01,-3.50,Cafe,coffee,餐饮\n",
        encoding="utf-8",
    )
    bank = CsvMappingImporter(
        CsvImportConfig(
            source_account="Assets:Bank:Checking",
            currency="CNY",
            category_accounts={"餐饮": "Expenses:Food"},
        )
    )
    wallet = CsvMappingImporter(
        CsvImportConfig(
            source_account="Assets:Wallet:Balance",
            currency="CNY",
            category_accounts={"餐饮": "Expenses:Food"},
        )
    )
    [existing] = bank.extract(str(csv_path), existing=[])
    [new] = wallet.extract(str(csv_path), existing=[])

    wallet.deduplicate([new], [existing])

    assert "__duplicate__" not in new.meta
