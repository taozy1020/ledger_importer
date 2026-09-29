"""Milestone 1 end to end, and the seams that let every part be replaced."""

from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from beancount.loader import (
    load_string,  # pyright: ignore[reportUnknownVariableType]
)
from beancount.parser import printer

from bean_import.advice.history import NullAdvisor
from bean_import.app.factory import Components, build_classifier, build_components
from bean_import.app.fava import (
    BatchError,
    PlatformBatchImporter,
    scan_folder,
    statements_in,
)
from bean_import.app.pipeline import import_files
from bean_import.clock import FixedClock
from bean_import.config.customer import load_customer_config
from bean_import.core.advice import Advice, Candidate
from bean_import.core.classification import Classification, ClassificationRequest
from bean_import.core.classifiers import UnknownClassifier
from bean_import.core.ports import AccountAdvisor, DecisionJournal, SemanticClassifier
from bean_import.core.situation import Situation
from bean_import.journal.memory import InMemoryJournal, NullJournal
from tests.helpers import LEDGER, PROTOTYPE, STATEMENTS, accounts_of

TODAY = FixedClock(date(2026, 9, 10))


def milestone_one(
    *,
    classifier: SemanticClassifier | None = None,
    advisor: AccountAdvisor | None = None,
    journal: DecisionJournal | None = None,
) -> Components:
    """Milestone 1, with nothing written to disk unless the test asks for it."""

    return Components(
        classifier=classifier or UnknownClassifier(),
        advisor=advisor or NullAdvisor(),
        journal=journal or NullJournal(),
        clock=TODAY,
    )


def test_a_whole_folder_imports_with_no_model_and_no_memory() -> None:
    config = load_customer_config(LEDGER)
    assert config.semantic is None
    assert isinstance(build_classifier(config), UnknownClassifier)

    entries = import_files(
        sorted(STATEMENTS.glob("*.csv")), config, components=milestone_one()
    )

    assert len(entries) == 5
    by_narration = {entry.narration: entry for entry in entries}

    coffee = by_narration["生椰拿铁"]
    assert coffee.date.isoformat() == "2026-09-02"
    assert accounts_of(coffee) == {
        "Assets:Bank:BOC:Debit": "-32.00",
        "Expenses:Unknown": "32.00",
    }
    assert coffee.meta["classification"] == "unknown"
    assert coffee.tags == frozenset()
    assert "alipay:" in str(coffee.meta["source_id"])
    assert "boc_debit:" in str(coffee.meta["source_id"])

    assert accounts_of(by_narration["牛肉面"])["Expenses:Unknown"] == "18.00"
    groceries = accounts_of(by_narration["购物"])
    assert groceries["Liabilities:CreditCard:BOC"] == "-58.00"
    assert groceries["Expenses:Unknown"] == "58.00"

    repayment = by_narration["信用卡还款"]
    assert repayment.meta["classification"] == "structural"
    assert accounts_of(repayment) == {
        "Assets:Bank:BOC:Debit": "-200.00",
        "Liabilities:CreditCard:BOC": "200.00",
    }
    transfer = by_narration["零钱提现"]
    assert transfer.meta["event_kind"] == "transfer"
    assert accounts_of(transfer) == {
        "Assets:WeChat:Balance": "-50.00",
        "Assets:Bank:BOC:Debit": "50.00",
    }

    output = StringIO()
    printer.print_entries(entries, file=output)  # pyright: ignore[reportUnknownMemberType]
    accounts = (PROTOTYPE / "accounts.bean").read_text(encoding="utf-8")
    _, errors, _ = load_string(accounts + "\n" + output.getvalue())
    assert errors == []


def test_an_ambiguous_cross_source_match_is_left_unmerged_and_labelled(
    tmp_path: Path,
) -> None:
    config = load_customer_config(LEDGER)
    alipay = tmp_path / "alipay.csv"
    alipay.write_text(
        (STATEMENTS / "alipay.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    debit = tmp_path / "debit.csv"
    debit.write_text(
        "记账日期,记账时间,币别,金额,余额,交易名称,渠道,网点名称,附言,对方账户名,对方卡号/账号,对方开户行\n"
        "2026-09-02,120102,人民币,-32.00,1000.00,消费,网上支付,------,支付宝-快捷支付,甲,------,------\n"
        "2026-09-02,120103,人民币,-32.00,968.00,消费,网上支付,------,支付宝-快捷支付,乙,------,------\n",
        encoding="utf-8",
    )

    entries = import_files([alipay, debit], config, components=milestone_one())

    assert len(entries) == 3
    assert all(entry.meta.get("link_candidates") for entry in entries)
    assert all(entry.meta["classification"] != "structural" for entry in entries)


def test_money_coming_in_lands_in_the_income_unknown_account(tmp_path: Path) -> None:
    config = load_customer_config(LEDGER)
    wechat = tmp_path / "wechat.csv"
    wechat.write_text(
        "微信支付账单明细\n"
        "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号\n"
        "2026-09-07 09:00:00,转账,朋友,还我的钱,收入,¥120.00,零钱,已存入零钱,W9\n",
        encoding="utf-8",
    )

    (entry,) = import_files([wechat], config, components=milestone_one())

    assert entry.meta["event_kind"] == "income"
    assert accounts_of(entry) == {
        "Assets:WeChat:Balance": "120.00",
        "Income:Unknown": "-120.00",
    }


def test_every_unresolved_proposal_is_written_to_the_journal() -> None:
    config = load_customer_config(LEDGER)
    journal = InMemoryJournal()

    import_files(
        sorted(STATEMENTS.glob("*.csv")),
        config,
        components=milestone_one(journal=journal),
    )

    entries = journal.entries()
    assert len(entries) == 3
    assert {entry.proposal.account for entry in entries} == {"Expenses:Unknown"}
    assert all(entry.decision is None for entry in entries)
    assert all(entry.known_accounts for entry in entries)
    coffee = next(entry for entry in entries if entry.situation.payee == "瑞幸咖啡")
    assert coffee.situation.day_part == "早晨"
    assert coffee.unknown_account == "Expenses:Unknown"


def test_advice_reaches_both_the_entry_and_the_classifier() -> None:
    config = load_customer_config(LEDGER)
    seen: list[Advice] = []

    class Advisor:
        def advise(self, situation: Situation, allowed: tuple[str, ...]) -> Advice:
            del situation, allowed
            return Advice((Candidate("Expenses:Food:Quick", 0.42, 3, "3 笔相似记录"),))

    class Watcher:
        def classify(
            self,
            request: ClassificationRequest,
            advice: Advice,
        ) -> Classification:
            seen.append(advice)
            return UnknownClassifier().classify(request, advice)

    entries = import_files(
        [STATEMENTS / "wechat.csv"],
        config,
        components=milestone_one(advisor=Advisor(), classifier=Watcher()),
    )

    unresolved = [
        entry for entry in entries if entry.meta["classification"] == "unknown"
    ]
    assert unresolved
    assert "Expenses:Food:Quick 0.42" in str(unresolved[0].meta["candidates"])
    assert "Expenses:Food:Quick" in str(unresolved[0].meta["candidates"])
    assert seen and seen[0].candidates[0].account == "Expenses:Food:Quick"


def test_the_folder_is_the_batch_and_anything_unrecognized_is_reported(
    tmp_path: Path,
) -> None:
    config = load_customer_config(LEDGER)
    importer = PlatformBatchImporter(config, LEDGER)

    assert importer.identify(str(LEDGER))
    assert not importer.identify(str(STATEMENTS / "wechat.csv"))

    folder = tmp_path / "inbox"
    folder.mkdir()
    (folder / "wechat.csv").write_text(
        (STATEMENTS / "wechat.csv").read_text(encoding="utf-8"), encoding="utf-8"
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


def test_the_default_stack_records_to_the_file_the_ledger_names(tmp_path: Path) -> None:
    text = LEDGER.read_text(encoding="utf-8").replace(
        'path = "decisions.jsonl"', 'path = "state/decisions.jsonl"'
    )
    ledger = tmp_path / "ledger.toml"
    ledger.write_text(text, encoding="utf-8")
    config = load_customer_config(ledger)

    parts = build_components(config, clock=TODAY)
    import_files([STATEMENTS / "wechat.csv"], config, components=parts)

    assert (tmp_path / "state" / "decisions.jsonl").is_file()
    assert parts.journal.entries()
