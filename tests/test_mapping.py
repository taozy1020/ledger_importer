from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from beancount.core.data import Transaction

from bean_import.config import CsvImportConfig
from bean_import.mapping import MappingError, map_record
from bean_import.models import SourceRecord


@pytest.fixture
def config() -> CsvImportConfig:
    return CsvImportConfig(
        source_account="Assets:Bank:Checking",
        currency="CNY",
        category_accounts={
            "餐饮": "Expenses:Food",
            "工资": "Income:Salary",
        },
    )


def make_record(amount: str, category: str = "餐饮") -> SourceRecord:
    return SourceRecord(
        source_id="row-1",
        row_number=2,
        transaction_date=date(2026, 9, 1),
        amount=Decimal(amount),
        payee="示例商户",
        narration="示例交易",
        category=category,
        raw_fields={"id": "row-1", "amount": amount},
    )


def test_expense_mapping_balances_against_bank_outflow(
    config: CsvImportConfig,
) -> None:
    entry = map_record(make_record("-12.30"), config, "statement.csv")

    assert isinstance(entry, Transaction)
    assert entry.postings[0].account == "Assets:Bank:Checking"
    assert entry.postings[0].units is not None
    assert entry.postings[0].units.number == Decimal("-12.30")
    assert entry.postings[1].account == "Expenses:Food"
    assert entry.postings[1].units is not None
    assert entry.postings[1].units.number == Decimal("12.30")
    assert entry.meta["source_id"] == "row-1"


def test_income_mapping_balances_against_bank_inflow(
    config: CsvImportConfig,
) -> None:
    entry = map_record(make_record("12000", "工资"), config, "statement.csv")

    assert entry.postings[0].units is not None
    assert entry.postings[0].units.number == Decimal("12000")
    assert entry.postings[1].account == "Income:Salary"
    assert entry.postings[1].units is not None
    assert entry.postings[1].units.number == Decimal("-12000")


def test_unknown_category_fails_instead_of_guessing(
    config: CsvImportConfig,
) -> None:
    with pytest.raises(MappingError, match="no account mapping"):
        map_record(make_record("-8", "未配置"), config, "statement.csv")
