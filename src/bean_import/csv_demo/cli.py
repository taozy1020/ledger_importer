"""Command-line entry point for running the first vertical slice by hand."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

from beancount.parser import printer

from bean_import.csv_demo.config import load_config
from bean_import.csv_demo.csv_source import read_records
from bean_import.csv_demo.mapping import map_record


def convert_csv(input_path: Path, output_path: Path, config_path: Path) -> int:
    """Convert configured CSV rows to Beancount text without touching a ledger."""

    config = load_config(config_path)
    records = read_records(input_path, config)
    entries = [map_record(record, config, input_path) for record in records]

    output = StringIO()
    printer.print_entries(entries, file=output)  # pyright: ignore[reportUnknownMemberType]
    output_path.write_text(output.getvalue(), encoding="utf-8")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSV file to import")
    parser.add_argument("output", type=Path, help="Output .bean file")
    parser.add_argument("--config", type=Path, required=True, help="TOML mapping")
    args = parser.parse_args()

    count = convert_csv(args.input, args.output, args.config)
    print(f"Wrote {count} transactions to {args.output}")
