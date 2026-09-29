"""Harvest what a person decided, and report how good the proposals were.

Run this after reviewing in Fava. It reads the ledger, matches every entry back
to the proposal that produced it by `event_id`, and records the verdict. The
statements themselves are not needed and may already be deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bean_import.config.customer import load_customer_config
from bean_import.core.ports import DecisionJournal
from bean_import.journal.jsonl import JsonlJournal
from bean_import.journal.memory import InMemoryJournal
from bean_import.learning.harvest import HarvestSummary, harvest
from bean_import.learning.ledger import LedgerFile
from bean_import.learning.report import format_report, report_for


def run_harvest(
    config_path: Path,
    ledger_path: Path,
    *,
    dry_run: bool = False,
) -> tuple[HarvestSummary, str]:
    """Settle the journal against the ledger and render the report."""

    config = load_customer_config(config_path)
    stored = JsonlJournal(config.journal.path)
    journal: DecisionJournal = InMemoryJournal(stored.entries()) if dry_run else stored
    summary = harvest(journal, LedgerFile(ledger_path))
    return summary, format_report(report_for(journal.entries()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Customer TOML")
    parser.add_argument("--ledger", type=Path, required=True, help="Beancount ledger")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report without writing decisions back to the journal",
    )
    args = parser.parse_args()
    summary, report = run_harvest(args.config, args.ledger, dry_run=args.dry_run)
    print(
        f"检查 {summary.examined} 条提议，"
        f"新结算 {summary.changed} 条，待定 {summary.pending} 条"
    )
    if summary.vanished:
        print(
            f"注意：{summary.vanished} 条已结算的记录在账本里找不到了。"
            "如果是你删掉了这些交易，它们仍在被当作学习样本；"
            "确认 --ledger 指向的是完整账本。"
        )
    print()
    print(report)
