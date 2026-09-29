"""Convert a folder of WeChat, Alipay, and Bank of China statements to Beancount.

With no file arguments the importer reads `[batch].folder` from the customer
config, so downloading new statements into that folder is the whole workflow.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

from beancount.parser import printer

from bean_import.batch_importer import scan_folder
from bean_import.customer_config import CustomerConfig, load_customer_config
from bean_import.pipeline import import_files


def collect_statements(
    inputs: Sequence[Path],
    config: CustomerConfig,
) -> tuple[list[Path], list[Path]]:
    """Expand folders into statements; no argument means the configured folder."""

    targets = list(inputs) or [config.batch_folder]
    statements: list[Path] = []
    skipped: list[Path] = []
    for target in targets:
        if target.is_dir():
            found, ignored = scan_folder(target)
            statements.extend(found)
            skipped.extend(ignored)
        else:
            statements.append(target)
    return statements, skipped


def convert_batch(
    inputs: Sequence[Path],
    output_path: Path,
    config_path: Path,
) -> tuple[int, list[Path]]:
    """Write balanced transactions for one customer config and its statements."""

    config = load_customer_config(config_path)
    statements, skipped = collect_statements(inputs, config)
    entries = import_files(statements, config)
    output = StringIO()
    printer.print_entries(entries, file=output)  # pyright: ignore[reportUnknownMemberType]
    output_path.write_text(output.getvalue(), encoding="utf-8")
    return len(entries), skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Statement files or folders; defaults to [batch].folder",
    )
    parser.add_argument("--config", type=Path, required=True, help="Customer TOML")
    parser.add_argument("--output", type=Path, required=True, help="Output .bean file")
    args = parser.parse_args()
    count, skipped = convert_batch(args.files, args.output, args.config)
    print(f"Wrote {count} transactions to {args.output}")
    if skipped:
        names = ", ".join(path.name for path in skipped)
        print(f"Skipped {len(skipped)} unrecognized files: {names}")
