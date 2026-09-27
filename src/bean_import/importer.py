"""Beangulp adapter that connects the CSV core to Fava's Import page."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from beancount.core.data import Directive
from beangulp.importer import Importer

from bean_import.config import CsvImportConfig
from bean_import.csv_source import can_read, read_records
from bean_import.mapping import map_record


class CsvMappingImporter(Importer):
    """A small Beangulp importer for the canonical CSV schema in this project."""

    def __init__(self, config: CsvImportConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.importer_name

    def identify(self, filepath: str) -> bool:
        return can_read(filepath, self.config)

    def account(self, filepath: str) -> str:
        del filepath
        return self.config.source_account

    def date(self, filepath: str) -> date:
        records = read_records(filepath, self.config)
        if not records:
            raise ValueError(f"{filepath} contains no transaction rows")
        return records[0].transaction_date

    def filename(self, filepath: str) -> str:
        return Path(filepath).name

    def extract(
        self,
        filepath: str,
        existing: Sequence[Directive],
    ) -> list[Directive]:
        del existing
        records = read_records(filepath, self.config)
        return [map_record(record, self.config, filepath) for record in records]
