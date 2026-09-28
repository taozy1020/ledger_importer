"""Convert a batch of WeChat, Alipay, and Bank of China CSVs to Beancount."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

from beancount.parser import printer

from bean_import.customer_config import load_customer_config
from bean_import.pipeline import import_files


def convert_batch(inputs: list[Path], output_path: Path, config_path: Path) -> int:
    """Write balanced transactions for one customer config and its statements."""

    config = load_customer_config(config_path)
    entries = import_files(inputs, config)
    output = StringIO()
    printer.print_entries(entries, file=output)  # pyright: ignore[reportUnknownMemberType]
    output_path.write_text(output.getvalue(), encoding="utf-8")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="Statement CSV files")
    parser.add_argument("--config", type=Path, required=True, help="Customer TOML")
    parser.add_argument("--output", type=Path, required=True, help="Output .bean file")
    args = parser.parse_args()
    count = convert_batch(args.files, args.output, args.config)
    print(f"Wrote {count} transactions to {args.output}")
