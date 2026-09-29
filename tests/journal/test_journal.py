"""The journal: round trips, idempotent recording, and settling decisions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from bean_import.core.advice import Advice, Candidate
from bean_import.core.journal import ACCEPTED, CORRECTED, Decision
from bean_import.journal.codec import JournalFormatError, decode, encode
from bean_import.journal.jsonl import JsonlJournal
from bean_import.journal.memory import InMemoryJournal, NullJournal
from tests.helpers import make_entry


def test_an_entry_survives_a_round_trip_with_its_features_intact() -> None:
    entry = make_entry(
        advice=Advice((Candidate("Expenses:Food:Quick", 0.5, 3, "3 笔相似记录"),)),
    )

    restored = decode(encode(entry))

    assert restored == entry
    assert restored.situation.tokens == entry.situation.tokens
    assert restored.proposal.advice.candidates[0].support == 3


def test_a_record_written_by_a_newer_version_is_refused_not_guessed() -> None:
    payload = encode(make_entry())
    payload["version"] = 99

    with pytest.raises(JournalFormatError, match="unsupported journal version"):
        decode(payload)


def test_recording_the_same_event_twice_keeps_only_the_last_proposal(
    tmp_path: Path,
) -> None:
    journal = JsonlJournal(tmp_path / "decisions.jsonl")
    journal.record(make_entry(event_id="e1", proposed="Expenses:Food:Quick"))
    journal.record(make_entry(event_id="e1", proposed="Expenses:Food:Delivery"))
    journal.record(make_entry(event_id="e2"))

    entries = journal.entries()

    assert [entry.event_id for entry in entries] == ["e1", "e2"]
    assert entries[0].proposal.account == "Expenses:Food:Delivery"


def test_re_importing_a_statement_does_not_forget_an_earlier_decision(
    tmp_path: Path,
) -> None:
    journal = JsonlJournal(tmp_path / "decisions.jsonl")
    journal.record(
        make_entry(
            event_id="e1",
            proposed="Expenses:Unknown",
            account="Expenses:Food:Quick",
            outcome=CORRECTED,
        )
    )
    journal.record(
        make_entry(event_id="e1", proposed="Expenses:Food:Quick", outcome=None)
    )

    entry = journal.entries()[0]

    assert entry.decision is not None
    assert entry.decision.account == "Expenses:Food:Quick"
    assert entry.proposal.account == "Expenses:Unknown", (
        "a settled record must not be rewritten with a proposal nobody saw"
    )


def test_settling_rewrites_the_file_compacted(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "decisions.jsonl"
    journal = JsonlJournal(path)
    journal.record(make_entry(event_id="e1"))
    journal.record(make_entry(event_id="e1"))
    decision = Decision(CORRECTED, "Expenses:Food:Quick", date(2026, 9, 3))

    landed = journal.settle({"e1": decision, "missing": decision})

    assert landed == 1
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 1
    assert journal.entries()[0].decision == decision


def test_an_unreadable_line_is_reported_with_its_position(tmp_path: Path) -> None:
    path = tmp_path / "decisions.jsonl"
    journal = JsonlJournal(path)
    journal.record(make_entry(event_id="e1"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")

    with pytest.raises(JournalFormatError, match="decisions.jsonl:2"):
        journal.entries()


def test_a_missing_file_is_an_empty_journal_not_an_error(tmp_path: Path) -> None:
    assert JsonlJournal(tmp_path / "absent.jsonl").entries() == ()


def test_the_in_memory_journal_behaves_like_the_file_one() -> None:
    journal = InMemoryJournal([make_entry(event_id="e1")])
    journal.record(make_entry(event_id="e1", proposed="Expenses:Food:Quick"))
    decision = Decision(ACCEPTED, "Expenses:Food:Quick", date(2026, 9, 3))

    assert journal.settle({"e1": decision}) == 1
    assert journal.entries()[0].decision == decision


def test_the_null_journal_records_nothing_and_still_satisfies_the_port() -> None:
    journal = NullJournal()
    journal.record(make_entry())

    assert journal.entries() == ()
    assert journal.settle({"e1": Decision(ACCEPTED, "x", date(2026, 9, 3))}) == 0
