"""Read back what a ledger actually says, keyed by `event_id`.

The join key is metadata the importer already writes and Fava preserves across
saves and later hand edits. That is the whole reason a decision can be
harvested months after the statement it came from was deleted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from beancount import loader
from beancount.core.data import Directive, Transaction

from bean_import.core.journal import LedgerOutcome
from bean_import.core.render import EVENT_ID


class LedgerReadError(ValueError):
    """The ledger could not be read."""


def outcomes_from(entries: Iterable[Directive]) -> dict[str, LedgerOutcome]:
    """Index transactions by `event_id`, keeping the last one written."""

    found: dict[str, LedgerOutcome] = {}
    for entry in entries:
        if not isinstance(entry, Transaction):
            continue
        event_id = entry.meta.get(EVENT_ID) if entry.meta else None
        if not isinstance(event_id, str) or not event_id:
            continue
        found[event_id] = LedgerOutcome(
            event_id=event_id,
            accounts=tuple(posting.account for posting in entry.postings),
            on=entry.date,
        )
    return found


class DirectiveOutcomes:
    """Outcomes from directives already in memory, such as Fava's `existing`."""

    def __init__(self, entries: Iterable[Directive]) -> None:
        self._outcomes = outcomes_from(entries)

    def outcomes(self) -> Mapping[str, LedgerOutcome]:
        return self._outcomes


class LedgerFile:
    """Outcomes from a Beancount file on disk, loaded once per harvest."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def outcomes(self) -> Mapping[str, LedgerOutcome]:
        if not self.path.is_file():
            raise LedgerReadError(f"Ledger not found: {self.path}")
        entries, _errors, _options = loader.load_file(str(self.path))
        return outcomes_from(entries)
