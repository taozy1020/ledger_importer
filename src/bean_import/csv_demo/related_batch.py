"""Safely reconcile a bank CSV and related Alipay details in one batch."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path, PurePosixPath
from typing import cast

from beancount.core.data import Directive, Transaction
from beangulp.importer import Importer

from bean_import.core.models import SourceRecord
from bean_import.csv_demo.config import CsvImportConfig
from bean_import.csv_demo.csv_source import read_records
from bean_import.csv_demo.mapping import map_record

MAX_RELATED_FILE_BYTES = 8 * 1024 * 1024


class RelatedBatchError(ValueError):
    """The related files cannot be reconciled safely."""


@dataclass(frozen=True, slots=True)
class RelatedBatchConfig:
    """Rules and source accounts for one bank/Alipay related-file batch."""

    root: Path
    bank: CsvImportConfig
    alipay: CsvImportConfig
    importer_name: str = "Bank + Alipay related batch"
    bank_keyword: str = "支付宝"
    funding_method_column: str = "funding_method"
    bank_funding_markers: tuple[str, ...] = ("银行卡", "信用卡")
    balance_funding_markers: tuple[str, ...] = ("余额", "余额宝")
    date_window_days: int = 2

    def __post_init__(self) -> None:
        if self.bank.currency != self.alipay.currency:
            raise ValueError("Bank and Alipay currencies must match for merging")
        if not self.importer_name or not self.bank_keyword.strip():
            raise ValueError("Importer name and bank keyword must not be empty")
        if self.date_window_days < 0:
            raise ValueError("date_window_days must not be negative")
        if not self.funding_method_column:
            raise ValueError("funding_method_column must not be empty")


@dataclass(frozen=True, slots=True)
class RelatedManifest:
    """A bundle file identifies one bank statement and one Alipay statement."""

    batch_id: str
    bank_file: Path
    alipay_file: Path


def _resolve_related_file(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RelatedBatchError(f"Manifest field {field!r} must be a relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise RelatedBatchError(f"Manifest field {field!r} escapes the batch root")

    resolved_root = root.resolve()
    path = resolved_root.joinpath(*relative.parts).resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError as error:
        raise RelatedBatchError(
            f"Manifest field {field!r} resolves outside the batch root"
        ) from error

    if not path.is_file() or path.suffix.casefold() != ".csv":
        raise RelatedBatchError(f"Related CSV does not exist: {value}")
    if path.stat().st_size > MAX_RELATED_FILE_BYTES:
        raise RelatedBatchError(f"Related file is too large: {value}")
    return path


def load_manifest(path: str | Path, root: Path) -> RelatedManifest:
    """Load a versioned JSON manifest and constrain sidecars to ``root``."""

    try:
        raw_value: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RelatedBatchError(
            f"Cannot read merge manifest {path}: {error}"
        ) from error
    if not isinstance(raw_value, dict):
        raise RelatedBatchError("Merge manifest must be a JSON object")
    raw = cast(dict[str, object], raw_value)

    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise RelatedBatchError("Merge manifest must have integer version=1")
    batch_id = raw.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip() or len(batch_id) > 200:
        raise RelatedBatchError("Manifest field 'batch_id' must be 1-200 characters")

    bank_file = _resolve_related_file(root, raw.get("bank_file"), "bank_file")
    alipay_file = _resolve_related_file(root, raw.get("alipay_file"), "alipay_file")
    if bank_file == alipay_file:
        raise RelatedBatchError("bank_file and alipay_file must be different files")
    return RelatedManifest(batch_id.strip(), bank_file, alipay_file)


def _funding_kind(record: SourceRecord, config: RelatedBatchConfig) -> str:
    method = record.raw_fields.get(config.funding_method_column, "").strip().casefold()
    if not method:
        raise RelatedBatchError(
            f"Alipay row {record.row_number} has no "
            f"{config.funding_method_column!r} value"
        )
    is_balance = any(
        marker.casefold() in method for marker in config.balance_funding_markers
    )
    is_bank = any(marker.casefold() in method for marker in config.bank_funding_markers)
    if is_balance == is_bank:
        raise RelatedBatchError(
            f"Alipay row {record.row_number} has unsupported or ambiguous "
            f"funding method {method!r}"
        )
    return "balance" if is_balance else "bank"


def _has_bank_keyword(record: SourceRecord, keyword: str) -> bool:
    return keyword.casefold() in f"{record.payee} {record.narration}".casefold()


def _assert_unique_source_ids(records: list[SourceRecord], label: str) -> None:
    counts = Counter(record.source_id for record in records)
    duplicates = sorted(source_id for source_id, count in counts.items() if count > 1)
    if duplicates:
        raise RelatedBatchError(
            f"{label} file contains duplicate source IDs: {', '.join(duplicates)}"
        )


def _matching_bank_indexes(
    record: SourceRecord,
    candidates: list[tuple[int, SourceRecord]],
    config: RelatedBatchConfig,
) -> list[int]:
    return [
        index
        for index, bank_record in candidates
        if bank_record.amount == record.amount
        and abs((bank_record.transaction_date - record.transaction_date).days)
        <= config.date_window_days
    ]


def _merge_entry(
    bank_record: SourceRecord,
    alipay_record: SourceRecord,
    manifest: RelatedManifest,
    config: RelatedBatchConfig,
) -> Transaction:
    combined_fields = {
        **{f"bank.{key}": value for key, value in bank_record.raw_fields.items()},
        **{f"alipay.{key}": value for key, value in alipay_record.raw_fields.items()},
    }
    enriched = replace(
        bank_record,
        payee=alipay_record.payee or bank_record.payee,
        narration=alipay_record.narration or bank_record.narration,
        category=alipay_record.category,
        raw_fields=combined_fields,
    )
    output_config = replace(
        config.alipay,
        source_account=config.bank.source_account,
        importer_name=config.importer_name,
    )
    entry = map_record(enriched, output_config, manifest.bank_file)
    entry.meta.update(
        {
            "source_kind": "bank_alipay_merge",
            "batch_id": manifest.batch_id,
            "bank_source_id": bank_record.source_id,
            "alipay_source_id": alipay_record.source_id,
            "bank_source_file": manifest.bank_file.name,
            "alipay_source_file": manifest.alipay_file.name,
            "alipay_lineno": alipay_record.row_number,
            "merge_rule": "alipay_keyword_exact_amount_date_v1",
            "__source__": (
                f"bank: {' | '.join(bank_record.raw_fields.values())}; "
                f"alipay: {' | '.join(alipay_record.raw_fields.values())}"
            ),
        }
    )
    return entry


def merge_related_records(
    manifest: RelatedManifest,
    bank_records: list[SourceRecord],
    alipay_records: list[SourceRecord],
    config: RelatedBatchConfig,
) -> list[Transaction]:
    """Merge only unique, evidence-backed pairs; fail closed on card orphans."""

    _assert_unique_source_ids(bank_records, "Bank")
    _assert_unique_source_ids(alipay_records, "Alipay")
    bank_candidates = [
        (index, record)
        for index, record in enumerate(bank_records)
        if _has_bank_keyword(record, config.bank_keyword)
    ]

    card_records: list[SourceRecord] = []
    balance_records: list[SourceRecord] = []
    for record in alipay_records:
        if _funding_kind(record, config) == "balance":
            balance_records.append(record)
        else:
            card_records.append(record)

    matched_by_bank: dict[int, SourceRecord] = {}
    for alipay_record in card_records:
        matches = _matching_bank_indexes(alipay_record, bank_candidates, config)
        if len(matches) != 1:
            reason = "no match" if not matches else "ambiguous matches"
            raise RelatedBatchError(
                f"Alipay bank-funded row {alipay_record.row_number} "
                f"({alipay_record.source_id}) has {reason}; expected exactly "
                f"one keyword-matched bank row with equal amount and date within "
                f"{config.date_window_days} day(s)"
            )
        bank_index = matches[0]
        if bank_index in matched_by_bank:
            bank_record = bank_records[bank_index]
            raise RelatedBatchError(
                f"Multiple Alipay rows match bank row {bank_record.row_number} "
                f"({bank_record.source_id}); refusing a many-to-one merge"
            )
        matched_by_bank[bank_index] = alipay_record

    entries: list[Transaction] = []
    for index, bank_record in enumerate(bank_records):
        alipay_record = matched_by_bank.get(index)
        if alipay_record is None:
            entry = map_record(bank_record, config.bank, manifest.bank_file)
            entry.meta.update(
                {
                    "source_kind": "bank",
                    "batch_id": manifest.batch_id,
                    "bank_source_id": bank_record.source_id,
                    "bank_source_file": manifest.bank_file.name,
                }
            )
        else:
            entry = _merge_entry(bank_record, alipay_record, manifest, config)
        entries.append(entry)

    for alipay_record in balance_records:
        entry = map_record(alipay_record, config.alipay, manifest.alipay_file)
        entry.meta["source_kind"] = "alipay_balance"
        entry.meta["batch_id"] = manifest.batch_id
        entry.meta["alipay_source_id"] = alipay_record.source_id
        entry.meta["alipay_source_file"] = manifest.alipay_file.name
        entries.append(entry)
    return entries


class RelatedBatchImporter(Importer):
    """Import a manifest that groups one bank and one Alipay CSV."""

    def __init__(self, config: RelatedBatchConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.importer_name

    def identify(self, filepath: str) -> bool:
        return Path(filepath).name.endswith(".merge.json")

    def account(self, filepath: str) -> str:
        del filepath
        return self.config.bank.source_account

    def _read(
        self,
        filepath: str,
    ) -> tuple[RelatedManifest, list[SourceRecord], list[SourceRecord]]:
        manifest = load_manifest(filepath, self.config.root)
        bank_records = read_records(manifest.bank_file, self.config.bank)
        alipay_records = read_records(manifest.alipay_file, self.config.alipay)
        if not bank_records:
            raise RelatedBatchError("Bank statement contains no transaction rows")
        if not alipay_records:
            raise RelatedBatchError("Alipay statement contains no transaction rows")
        return manifest, bank_records, alipay_records

    def date(self, filepath: str) -> date:
        _, bank_records, alipay_records = self._read(filepath)
        return min(
            record.transaction_date for record in [*bank_records, *alipay_records]
        )

    def filename(self, filepath: str) -> str:
        return Path(filepath).name

    def extract(
        self,
        filepath: str,
        existing: Sequence[Directive],
    ) -> list[Directive]:
        del existing
        manifest, bank_records, alipay_records = self._read(filepath)
        return list(
            merge_related_records(manifest, bank_records, alipay_records, self.config)
        )
