"""Score the importer against the person using it.

Two things happen at review time and they must not be mixed up:

- The importer **committed** to an account, and the person kept it or replaced
  it. That is a prediction with a verdict, and it is what accuracy means.
- The importer **abstained**, and the person supplied an account anyway. That
  is a free label. It is the most valuable thing that can happen early on, but
  counting it as a wrong prediction would be nonsense: nothing was predicted.

Milestone 1 abstains every time, so it should report zero coverage and no
accuracy at all, rather than looking like a classifier that is always wrong.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from bean_import.core.classification import ACCEPTED as COMMITTED
from bean_import.core.journal import (
    ABSTAINED,
    ACCEPTED,
    SPLIT,
    JournalEntry,
)

MAX_CONFUSIONS = 10


@dataclass(frozen=True, slots=True)
class AccountRow:
    """How one account fared as a prediction and as an answer."""

    account: str
    predicted: int
    kept: int
    overridden: int
    chosen: int

    @property
    def precision(self) -> float:
        return self.kept / self.predicted if self.predicted else 0.0


@dataclass(frozen=True, slots=True)
class Confusion:
    """We said one thing, the person wrote another, this many times."""

    predicted: str
    chosen: str
    count: int


@dataclass(frozen=True, slots=True)
class LearningReport:
    total: int
    settled: int
    pending: int
    predicted: int
    kept: int
    overridden: int
    labelled: int
    left_unknown: int
    split: int
    rows: tuple[AccountRow, ...]
    confusions: tuple[Confusion, ...]

    @property
    def precision(self) -> float:
        """Of the accounts we committed to, how many the person kept."""

        return self.kept / self.predicted if self.predicted else 0.0

    @property
    def coverage(self) -> float:
        """Of the settled entries, how many we dared commit to."""

        return self.predicted / self.settled if self.settled else 0.0

    @property
    def learnable(self) -> int:
        """Examples worth remembering: our hits plus the person's own labels."""

        return self.kept + self.overridden + self.labelled


def report_for(entries: Sequence[JournalEntry]) -> LearningReport:
    """Aggregate a journal into the numbers worth looking at."""

    predicted: Counter[str] = Counter()
    kept: Counter[str] = Counter()
    overridden: Counter[str] = Counter()
    chosen: Counter[str] = Counter()
    confusions: Counter[tuple[str, str]] = Counter()
    pending = 0
    labelled = 0
    left_unknown = 0
    split = 0

    for entry in entries:
        decision = entry.decision
        if decision is None:
            pending += 1
            continue
        if decision.outcome == SPLIT:
            split += 1
            continue
        chosen[decision.account] += 1
        if decision.outcome == ABSTAINED:
            left_unknown += 1
            continue
        if entry.proposal.status != COMMITTED:
            labelled += 1
            continue
        account = entry.proposal.account
        predicted[account] += 1
        if decision.outcome == ACCEPTED:
            kept[account] += 1
        else:
            overridden[account] += 1
            confusions[(account, decision.account)] += 1

    accounts = sorted(set(predicted) | set(chosen))
    rows = tuple(
        AccountRow(
            account=account,
            predicted=predicted[account],
            kept=kept[account],
            overridden=overridden[account],
            chosen=chosen[account],
        )
        for account in accounts
    )
    ranked = sorted(confusions.items(), key=lambda item: (-item[1], item[0]))
    return LearningReport(
        total=len(entries),
        settled=len(entries) - pending,
        pending=pending,
        predicted=sum(predicted.values()),
        kept=sum(kept.values()),
        overridden=sum(overridden.values()),
        labelled=labelled,
        left_unknown=left_unknown,
        split=split,
        rows=rows,
        confusions=tuple(
            Confusion(predicted=pair[0], chosen=pair[1], count=count)
            for pair, count in ranked[:MAX_CONFUSIONS]
        ),
    )


def format_report(report: LearningReport) -> str:
    """A plain text summary for the command line."""

    lines = [
        f"记录 {report.total} 条，已结算 {report.settled} 条，待定 {report.pending} 条",
        (
            f"提议了账户 {report.predicted} 条："
            f"保留 {report.kept}，被改 {report.overridden}"
        ),
        (
            f"未提议 {report.settled - report.predicted - report.split} 条："
            f"你自己填了 {report.labelled}，仍留未知 {report.left_unknown}；"
            f"另有拆分 {report.split}"
        ),
    ]
    if report.predicted:
        lines.append(f"覆盖率 {report.coverage:.0%}，命中率 {report.precision:.0%}")
    else:
        lines.append(
            f"覆盖率 0%（还没有提议过账户），已积累可学习样本 {report.learnable} 条"
        )
    if report.rows:
        lines.append("")
        lines.append(f"{'账户':<34}{'提议':>6}{'保留':>6}{'被改':>6}{'最终':>6}")
        for row in report.rows:
            lines.append(
                f"{row.account:<34}{row.predicted:>6}{row.kept:>6}"
                f"{row.overridden:>6}{row.chosen:>6}"
            )
    if report.confusions:
        lines.append("")
        lines.append("最常见的误判：")
        for confusion in report.confusions:
            lines.append(
                f"  {confusion.predicted} -> {confusion.chosen} × {confusion.count}"
            )
    return "\n".join(lines)
