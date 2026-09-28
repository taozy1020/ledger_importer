"""Shared readers for the platform statement adapters.

Column layouts follow the public exports handled by china_bean_importers (MIT).
These adapters stop at source records and do not reuse that project's account
matching.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

MAX_STATEMENT_BYTES = 8 * 1024 * 1024
CARD_TAIL = re.compile(r"[（(](\d{4})[)）]")
CURRENCY_CODES = {
    "人民币": "CNY",
    "CNY": "CNY",
    "美元": "USD",
    "USD": "USD",
    "港币": "HKD",
    "HKD": "HKD",
}


class SourceParseError(ValueError):
    """A statement file cannot be turned into source records."""


def read_text(path: str | Path) -> str:
    """Read a UTF-8 or GBK statement, rejecting oversized files."""

    file_path = Path(path)
    data = file_path.read_bytes()
    if len(data) > MAX_STATEMENT_BYTES:
        raise SourceParseError(f"{file_path.name} exceeds the statement size limit")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeError:
        try:
            return data.decode("gbk")
        except UnicodeError as error:
            raise SourceParseError(
                f"{file_path.name} is neither UTF-8 nor GBK"
            ) from error


def csv_rows(text: str) -> list[tuple[int, list[str]]]:
    rows: list[tuple[int, list[str]]] = []
    for row_number, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        rows.append((row_number, [cell.strip() for cell in row]))
    return rows


def find_header(
    rows: list[tuple[int, list[str]]],
    required: set[str],
) -> tuple[int, dict[str, int]]:
    for row_number, cells in rows:
        present = set(cells)
        if not required <= present:
            continue
        return row_number, {name: cells.index(name) for name in required}
    missing = ", ".join(sorted(required))
    raise SourceParseError(f"Statement header is missing columns: {missing}")


def find_amount_column(cells: list[str]) -> int | None:
    for index, cell in enumerate(cells):
        if cell == "金额" or cell.startswith("金额(") or cell.startswith("金额（"):
            return index
    return None


def cell(cells: list[str], columns: dict[str, int], key: str, row_number: int) -> str:
    index = columns[key]
    if index >= len(cells):
        raise SourceParseError(f"Row {row_number} is missing column {key}")
    return cells[index]


def blank(value: str) -> bool:
    text = value.strip()
    return not text or set(text) <= set("-—/")


def parse_date(value: str, row_number: int) -> date:
    text = value.strip().split()[0] if value.strip() else ""
    if len(text) == 8 and text.isdigit():
        text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise SourceParseError(f"Row {row_number} has an invalid date") from error


def parse_amount(value: str, row_number: int) -> Decimal:
    cleaned = (
        value.strip()
        .replace("¥", "")
        .replace("￥", "")
        .replace(",", "")
        .replace(" ", "")
    )
    if not cleaned:
        raise SourceParseError(f"Row {row_number} has an empty amount")
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise SourceParseError(f"Row {row_number} has an invalid amount") from error


def currency_code(value: str, row_number: int) -> str:
    code = CURRENCY_CODES.get(value.strip())
    if code is None:
        raise SourceParseError(
            f"Row {row_number} has an unsupported currency {value!r}"
        )
    return code


def card_tail(value: str) -> str:
    match = CARD_TAIL.search(value)
    return match.group(1) if match else ""


def fingerprint(source_type: str, raw_fields: dict[str, str]) -> str:
    canonical = "|".join(f"{key}={raw_fields[key]}" for key in sorted(raw_fields))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{source_type}:{digest}"


def reject_duplicate_ids(source_ids: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for source_id in source_ids:
        if source_id in seen and source_id not in duplicates:
            duplicates.append(source_id)
        seen.add(source_id)
    if duplicates:
        raise SourceParseError(
            f"{label} file contains duplicate source IDs: {', '.join(duplicates)}"
        )
