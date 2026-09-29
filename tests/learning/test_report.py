"""Measuring the importer against the person using it."""

from __future__ import annotations

from bean_import.core.journal import (
    ABSTAINED,
    ACCEPTED,
    CORRECTED,
    SPLIT,
    JournalEntry,
)
from bean_import.learning.report import format_report, report_for
from tests.helpers import make_entry


def journal() -> list[JournalEntry]:
    return [
        make_entry(
            event_id="a",
            proposed="Expenses:Food:Quick",
            account="Expenses:Food:Quick",
            outcome=ACCEPTED,
        ),
        make_entry(
            event_id="b",
            proposed="Expenses:Food:Quick",
            account="Expenses:Food:Delivery",
            outcome=CORRECTED,
        ),
        make_entry(
            event_id="c",
            proposed="Expenses:Unknown",
            account="Expenses:Unknown",
            outcome=ABSTAINED,
        ),
        make_entry(
            event_id="f",
            proposed="Expenses:Unknown",
            account="Expenses:Food:Delivery",
            outcome=CORRECTED,
        ),
        make_entry(event_id="d", account="", outcome=SPLIT),
        make_entry(event_id="e", outcome=None),
    ]


def test_coverage_and_precision_pull_against_each_other() -> None:
    report = report_for(journal())

    assert (report.total, report.settled, report.pending) == (6, 5, 1)
    assert (report.kept, report.overridden) == (1, 1)
    assert (report.left_unknown, report.split) == (1, 1)
    assert report.precision == 0.5
    assert report.coverage == 0.4


def test_an_abstention_the_person_answered_is_a_label_not_a_wrong_guess() -> None:
    report = report_for(journal())

    assert report.labelled == 1
    assert report.predicted == 2
    assert report.learnable == 3
    assert all(
        confusion.predicted != "Expenses:Unknown" for confusion in report.confusions
    )


def test_a_milestone_that_never_commits_reports_no_accuracy_at_all() -> None:
    entries = [
        make_entry(
            event_id="a",
            proposed="Expenses:Unknown",
            account="Expenses:Food:Quick",
            outcome=CORRECTED,
        ),
        make_entry(
            event_id="b",
            proposed="Expenses:Unknown",
            account="Expenses:Unknown",
            outcome=ABSTAINED,
        ),
    ]

    report = report_for(entries)

    assert (report.predicted, report.coverage, report.precision) == (0, 0.0, 0.0)
    assert report.learnable == 1
    assert "覆盖率 0%" in format_report(report)


def test_the_confusion_list_names_what_to_fix_first() -> None:
    report = report_for(journal())

    assert report.confusions[0].predicted == "Expenses:Food:Quick"
    assert report.confusions[0].chosen == "Expenses:Food:Delivery"
    assert report.confusions[0].count == 1


def test_each_account_is_scored_as_a_prediction_and_as_an_answer() -> None:
    rows = {row.account: row for row in report_for(journal()).rows}

    quick = rows["Expenses:Food:Quick"]
    assert (quick.predicted, quick.kept, quick.overridden) == (2, 1, 1)
    assert quick.precision == 0.5
    assert rows["Expenses:Food:Delivery"].chosen == 2


def test_an_empty_journal_reports_zeroes_instead_of_dividing_by_them() -> None:
    report = report_for([])

    assert report.precision == 0.0
    assert report.coverage == 0.0
    assert "记录 0 条" in format_report(report)


def test_the_text_report_names_the_numbers_and_the_confusions() -> None:
    text = format_report(report_for(journal()))

    assert "命中率 50%" in text
    assert "Expenses:Food:Quick -> Expenses:Food:Delivery × 1" in text
