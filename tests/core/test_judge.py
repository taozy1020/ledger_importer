"""Reading a human decision out of what the ledger ended up holding."""

from __future__ import annotations

from datetime import date

from bean_import.core.journal import (
    ABSTAINED,
    ACCEPTED,
    CORRECTED,
    SPLIT,
    Decision,
    LedgerOutcome,
    judge,
)
from tests.helpers import make_entry

ON = date(2026, 9, 1)


def outcome(*accounts: str) -> LedgerOutcome:
    return LedgerOutcome("event", accounts, ON)


def test_no_ledger_entry_yet_means_the_answer_is_simply_not_in() -> None:
    assert judge(make_entry(proposed="Expenses:Food:Quick"), None) is None


def test_keeping_the_proposal_is_an_acceptance() -> None:
    entry = make_entry(proposed="Expenses:Food:Quick")

    decision = judge(entry, outcome("Assets:Bank:BOC:Debit", "Expenses:Food:Quick"))

    assert decision == Decision(ACCEPTED, "Expenses:Food:Quick", ON)


def test_writing_a_different_account_is_a_correction() -> None:
    entry = make_entry(proposed="Expenses:Food:Quick")

    decision = judge(entry, outcome("Assets:Bank:BOC:Debit", "Expenses:Food:Delivery"))

    assert decision is not None
    assert decision.outcome == CORRECTED
    assert decision.account == "Expenses:Food:Delivery"
    assert decision.learnable is True


def test_leaving_it_unknown_is_an_abstention_and_teaches_nothing() -> None:
    entry = make_entry(proposed="Expenses:Food:Quick")

    decision = judge(entry, outcome("Assets:Bank:BOC:Debit", "Expenses:Unknown"))

    assert decision is not None
    assert decision.outcome == ABSTAINED
    assert decision.learnable is False


def test_a_split_is_recorded_but_never_trained_on() -> None:
    entry = make_entry(proposed="Expenses:Food:Quick")

    decision = judge(
        entry,
        outcome("Assets:Bank:BOC:Debit", "Expenses:Food:Quick", "Expenses:Gift"),
    )

    assert decision is not None
    assert decision.outcome == SPLIT
    assert decision.account == ""
    assert decision.learnable is False
