"""An append-only JSONL journal beside the ledger.

Appending is the only write on the import path, so an interrupted Fava extract
can never corrupt earlier records. Fava may extract the same folder several
times before anything is saved, so reading keeps the last record per
`event_id`; settling a harvest rewrites the file compacted, through a temporary
file and an atomic replace.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from bean_import.core.journal import Decision, JournalEntry, merge
from bean_import.journal.codec import JournalFormatError, decode, encode


class JsonlJournal:
    """One JSON object per line, addressed by `event_id`."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, entry: JournalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(encode(entry), ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    def entries(self) -> tuple[JournalEntry, ...]:
        if not self.path.is_file():
            return ()
        found: dict[str, JournalEntry] = {}
        text = self.path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload: object = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise JournalFormatError(
                    f"{self.path}:{number} is not valid JSON"
                ) from error
            entry = decode(payload)
            found[entry.event_id] = merge(found.get(entry.event_id), entry)
        return tuple(found.values())

    def settle(self, decisions: Mapping[str, Decision]) -> int:
        entries = self.entries()
        landed = 0
        updated: list[JournalEntry] = []
        for entry in entries:
            decision = decisions.get(entry.event_id)
            if decision is None:
                updated.append(entry)
                continue
            updated.append(entry.with_decision(decision))
            landed += 1
        self._rewrite(updated)
        return landed

    def _rewrite(self, entries: list[JournalEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        body = "".join(
            f"{json.dumps(encode(entry), ensure_ascii=False, sort_keys=True)}\n"
            for entry in entries
        )
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, self.path)
