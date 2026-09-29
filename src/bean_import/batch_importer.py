"""Beangulp entry points for one statement or for a whole download folder.

Fava calls an importer with a single file path, so the batch entry point is the
customer's ledger config: identifying it means "import every statement in the
folder it points at". Nothing has to be edited when new statements arrive.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from beancount.core.data import Directive
from beangulp.importer import Importer

from bean_import.customer_config import CustomerConfig
from bean_import.pipeline import import_files
from bean_import.sources import detect_kind, read_platform_file
from bean_import.sources.common import MAX_STATEMENT_BYTES, SourceParseError, read_text

SKIPPED_SUFFIXES = {".pdf", ".eml", ".zip", ".toml", ".bean", ".md", ".json"}


class BatchError(ValueError):
    """A statement folder cannot be imported safely."""


class PlatformImporter(Importer):
    """Import one WeChat, Alipay, or Bank of China CSV through the pipeline."""

    def __init__(self, config: CustomerConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return "WeChat / Alipay / BOC statement"

    def identify(self, filepath: str) -> bool:
        path = Path(filepath)
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            return False
        try:
            return detect_kind(read_text(path)) is not None
        except (OSError, UnicodeError, SourceParseError):
            return False

    def account(self, filepath: str) -> str:
        return read_platform_file(filepath, self.config)[0].source_account

    def date(self, filepath: str) -> date:
        records = read_platform_file(filepath, self.config)
        return min(record.transaction_date for record in records)

    def filename(self, filepath: str) -> str:
        return Path(filepath).name

    def extract(
        self,
        filepath: str,
        existing: Sequence[Directive],
    ) -> list[Directive]:
        return list(import_files([filepath], self.config, existing))


class PlatformBatchImporter(Importer):
    """Import every statement in the folder the customer config points at."""

    def __init__(self, config: CustomerConfig, config_path: Path) -> None:
        self.config = config
        self.config_path = Path(config_path).resolve()

    @property
    def name(self) -> str:
        return f"Statement folder {self.config.batch_folder.name}"

    def identify(self, filepath: str) -> bool:
        try:
            return Path(filepath).resolve() == self.config_path
        except OSError:
            return False

    def account(self, filepath: str) -> str:
        del filepath
        return self.config.sources[0].account

    def date(self, filepath: str) -> date:
        del filepath
        records = [
            record
            for path in statements_in(self.config.batch_folder)
            for record in read_platform_file(path, self.config)
        ]
        if not records:
            raise BatchError(f"{self.config.batch_folder} contains no transaction rows")
        return min(record.transaction_date for record in records)

    def filename(self, filepath: str) -> str:
        del filepath
        return f"{self.config.batch_folder.name}.csv"

    def extract(
        self,
        filepath: str,
        existing: Sequence[Directive],
    ) -> list[Directive]:
        del filepath
        files = statements_in(self.config.batch_folder)
        return list(import_files(files, self.config, existing))


def scan_folder(folder: str | Path) -> tuple[list[Path], list[Path]]:
    """Split one folder into recognized statements and everything else."""

    directory = Path(folder)
    if not directory.is_dir():
        raise BatchError(f"Statement folder does not exist: {directory}")
    statements: list[Path] = []
    skipped: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() in SKIPPED_SUFFIXES:
            skipped.append(path)
            continue
        if path.stat().st_size > MAX_STATEMENT_BYTES:
            raise BatchError(f"Statement is too large: {path.name}")
        try:
            recognized = detect_kind(read_text(path)) is not None
        except (OSError, UnicodeError, SourceParseError):
            recognized = False
        (statements if recognized else skipped).append(path)
    return statements, skipped


def statements_in(folder: str | Path) -> list[Path]:
    """Every statement in the folder, failing when none can be recognized."""

    statements, _ = scan_folder(folder)
    if not statements:
        raise BatchError(f"No recognized statements in {Path(folder)}")
    return statements
