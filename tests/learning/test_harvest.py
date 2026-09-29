"""Joining proposals to a ledger, months later if need be."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from bean_import.core.journal import (
    ABSTAINED,
    CORRECTED,
    PENDING,
    Decision,
    JournalEntry,
    LedgerOutcome,
)
from bean_import.journal.memory import InMemoryJournal
from bean_import.learning.harvest import harvest
from bean_import.learning.ledger import DirectiveOutcomes, outcomes_from
from tests.helpers import make_entry, make_transaction


class Outcomes:
    def __init__(self, outcomes: Mapping[str, LedgerOutcome]) -> None:
        self._outcomes = outcomes

    def outcomes(self) -> Mapping[str, LedgerOutcome]:
        return self._outcomes


def pending_entry(event_id: str, proposed: str) -> JournalEntry:
    return make_entry(event_id=event_id, proposed=proposed, outcome=None)


def test_a_proposal_with_no_ledger_entry_yet_stays_pending() -> None:
    journal = InMemoryJournal([pending_entry("e1", "Expenses:Food:Quick")])

    summary = harvest(journal, Outcomes({}))

    assert summary.pending == 1
    assert summary.settled == 0
    assert summary.count_of(PENDING) == 1
    assert journal.entries()[0].decision is None


def test_an_entry_that_vanished_from_the_ledger_is_reported_not_forgotten() -> None:
    settled = make_entry(event_id="e1", proposed="Expenses:Food:Quick")
    journal = InMemoryJournal([settled, pending_entry("e2", "Expenses:Food:Quick")])

    summary = harvest(journal, Outcomes({}))

    assert (summary.vanished, summary.pending) == (1, 1)
    assert summary.settled == 0
    assert journal.entries()[0].decision == settled.decision, (
        "pointing at the wrong ledger must not erase months of history"
    )


def test_a_correction_made_in_the_ledger_is_written_back_to_the_journal() -> None:
    journal = InMemoryJournal([pending_entry("e1", "Expenses:Food:Quick")])
    ledger = DirectiveOutcomes(
        [
            make_transaction(
                "e1",
                {"Assets:Bank:BOC:Debit": "-32", "Expenses:Food:Delivery": "32"},
            )
        ]
    )

    summary = harvest(journal, ledger)

    assert summary.changed == 1
    assert summary.count_of(CORRECTED) == 1
    decision = journal.entries()[0].decision
    assert decision is not None
    assert decision.outcome == CORRECTED
    assert decision.account == "Expenses:Food:Delivery"


def test_recategorizing_later_overwrites_an_earlier_verdict() -> None:
    settled = make_entry(event_id="e1", proposed="Expenses:Food:Quick")
    journal = InMemoryJournal([settled])
    assert settled.decision is not None

    summary = harvest(
        journal,
        DirectiveOutcomes(
            [
                make_transaction(
                    "e1",
                    {"Assets:Bank:BOC:Debit": "-32", "Expenses:Unknown": "32"},
                    on=date(2027, 3, 1),
                )
            ]
        ),
    )

    assert summary.changed == 1
    decision = journal.entries()[0].decision
    assert decision == Decision(ABSTAINED, "Expenses:Unknown", date(2027, 3, 1))


def test_harvesting_twice_changes_nothing_the_second_time() -> None:
    journal = InMemoryJournal([pending_entry("e1", "Expenses:Food:Quick")])
    ledger = DirectiveOutcomes(
        [
            make_transaction(
                "e1",
                {"Assets:Bank:BOC:Debit": "-32", "Expenses:Food:Quick": "32"},
            )
        ]
    )

    harvest(journal, ledger)
    second = harvest(journal, ledger)

    assert second.changed == 0
    assert second.settled == 1


def test_only_transactions_carrying_an_event_id_can_be_joined() -> None:
    anonymous = make_transaction("e1", {"Expenses:Food:Quick": "32"})
    stripped = anonymous._replace(meta={})

    assert outcomes_from([stripped]) == {}
    assert set(outcomes_from([anonymous])) == {"e1"}
