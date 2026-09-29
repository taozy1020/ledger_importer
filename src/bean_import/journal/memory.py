"""Journals that keep nothing on disk."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from bean_import.core.journal import Decision, JournalEntry, merge


class NullJournal:
    """Record nothing. The import still runs; there is just nothing to learn."""

    def record(self, entry: JournalEntry) -> None:
        del entry

    def entries(self) -> tuple[JournalEntry, ...]:
        return ()

    def settle(self, decisions: Mapping[str, Decision]) -> int:
        del decisions
        return 0


class InMemoryJournal:
    """A real journal without a file, for tests and for dry runs."""

    def __init__(self, entries: Iterable[JournalEntry] = ()) -> None:
        self._entries: dict[str, JournalEntry] = {
            entry.event_id: entry for entry in entries
        }

    def record(self, entry: JournalEntry) -> None:
        self._entries[entry.event_id] = merge(self._entries.get(entry.event_id), entry)

    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries.values())

    def settle(self, decisions: Mapping[str, Decision]) -> int:
        landed = 0
        for event_id, decision in decisions.items():
            entry = self._entries.get(event_id)
            if entry is None:
                continue
            self._entries[event_id] = entry.with_decision(decision)
            landed += 1
        return landed
