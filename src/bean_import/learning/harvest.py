"""Join proposals with the ledger and write back what the person decided.

Run offline, as often as you like. Every entry is re-judged, not only the
unsettled ones, because recategorizing a transaction six months later is still
a correction and should still be learned from.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from bean_import.core.journal import PENDING, Decision, judge
from bean_import.core.ports import DecisionJournal, LedgerOutcomes


@dataclass(frozen=True, slots=True)
class HarvestSummary:
    """What one harvest changed."""

    examined: int
    settled: int
    changed: int
    pending: int
    vanished: int
    counts: tuple[tuple[str, int], ...]

    def count_of(self, outcome: str) -> int:
        return dict(self.counts).get(outcome, 0)


def harvest(journal: DecisionJournal, ledger: LedgerOutcomes) -> HarvestSummary:
    """Attach ledger outcomes to journal entries and report the movement.

    A proposal the ledger has never answered and one whose transaction has
    since been deleted look identical from here, so neither is treated as a
    verdict. An already settled entry keeps its decision rather than being
    silently unlearned — pointing this command at the wrong ledger should not
    erase months of history — but the count is reported so a real deletion
    does not stay invisible.
    """

    outcomes = ledger.outcomes()
    entries = journal.entries()
    decisions: dict[str, Decision] = {}
    counts: Counter[str] = Counter()
    pending = 0
    vanished = 0

    for entry in entries:
        decision = judge(entry, outcomes.get(entry.event_id))
        if decision is None:
            counts[PENDING] += 1
            if entry.settled:
                vanished += 1
            else:
                pending += 1
            continue
        counts[decision.outcome] += 1
        if decision != entry.decision:
            decisions[entry.event_id] = decision

    changed = journal.settle(decisions)
    return HarvestSummary(
        examined=len(entries),
        settled=len(entries) - pending - vanished,
        changed=changed,
        pending=pending,
        vanished=vanished,
        counts=tuple(sorted(counts.items())),
    )
