"""The loop, end to end: propose, let a person decide, harvest, propose better.

This is the test that says the architecture works. Nothing here reads a
statement twice and nothing keeps the original CSV: the only thing carried
across time is the journal and the `event_id` written into the ledger.
"""

from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path

from beancount.core.data import Transaction
from beancount.parser import printer

from bean_import.advice.classifier import HistoryClassifier
from bean_import.advice.history import HistoryAdvisor
from bean_import.app.cli.learn import run_harvest
from bean_import.app.factory import Components, build_components
from bean_import.app.pipeline import import_files
from bean_import.clock import FixedClock
from bean_import.config.customer import load_customer_config
from bean_import.core.classifiers import UnknownClassifier
from bean_import.core.journal import CORRECTED
from bean_import.journal.jsonl import JsonlJournal
from tests.helpers import STATEMENTS, accounts_of

TODAY = FixedClock(date(2026, 9, 10))
CORRECTION = "Expenses:Food:Quick"

COFFEE = (
    "微信支付账单明细\n"
    "微信昵称：[小明]\n"
    "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号\n"
    "{when},商户消费,瑞幸咖啡,{item},支出,¥{amount},零钱,支付成功,{number}\n"
)


def ledger_at(tmp_path: Path) -> Path:
    """A copy of the example ledger whose journal lives in the temp folder."""

    source = STATEMENTS.parent / "ledger.toml"
    path = tmp_path / "ledger.toml"
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "accounts.bean").write_text(
        (STATEMENTS.parent / "accounts.bean").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def statement(tmp_path: Path, name: str, **fields: str) -> Path:
    path = tmp_path / name
    path.write_text(COFFEE.format(**fields), encoding="utf-8")
    return path


def write_ledger(
    tmp_path: Path,
    entries: list[Transaction],
    corrections: dict[str, str],
) -> Path:
    """Stand in for the person reviewing in Fava and saving the result."""

    fixed: list[Transaction] = []
    for entry in entries:
        postings = [
            posting._replace(account=corrections.get(posting.account, posting.account))
            for posting in entry.postings
        ]
        fixed.append(entry._replace(postings=postings))
    output = StringIO()
    printer.print_entries(fixed, file=output)  # pyright: ignore[reportUnknownMemberType]
    path = tmp_path / "main.bean"
    path.write_text(
        'include "accounts.bean"\n\n' + output.getvalue(),
        encoding="utf-8",
    )
    return path


def test_a_correction_today_becomes_advice_tomorrow(tmp_path: Path) -> None:
    ledger_toml = ledger_at(tmp_path)
    config = load_customer_config(ledger_toml)
    journal = JsonlJournal(config.journal.path)

    first = import_files(
        [
            statement(
                tmp_path,
                "wechat-1.csv",
                when="2026-09-01 12:30:00",
                item="生椰拿铁",
                amount="32.00",
                number="W1",
            )
        ],
        config,
        components=build_components(config, clock=TODAY),
    )
    (proposal,) = first
    assert accounts_of(proposal)["Expenses:Unknown"] == "32.00"
    assert "candidates" not in proposal.meta
    assert journal.entries()[0].decision is None

    ledger = write_ledger(tmp_path, list(first), {"Expenses:Unknown": CORRECTION})
    summary, report = run_harvest(ledger_toml, ledger)

    assert summary.changed == 1
    decision = journal.entries()[0].decision
    assert decision is not None
    assert decision.outcome == CORRECTED
    assert decision.account == CORRECTION
    assert "你自己填了 1" in report
    assert "命中率" not in report, "milestone 1 never commits, so it has no accuracy"

    second = import_files(
        [
            statement(
                tmp_path,
                "wechat-2.csv",
                when="2026-09-08 12:40:00",
                item="美式",
                amount="29.00",
                number="W2",
            )
        ],
        config,
        components=build_components(config, clock=TODAY),
    )
    (advised,) = second

    assert accounts_of(advised)["Expenses:Unknown"] == "29.00"
    assert CORRECTION in str(advised.meta["candidates"])

    settled = {entry.event_id for entry in journal.entries() if entry.settled}
    assert len(settled) == 1, "re-importing must not erase a harvested decision"


def test_the_same_memory_can_fill_the_account_in_when_the_ledger_allows_it(
    tmp_path: Path,
) -> None:
    ledger_toml = ledger_at(tmp_path)
    config = load_customer_config(ledger_toml)

    files = [
        statement(
            tmp_path,
            f"wechat-{index}.csv",
            when=f"2026-09-0{index} 12:30:00",
            item="生椰拿铁",
            amount="32.00",
            number=f"W{index}",
        )
        for index in (1, 2, 3)
    ]
    entries = import_files(
        files, config, components=build_components(config, clock=TODAY)
    )
    run_harvest(
        ledger_toml,
        write_ledger(tmp_path, list(entries), {"Expenses:Unknown": CORRECTION}),
    )

    journal = JsonlJournal(config.journal.path)
    advisor = HistoryAdvisor(journal, TODAY)
    confident = Components(
        classifier=HistoryClassifier(0.5),
        advisor=advisor,
        journal=journal,
        clock=TODAY,
    )
    (filled,) = import_files(
        [
            statement(
                tmp_path,
                "wechat-9.csv",
                when="2026-09-09 12:35:00",
                item="拿铁",
                amount="30.00",
                number="W9",
            )
        ],
        config,
        components=confident,
    )

    assert accounts_of(filled)[CORRECTION] == "30.00"
    assert filled.meta["model_id"] == "history"


def test_turning_the_journal_off_leaves_milestone_one_exactly_as_it_was(
    tmp_path: Path,
) -> None:
    text = (STATEMENTS.parent / "ledger.toml").read_text(encoding="utf-8")
    path = tmp_path / "ledger.toml"
    path.write_text(text.replace("enabled = true", "enabled = false"), encoding="utf-8")
    config = load_customer_config(path)
    parts = build_components(config, clock=TODAY)

    assert isinstance(parts.classifier, UnknownClassifier)
    (entry,) = import_files(
        [
            statement(
                tmp_path,
                "wechat-1.csv",
                when="2026-09-01 12:30:00",
                item="生椰拿铁",
                amount="32.00",
                number="W1",
            )
        ],
        config,
        components=parts,
    )

    assert accounts_of(entry)["Expenses:Unknown"] == "32.00"
    assert parts.journal.entries() == ()
    assert not list(tmp_path.glob("*.jsonl"))
