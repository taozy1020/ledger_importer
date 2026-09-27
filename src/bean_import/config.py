"""Load and validate the deliberately small TOML mapping configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class CsvColumns:
    """Names of the columns used by the CSV source adapter."""

    date: str = "date"
    amount: str = "amount"
    payee: str = "payee"
    narration: str = "narration"
    category: str = "category"
    source_id: str = "id"


@dataclass(frozen=True, slots=True)
class CsvImportConfig:
    """Everything needed to turn one CSV row into a balanced transaction."""

    source_account: str
    currency: str
    category_accounts: dict[str, str]
    columns: CsvColumns = CsvColumns()
    importer_name: str = "CSV mapping prototype"


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section [{key}] is required")
    return cast(dict[str, Any], value)


def load_config(path: str | Path) -> CsvImportConfig:
    """Load TOML config and fail early when required mapping fields are absent."""

    with Path(path).open("rb") as config_file:
        raw = tomllib.load(config_file)

    source = _require_table(raw, "source")
    importer_value = raw.get("importer", {})
    if not isinstance(importer_value, dict):
        raise ValueError("Configuration section [importer] must be a table")
    importer = cast(dict[str, Any], importer_value)
    columns_raw_value = raw.get("columns", {})
    categories_raw = _require_table(raw, "categories")

    if not isinstance(columns_raw_value, dict):
        raise ValueError("Configuration section [columns] must be a table")
    columns_raw = cast(dict[str, Any], columns_raw_value)

    source_account = source.get("account")
    currency = source.get("currency")
    if not isinstance(source_account, str) or not source_account:
        raise ValueError("[source].account must be a non-empty Beancount account")
    if not isinstance(currency, str) or not currency:
        raise ValueError("[source].currency must be a non-empty currency code")
    importer_name = importer.get("name", "CSV mapping prototype")
    if not isinstance(importer_name, str) or not importer_name:
        raise ValueError("[importer].name must be a non-empty string")
    category_accounts: dict[str, str] = {}
    for category, account in categories_raw.items():
        if not isinstance(account, str) or not account:
            raise ValueError("Every [categories] value must be a non-empty account")
        category_accounts[category] = account

    column_values: dict[str, str] = {}
    for field_name in CsvColumns.__dataclass_fields__:
        value: Any = columns_raw.get(field_name, getattr(CsvColumns(), field_name))
        if not isinstance(value, str) or not value:
            raise ValueError(f"[columns].{field_name} must be a non-empty string")
        column_values[field_name] = value

    return CsvImportConfig(
        source_account=source_account,
        currency=currency,
        category_accounts=category_accounts,
        columns=CsvColumns(**column_values),
        importer_name=importer_name,
    )
