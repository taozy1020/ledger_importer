"""Beangulp entry points for one statement or a multi-file batch manifest."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path, PurePosixPath
from typing import cast

from beancount.core.data import Directive
from beangulp.importer import Importer

from bean_import.customer_config import CustomerConfig
from bean_import.pipeline import import_files
from bean_import.sources import detect_kind, read_platform_file
from bean_import.sources.common import MAX_STATEMENT_BYTES, SourceParseError, read_text


class BatchError(ValueError):
    """A batch manifest cannot be imported safely."""


class PlatformImporter(Importer):
    """Import one WeChat, Alipay, or Bank of China CSV through the pipeline."""

    def __init__(self, config: CustomerConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return "WeChat / Alipay / BOC statement"

    def identify(self, filepath: str) -> bool:
        path = Path(filepath)
        if path.suffix.lower() in {".pdf", ".eml", ".json"}:
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
    """Import a JSON manifest that lists several statements from one batch."""

    def __init__(self, config: CustomerConfig, root: Path) -> None:
        self.config = config
        self.root = root

    @property
    def name(self) -> str:
        return "WeChat + Alipay + BOC batch"

    def identify(self, filepath: str) -> bool:
        path = Path(filepath)
        if not path.name.endswith(".batch.json"):
            return False
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(raw, dict):
            return False
        item = cast(dict[str, object], raw)
        version = item.get("version")
        files = item.get("files")
        file_list = cast(list[object], files) if isinstance(files, list) else []
        return (
            isinstance(version, int)
            and not isinstance(version, bool)
            and version == 1
            and len(file_list) > 0
        )

    def account(self, filepath: str) -> str:
        del filepath
        return self.config.require_account("boc_debit")

    def date(self, filepath: str) -> date:
        records = [
            record
            for path in load_batch_files(filepath, self.root)
            for record in read_platform_file(path, self.config)
        ]
        if not records:
            raise BatchError(f"{filepath} contains no transaction rows")
        return min(record.transaction_date for record in records)

    def filename(self, filepath: str) -> str:
        return Path(filepath).name

    def extract(
        self,
        filepath: str,
        existing: Sequence[Directive],
    ) -> list[Directive]:
        files = load_batch_files(filepath, self.root)
        return list(import_files(files, self.config, existing))


def load_batch_files(path: str | Path, root: Path) -> list[Path]:
    """Resolve manifest paths and keep every statement inside ``root``."""

    manifest = Path(path)
    try:
        raw: object = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BatchError(f"Cannot read batch manifest {manifest}: {error}") from error
    if not isinstance(raw, dict):
        raise BatchError("Batch manifest must be a JSON object")
    item = cast(dict[str, object], raw)
    version = item.get("version")
    if isinstance(version, bool) or version != 1:
        raise BatchError("Batch manifest must have integer version=1")
    files = item.get("files")
    if not isinstance(files, list) or not files:
        raise BatchError("Batch manifest field 'files' must be a non-empty list")
    return [_resolve(root, manifest, value) for value in cast(list[object], files)]


def _resolve(root: Path, manifest: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BatchError("Manifest file paths must be relative strings")
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts:
        raise BatchError(f"Manifest path {value!r} escapes the batch root")
    path = manifest.parent.joinpath(*relative.parts).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise BatchError(f"Manifest path {value!r} escapes the batch root") from error
    if not path.is_file():
        raise BatchError(f"Statement does not exist: {value}")
    if path.stat().st_size > MAX_STATEMENT_BYTES:
        raise BatchError(f"Statement is too large: {value}")
    return path
