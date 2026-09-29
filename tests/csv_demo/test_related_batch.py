from __future__ import annotations

import json
from pathlib import Path

import pytest
from beancount.core.data import Transaction

from bean_import.csv_demo.config import CsvImportConfig
from bean_import.csv_demo.related_batch import (
    RelatedBatchConfig,
    RelatedBatchError,
    RelatedBatchImporter,
)

BANK_HEADER = "id,date,amount,payee,narration,category\n"
ALIPAY_HEADER = "id,date,amount,payee,narration,category,funding_method\n"


def make_importer(
    root: Path,
    bank_rows: str,
    alipay_rows: str,
) -> tuple[RelatedBatchImporter, Path]:
    related_dir = root / "related"
    related_dir.mkdir(parents=True, exist_ok=True)
    bank_file = related_dir / "bank.csv"
    alipay_file = related_dir / "alipay.csv"
    bank_file.write_text(BANK_HEADER + bank_rows, encoding="utf-8")
    alipay_file.write_text(ALIPAY_HEADER + alipay_rows, encoding="utf-8")

    manifest = root / "merge-demo.merge.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "batch_id": "test-batch",
                "bank_file": "related/bank.csv",
                "alipay_file": "related/alipay.csv",
            }
        ),
        encoding="utf-8",
    )

    config = RelatedBatchConfig(
        root=root,
        bank=CsvImportConfig(
            source_account="Assets:Bank:Checking",
            currency="CNY",
            category_accounts={
                "支付平台": "Expenses:Uncategorized",
                "购物": "Expenses:Groceries",
            },
        ),
        alipay=CsvImportConfig(
            source_account="Assets:Alipay:Balance",
            currency="CNY",
            category_accounts={
                "餐饮": "Expenses:Food",
                "交通": "Expenses:Transport",
            },
        ),
    )
    return RelatedBatchImporter(config), manifest


def test_merges_unique_bank_alipay_pair_and_keeps_independent_rows(
    tmp_path: Path,
) -> None:
    importer, manifest = make_importer(
        tmp_path,
        "bank-alipay-001,2026-09-10,-38.50,支付宝,支付宝付款,支付平台\n"
        "bank-shop-002,2026-09-11,-22.00,便利店,购物,购物\n",
        "alipay-card-001,2026-09-11,-38.50,咖啡店甲,手冲咖啡,餐饮,银行卡\n"
        "alipay-balance-002,2026-09-12,-15.00,餐馆乙,午餐,餐饮,余额\n",
    )

    entries = importer.extract(str(manifest), existing=[])

    assert len(entries) == 3
    merged, bank_only, alipay_balance = entries
    assert isinstance(merged, Transaction)
    assert merged.payee == "咖啡店甲"
    assert merged.narration == "手冲咖啡"
    assert merged.meta["source_kind"] == "bank_alipay_merge"
    assert merged.meta["source_id"] == "bank-alipay-001"
    assert merged.meta["alipay_source_id"] == "alipay-card-001"
    assert merged.postings[0].account == "Assets:Bank:Checking"
    assert merged.postings[1].account == "Expenses:Food"
    assert "bank: bank-alipay-001" in merged.meta["__source__"]
    assert "alipay: alipay-card-001" in merged.meta["__source__"]

    assert isinstance(bank_only, Transaction)
    assert bank_only.meta["source_kind"] == "bank"
    assert bank_only.payee == "便利店"
    assert bank_only.postings[1].account == "Expenses:Groceries"

    assert isinstance(alipay_balance, Transaction)
    assert alipay_balance.meta["source_kind"] == "alipay_balance"
    assert alipay_balance.postings[0].account == "Assets:Alipay:Balance"
    assert alipay_balance.postings[1].account == "Expenses:Food"


def test_unmatched_bank_funded_alipay_fails_the_whole_batch(tmp_path: Path) -> None:
    importer, manifest = make_importer(
        tmp_path,
        "bank-shop-001,2026-09-10,-22.00,便利店,购物,购物\n",
        "alipay-card-001,2026-09-10,-38.50,咖啡店甲,咖啡,餐饮,银行卡\n",
    )

    with pytest.raises(RelatedBatchError, match="no match"):
        importer.extract(str(manifest), existing=[])


def test_ambiguous_bank_match_fails_instead_of_guessing(tmp_path: Path) -> None:
    importer, manifest = make_importer(
        tmp_path,
        "bank-alipay-001,2026-09-10,-38.50,支付宝,快捷支付,支付平台\n"
        "bank-alipay-002,2026-09-11,-38.50,支付宝,快捷支付,支付平台\n",
        "alipay-card-001,2026-09-10,-38.50,咖啡店甲,咖啡,餐饮,银行卡\n",
    )

    with pytest.raises(RelatedBatchError, match="ambiguous matches"):
        importer.extract(str(manifest), existing=[])


def test_manifest_cannot_reference_a_file_outside_the_batch_root(
    tmp_path: Path,
) -> None:
    importer, manifest = make_importer(
        tmp_path,
        "bank-001,2026-09-10,-22.00,便利店,购物,购物\n",
        "alipay-001,2026-09-10,-15.00,餐馆,午餐,餐饮,余额\n",
    )
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "batch_id": "unsafe",
                "bank_file": "../outside.csv",
                "alipay_file": "related/alipay.csv",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RelatedBatchError, match="escapes the batch root"):
        importer.extract(str(manifest), existing=[])


def test_unknown_alipay_funding_method_fails_closed(tmp_path: Path) -> None:
    importer, manifest = make_importer(
        tmp_path,
        "bank-001,2026-09-10,-15.00,便利店,购物,购物\n",
        "alipay-001,2026-09-10,-15.00,餐馆,午餐,餐饮,花呗\n",
    )

    with pytest.raises(RelatedBatchError, match="unsupported or ambiguous"):
        importer.extract(str(manifest), existing=[])
