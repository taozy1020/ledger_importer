"""Advice built from decisions the person already made."""

from __future__ import annotations

from datetime import date

from bean_import.advice.history import AdvicePolicy, HistoryAdvisor, NullAdvisor
from bean_import.clock import FixedClock
from bean_import.core.journal import ABSTAINED, ACCEPTED, CORRECTED, SPLIT, JournalEntry
from bean_import.journal.memory import InMemoryJournal
from tests.helpers import ALLOWED, make_entry, make_situation

TODAY = FixedClock(date(2026, 9, 10))


def advisor(
    *entries: JournalEntry, policy: AdvicePolicy | None = None
) -> HistoryAdvisor:
    return HistoryAdvisor(
        InMemoryJournal(entries),
        TODAY,
        policy or AdvicePolicy(),
    )


def test_nothing_settled_means_nothing_to_say() -> None:
    assert advisor().advise(make_situation(), ALLOWED).candidates == ()
    assert NullAdvisor().advise(make_situation(), ALLOWED).candidates == ()


def test_similar_past_moments_become_a_ranked_candidate_with_its_evidence() -> None:
    entries = [
        make_entry(event_id=f"e{index}", account="Expenses:Food:Quick")
        for index in range(3)
    ]

    advice = advisor(*entries).advise(make_situation(event_id="new"), ALLOWED)

    top = advice.top
    assert top is not None
    assert top.account == "Expenses:Food:Quick"
    assert top.support == 3
    assert 0.0 < top.confidence <= 1.0
    assert "3 笔相似记录" in top.evidence
    assert "瑞幸咖啡" in top.evidence


def test_one_weak_memory_does_not_pretend_to_be_certain() -> None:
    advice = advisor(make_entry(account="Expenses:Food:Quick")).advise(
        make_situation(event_id="new"), ALLOWED
    )

    assert advice.confidence < 0.6


def test_a_correction_outweighs_an_acceptance() -> None:
    advice = advisor(
        make_entry(event_id="a", account="Expenses:Food:Quick", outcome=ACCEPTED),
        make_entry(event_id="b", account="Expenses:Food:Delivery", outcome=CORRECTED),
    ).advise(make_situation(event_id="new"), ALLOWED)

    assert [candidate.account for candidate in advice.candidates] == [
        "Expenses:Food:Delivery",
        "Expenses:Food:Quick",
    ]


def test_abstentions_and_splits_teach_nothing() -> None:
    advice = advisor(
        make_entry(event_id="a", account="Expenses:Unknown", outcome=ABSTAINED),
        make_entry(event_id="b", account="", outcome=SPLIT),
    ).advise(make_situation(event_id="new"), ALLOWED)

    assert advice.candidates == ()


def test_an_old_habit_loses_to_a_recent_one() -> None:
    old = make_entry(
        event_id="old",
        account="Expenses:Food:Delivery",
        occurred_at="2024-09-01 08:00:00",
        outcome=CORRECTED,
    )
    recent = make_entry(
        event_id="recent",
        account="Expenses:Food:Quick",
        occurred_at="2026-09-01 08:00:00",
        outcome=CORRECTED,
    )

    advice = advisor(old, recent).advise(make_situation(event_id="new"), ALLOWED)

    assert advice.candidates[0].account == "Expenses:Food:Quick"


def test_an_unrelated_moment_is_below_the_similarity_floor() -> None:
    entry = make_entry(
        event_id="rent",
        account="Expenses:Housing",
        payee="房东",
        narration="房租",
        amount="-3200.00",
        occurred_at="2026-09-01 22:00:00",
        source_category="生活服务",
        outcome=CORRECTED,
    )

    advice = advisor(entry).advise(
        make_situation(event_id="new"), (*ALLOWED, "Expenses:Housing")
    )

    assert advice.candidates == ()


def test_income_memories_never_leak_into_expense_advice() -> None:
    entry = make_entry(
        event_id="salary",
        account="Income:Salary",
        role="income_account",
        kind="income",
        amount="32.00",
        outcome=CORRECTED,
    )

    advice = advisor(entry).advise(
        make_situation(event_id="new"), (*ALLOWED, "Income:Salary")
    )

    assert advice.candidates == ()


def test_an_account_the_ledger_no_longer_allows_is_dropped() -> None:
    entry = make_entry(account="Expenses:Food:Quick", outcome=CORRECTED)

    advice = advisor(entry).advise(
        make_situation(event_id="new"), ("Expenses:Food:Delivery", "Expenses:Unknown")
    )

    assert advice.candidates == ()


def test_the_ledger_decides_how_many_candidates_are_worth_reading() -> None:
    entries = [
        make_entry(
            event_id=f"{account}-{index}",
            account=account,
            outcome=CORRECTED,
        )
        for account in ("Expenses:Food:Quick", "Expenses:Food:Delivery")
        for index in range(2)
    ]

    advice = advisor(*entries, policy=AdvicePolicy(max_candidates=1)).advise(
        make_situation(event_id="new"), ALLOWED
    )

    assert len(advice.candidates) == 1
