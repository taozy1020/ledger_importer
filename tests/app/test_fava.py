"""What Fava re-offers on the second import.

Beangulp decides "already imported" by comparing accounts and amounts. That
works right up until the first review, because reviewing *is* changing the
account — after which the same statement row no longer resembles its own
ledger entry and comes back as new. Since people drop next month's download
into the same folder, this is the normal case, not an edge case.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from beancount.core.amount import Amount
from beancount.core.data import Open, Posting, Transaction
from beangulp.extract import DUPLICATE

from bean_import.app.fava import mark_known_events
from tests.helpers import make_transaction


def posting(account: str, number: str) -> Posting:
    return Posting(account, Amount(Decimal(number), "CNY"), None, None, None, None)


def corrected(entry: Transaction, account: str) -> Transaction:
    """The same transaction after a person fixed the unknown account."""

    postings = [
        posting._replace(account=account)
        if posting.account == "Expenses:Unknown"
        else posting
        for posting in entry.postings
    ]
    return entry._replace(postings=postings)


def imported() -> Transaction:
    return make_transaction(
        "abc123",
        {"Assets:Bank:BOC:Debit": "-32", "Expenses:Unknown": "32"},
    )


def test_a_transaction_the_person_recategorized_is_still_a_duplicate() -> None:
    fresh = imported()
    existing = corrected(imported(), "Expenses:Food:Quick")

    assert mark_known_events([fresh], [existing]) == 1
    assert fresh.meta[DUPLICATE] is existing, "the report should name what it repeats"


def test_a_transaction_the_person_split_across_accounts_is_still_a_duplicate() -> None:
    fresh = imported()
    existing = imported()._replace(
        postings=[
            posting(account, number)
            for account, number in (
                ("Assets:Bank:BOC:Debit", "-32"),
                ("Expenses:Food:Quick", "20"),
                ("Expenses:Gifts", "12"),
            )
        ]
    )

    assert mark_known_events([fresh], [existing]) == 1


def test_a_genuinely_new_row_is_left_alone() -> None:
    fresh = imported()

    assert mark_known_events([fresh], [make_transaction("other", {})]) == 0
    assert DUPLICATE not in fresh.meta


def test_ledger_entries_without_an_event_id_cannot_mask_anything() -> None:
    fresh = imported()
    handwritten = imported()._replace(meta={"filename": "main.bean", "lineno": 1})
    other = Open({}, date(2026, 1, 1), "Expenses:Food:Quick", [], None)

    assert mark_known_events([fresh], [handwritten, other]) == 0


def test_a_blank_event_id_on_both_sides_does_not_match_itself() -> None:
    fresh = imported()._replace(meta={"event_id": ""})
    existing = imported()._replace(meta={"event_id": ""})

    assert mark_known_events([fresh], [existing]) == 0


def test_marking_twice_counts_once_so_the_report_stays_honest() -> None:
    fresh = imported()
    existing = corrected(imported(), "Expenses:Food:Quick")

    assert mark_known_events([fresh], [existing]) == 1
    assert mark_known_events([fresh], [existing]) == 0
