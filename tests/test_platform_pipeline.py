"""Platform adapters, normalization, and the constrained classifier."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from beancount.core.data import Transaction
from beancount.loader import (
    load_string,  # pyright: ignore[reportUnknownVariableType]
)
from beancount.parser import printer

from bean_import.batch_importer import (
    BatchError,
    PlatformBatchImporter,
    load_batch_files,
)
from bean_import.classify import (
    ClassificationRequest,
    KnowledgeClassifier,
    OpenAICompatibleClassifier,
)
from bean_import.customer_config import CustomerConfigError, load_customer_config
from bean_import.knowledge import KnowledgeGuide
from bean_import.pipeline import import_files
from bean_import.sources import read_platform_file
from bean_import.sources.common import SourceParseError

ROOT = Path(__file__).resolve().parents[1] / "examples" / "prototype"
STATEMENTS = ROOT / "statements"


def test_prototype_batch_merges_card_payments_and_uses_knowledge() -> None:
    config = load_customer_config(ROOT / "ledger.toml")
    entries = import_files(sorted(STATEMENTS.glob("*.csv")), config)

    assert len(entries) == 5
    by_narration = {entry.narration: entry for entry in entries}
    coffee = by_narration["生椰拿铁"]
    assert coffee.date.isoformat() == "2026-09-02"
    assert _accounts(coffee) == {
        "Assets:Bank:BOC:Debit": "-32.00",
        "Expenses:Food:Coffee": "32.00",
    }
    assert coffee.meta["classification"] == "knowledge"
    assert "alipay:" in str(coffee.meta["source_id"])
    assert "boc_debit:" in str(coffee.meta["source_id"])

    meal = by_narration["牛肉面"]
    assert _accounts(meal) == {
        "Assets:WeChat:Balance": "-18.00",
        "Expenses:Food:Meal": "18.00",
    }
    groceries = by_narration["购物"]
    assert _accounts(groceries)["Liabilities:CreditCard:BOC"] == "-58.00"
    assert _accounts(groceries)["Expenses:Groceries"] == "58.00"

    repayment = by_narration["信用卡还款"]
    assert repayment.meta["classification"] == "structural"
    assert _accounts(repayment) == {
        "Assets:Bank:BOC:Debit": "-200.00",
        "Liabilities:CreditCard:BOC": "200.00",
    }
    transfer = by_narration["零钱提现"]
    assert transfer.meta["event_kind"] == "transfer"
    assert _accounts(transfer) == {
        "Assets:WeChat:Balance": "-50.00",
        "Assets:Bank:BOC:Debit": "50.00",
    }

    ledger = (ROOT / "accounts.bean").read_text(encoding="utf-8")
    output = StringIO()
    printer.print_entries(entries, file=output)  # pyright: ignore[reportUnknownMemberType]
    _, errors, _ = load_string(ledger + "\n" + output.getvalue())
    assert errors == []


def test_ambiguous_card_match_stays_unmerged(tmp_path: Path) -> None:
    config = load_customer_config(ROOT / "ledger.toml")
    alipay = tmp_path / "alipay.csv"
    debit = tmp_path / "debit.csv"
    alipay.write_text(
        (STATEMENTS / "alipay.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    debit.write_text(
        "记账日期,记账时间,币别,金额,余额,交易名称,渠道,网点名称,附言,对方账户名,对方卡号/账号,对方开户行\n"
        "2026-09-02,120102,人民币,-32.00,1000.00,消费,网上支付,------,支付宝-快捷支付,甲,------,------\n"
        "2026-09-02,120103,人民币,-32.00,968.00,消费,网上支付,------,支付宝-快捷支付,乙,------,------\n",
        encoding="utf-8",
    )

    entries = import_files([alipay, debit], config)

    assert len(entries) == 3
    assert all(entry.meta.get("link_candidates") for entry in entries)
    assert all(entry.meta["classification"] != "structural" for entry in entries)


def test_alipay_gbk_and_rejected_containers(tmp_path: Path) -> None:
    config = load_customer_config(ROOT / "ledger.toml")
    gbk = tmp_path / "alipay.csv"
    source = (STATEMENTS / "alipay.csv").read_text(encoding="utf-8")
    gbk.write_bytes(source.encode("gbk"))
    records = read_platform_file(gbk, config)
    assert records[0].payee == "瑞幸咖啡"
    assert records[0].source_account == "Assets:Bank:BOC:Debit"

    pdf = tmp_path / "statement.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(SourceParseError, match="PDF or email"):
        read_platform_file(pdf, config)
    web = tmp_path / "web.csv"
    web.write_text("支付宝交易记录明细查询\n", encoding="utf-8")
    with pytest.raises(SourceParseError, match="mobile"):
        read_platform_file(web, config)


def test_knowledge_account_must_belong_to_the_customer(tmp_path: Path) -> None:
    text = (ROOT / "ledger.toml").read_text(encoding="utf-8")
    text += '\n[[knowledge.examples]]\npayee = "未知"\naccount = "Expenses:NotOpen"\n'
    path = tmp_path / "ledger.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CustomerConfigError, match="not in"):
        load_customer_config(path)


def test_model_choice_is_limited_to_allowed_accounts() -> None:
    request = _request()
    calls: list[dict[str, object]] = []

    def transport(url: str, payload: dict[str, object], api_key: str) -> str:
        del url, api_key
        calls.append(payload)
        return json.dumps(
            {"account": "Expenses:NotOpen", "uncertain": False, "reason": "猜的"},
            ensure_ascii=False,
        )

    result = OpenAICompatibleClassifier(
        "http://127.0.0.1:9/v1",
        "demo-model",
        transport=transport,
    ).classify(request)

    assert result.status == "suspense"
    assert result.account == "Expenses:Uncategorized"
    message = str(calls[0]["messages"])
    assert "咖啡和奶茶" in message
    assert "Expenses:Food:Coffee" in message


def test_invalid_model_json_is_retried_once() -> None:
    responses = iter(
        [
            "not json",
            json.dumps(
                {"account": "Expenses:Food", "uncertain": False, "reason": "餐饮"},
                ensure_ascii=False,
            ),
        ]
    )

    def transport(url: str, payload: dict[str, object], api_key: str) -> str:
        del url, payload, api_key
        return next(responses)

    result = OpenAICompatibleClassifier(
        "http://127.0.0.1:9/v1",
        "demo-model",
        transport=transport,
    ).classify(_request())
    assert result.status == "accepted"
    assert result.account == "Expenses:Food"


def test_missing_example_uses_suspense_without_calling_a_model() -> None:
    request = _request()
    result = KnowledgeClassifier().classify(
        ClassificationRequest(
            event_id=request.event_id,
            kind=request.kind,
            role=request.role,
            transaction_date=request.transaction_date,
            amount=request.amount,
            currency=request.currency,
            payee="没有见过的店",
            narration="其他",
            source_category="",
            source_types=request.source_types,
            allowed_accounts=request.allowed_accounts,
            suspense_account=request.suspense_account,
            examples=(),
            guides=(),
        )
    )
    assert result.status == "suspense"
    assert result.account == "Expenses:Uncategorized"


def test_batch_manifest_rejects_paths_outside_the_root(tmp_path: Path) -> None:
    manifest = tmp_path / "imports" / "bad.batch.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps({"version": 1, "files": ["../../etc/passwd"]}),
        encoding="utf-8",
    )
    with pytest.raises(BatchError, match="escapes"):
        load_batch_files(manifest, tmp_path)

    importer = PlatformBatchImporter(load_customer_config(ROOT / "ledger.toml"), ROOT)
    batch = ROOT / "imports" / "demo.batch.json"
    assert importer.identify(str(batch))
    assert len(importer.extract(str(batch), [])) == 5


def _request() -> ClassificationRequest:
    from datetime import date
    from decimal import Decimal

    return ClassificationRequest(
        event_id="event",
        kind="expense",
        role="expense_account",
        transaction_date=date(2026, 9, 1),
        amount=Decimal("-32.00"),
        currency="CNY",
        payee="瑞幸咖啡",
        narration="生椰拿铁",
        source_category="餐饮美食",
        source_types=("alipay",),
        allowed_accounts=(
            "Expenses:Food",
            "Expenses:Food:Coffee",
            "Expenses:Uncategorized",
        ),
        suspense_account="Expenses:Uncategorized",
        examples=(),
        guides=(
            KnowledgeGuide(
                ("餐饮", "咖啡"),
                "咖啡和奶茶归入 Expenses:Food:Coffee。正餐归入 Expenses:Food:Meal。",
            ),
        ),
    )


def _accounts(entry: Transaction) -> dict[str, str]:
    return {
        posting.account: str(posting.units.number)
        for posting in entry.postings
        if posting.units is not None
    }
