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
    scan_folder,
    statements_in,
)
from bean_import.classify import (
    ClassificationRequest,
    UnknownClassifier,
)
from bean_import.customer_config import CustomerConfigError, load_customer_config
from bean_import.pipeline import build_classifier, import_files
from bean_import.semantic import OpenAICompatibleClassifier
from bean_import.sources import read_platform_file
from bean_import.sources.common import SourceParseError

ROOT = Path(__file__).resolve().parents[1] / "examples" / "prototype"
STATEMENTS = ROOT / "statements"


def test_milestone_one_imports_without_any_model() -> None:
    config = load_customer_config(ROOT / "ledger.toml")
    assert config.semantic is None
    assert isinstance(build_classifier(config), UnknownClassifier)
    entries = import_files(sorted(STATEMENTS.glob("*.csv")), config)

    assert len(entries) == 5
    by_narration = {entry.narration: entry for entry in entries}
    coffee = by_narration["生椰拿铁"]
    assert coffee.date.isoformat() == "2026-09-02"
    assert _accounts(coffee) == {
        "Assets:Bank:BOC:Debit": "-32.00",
        "Expenses:Unknown": "32.00",
    }
    assert coffee.meta["classification"] == "unknown"
    assert "alipay:" in str(coffee.meta["source_id"])
    assert "boc_debit:" in str(coffee.meta["source_id"])

    meal = by_narration["牛肉面"]
    assert _accounts(meal)["Expenses:Unknown"] == "18.00"
    groceries = by_narration["购物"]
    assert _accounts(groceries)["Liabilities:CreditCard:BOC"] == "-58.00"
    assert _accounts(groceries)["Expenses:Unknown"] == "58.00"

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


def test_income_direction_falls_back_to_the_income_unknown_account(
    tmp_path: Path,
) -> None:
    config = load_customer_config(ROOT / "ledger.toml")
    wechat = tmp_path / "wechat.csv"
    wechat.write_text(
        "微信支付账单明细\n"
        "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号\n"
        "2026-09-07 09:00:00,转账,朋友,还我的钱,收入,¥120.00,零钱,已存入零钱,W9\n",
        encoding="utf-8",
    )

    (entry,) = import_files([wechat], config)

    assert entry.meta["event_kind"] == "income"
    assert _accounts(entry) == {
        "Assets:WeChat:Balance": "120.00",
        "Income:Unknown": "-120.00",
    }
    assert entry.meta["classification"] == "unknown"


def test_two_wechat_accounts_are_told_apart_by_the_statement_header(
    tmp_path: Path,
) -> None:
    text = (ROOT / "ledger.toml").read_text(encoding="utf-8")
    text = text.replace(
        '[[sources]]\ntype = "wechat"\naccount = "Assets:WeChat:Balance"\n',
        '[[sources]]\ntype = "wechat"\n'
        'account = "Assets:WeChat:Balance"\nidentity = "小明"\n\n'
        '[[sources]]\ntype = "wechat"\n'
        'account = "Assets:WeChat:Work"\nidentity = "小明工作号"\n',
    )
    path = tmp_path / "ledger.toml"
    path.write_text(text, encoding="utf-8")
    config = load_customer_config(path)
    assert len(config.sources_of("wechat")) == 2

    personal = (STATEMENTS / "wechat.csv").read_text(encoding="utf-8")
    work = personal.replace("微信昵称：[小明]", "微信昵称：[小明工作号]")
    work_file = tmp_path / "wechat-work.csv"
    work_file.write_text(work, encoding="utf-8")

    assert read_platform_file(STATEMENTS / "wechat.csv", config)[0].source_account == (
        "Assets:WeChat:Balance"
    )
    assert read_platform_file(work_file, config)[0].source_account == (
        "Assets:WeChat:Work"
    )

    stranger = tmp_path / "wechat-stranger.csv"
    stranger.write_text(
        personal.replace("微信昵称：[小明]", "微信昵称：[路人]"),
        encoding="utf-8",
    )
    with pytest.raises(SourceParseError, match="matches none of the configured"):
        read_platform_file(stranger, config)


def test_cards_are_written_in_full_and_matched_by_tail(tmp_path: Path) -> None:
    config = load_customer_config(ROOT / "ledger.toml")
    assert config.cards[0].number == "6217000000001234"
    assert config.card_account("1234") == "Assets:Bank:BOC:Debit"
    assert config.find_card_account("9999") == ""

    text = (ROOT / "ledger.toml").read_text(encoding="utf-8")
    text = text.replace('number = "6259000000005678"', 'number = "6259 0000 0000 1234"')
    path = tmp_path / "ledger.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CustomerConfigError, match="share the last four digits"):
        load_customer_config(path)


def test_skill_context_uses_time_and_ledger_memory() -> None:
    from datetime import date
    from decimal import Decimal

    from beancount.core.amount import Amount
    from beancount.core.data import Posting

    config = load_customer_config(ROOT / "ledger-with-model.toml")
    assert config.semantic is not None
    assert "外卖" in config.semantic.skill_text
    assert "简餐" in config.semantic.skill_text
    past = Transaction(
        {},
        date(2026, 8, 4),
        "*",
        "美团外卖",
        "午饭",
        frozenset(),
        frozenset(),
        [
            Posting(
                "Assets:Bank:BOC:Debit",
                Amount(Decimal("-36"), "CNY"),
                None,
                None,
                None,
                None,
            ),
            Posting(
                "Expenses:Food:Delivery",
                Amount(Decimal("36"), "CNY"),
                None,
                None,
                None,
                None,
            ),
        ],
    )
    prompts: list[str] = []

    def transport(url: str, payload: dict[str, object], api_key: str) -> str:
        del url, api_key
        prompts.append(str(payload["messages"]))
        return json.dumps({"account": "", "uncertain": True, "reason": ""})

    built = build_classifier(config, [past])
    assert isinstance(built, OpenAICompatibleClassifier)
    assert "美团外卖" in built.memory

    classifier = OpenAICompatibleClassifier(
        built.endpoint,
        built.model,
        skill=built.skill,
        memory=built.memory,
        transport=transport,
    )
    import_files(
        [STATEMENTS / "alipay.csv", STATEMENTS / "boc_debit.csv"],
        config,
        [past],
        classifier,
    )
    coffee = next(prompt for prompt in prompts if "瑞幸咖啡" in prompt)
    assert "星期二" in coffee
    assert "早晨" in coffee
    assert "外卖" in coffee
    assert "美团外卖" in coffee
    assert "Expenses:Food:Delivery" in coffee


def test_skill_path_must_stay_beside_the_ledger(tmp_path: Path) -> None:
    text = (ROOT / "ledger-with-model.toml").read_text(encoding="utf-8")
    text = text.replace('skill = "skills/food.md"', 'skill = "../food.md"')
    path = tmp_path / "ledger.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CustomerConfigError, match="escapes"):
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
        skill="外卖是送到手里的一餐。简餐是顺手吃掉的一餐。",
        transport=transport,
    ).classify(request)

    assert result.status == "unknown"
    assert result.account == "Expenses:Unknown"
    message = str(calls[0]["messages"])
    assert "外卖" in message
    assert "Expenses:Food:Delivery" in message
    assert "星期二" in message


def test_invalid_model_json_is_retried_once() -> None:
    responses = iter(
        [
            "not json",
            json.dumps(
                {
                    "account": "Expenses:Food:Quick",
                    "uncertain": False,
                    "reason": "简餐",
                },
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
    assert result.account == "Expenses:Food:Quick"


def test_unknown_classifier_keeps_the_direction_and_refuses_to_guess() -> None:
    result = UnknownClassifier().classify(_request())
    assert result.status == "unknown"
    assert result.account == "Expenses:Unknown"
    assert result.model_id == ""
    assert "未启用语义分类" in result.reason


def test_folder_is_the_batch_and_other_files_are_skipped(tmp_path: Path) -> None:
    ledger = ROOT / "ledger.toml"
    config = load_customer_config(ledger)
    assert config.batch_folder == STATEMENTS

    importer = PlatformBatchImporter(config, ledger)
    assert importer.identify(str(ledger))
    assert not importer.identify(str(STATEMENTS / "wechat.csv"))
    assert len(importer.extract(str(ledger), [])) == 5

    folder = tmp_path / "inbox"
    folder.mkdir()
    (folder / "wechat.csv").write_text(
        (STATEMENTS / "wechat.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (folder / "中国银行信用卡账单.pdf").write_bytes(b"%PDF")
    (folder / "notes.txt").write_text("下载记录\n", encoding="utf-8")
    statements, skipped = scan_folder(folder)
    assert [path.name for path in statements] == ["wechat.csv"]
    assert sorted(path.name for path in skipped) == [
        "notes.txt",
        "中国银行信用卡账单.pdf",
    ]

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(BatchError, match="No recognized statements"):
        statements_in(empty)


def _request() -> ClassificationRequest:
    from datetime import date
    from decimal import Decimal

    return ClassificationRequest(
        event_id="event",
        kind="expense",
        role="expense_account",
        transaction_date=date(2026, 9, 1),
        occurred_at="2026-09-01 08:00:00",
        amount=Decimal("-32.00"),
        currency="CNY",
        payee="瑞幸咖啡",
        narration="生椰拿铁",
        source_category="餐饮美食",
        source_types=("alipay",),
        allowed_accounts=(
            "Expenses:Food:Delivery",
            "Expenses:Food:Quick",
            "Expenses:Unknown",
        ),
        unknown_account="Expenses:Unknown",
    )


def _accounts(entry: Transaction) -> dict[str, str]:
    return {
        posting.account: str(posting.units.number)
        for posting in entry.postings
        if posting.units is not None
    }
