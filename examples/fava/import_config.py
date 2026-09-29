"""Importer configuration loaded by Fava's Import page."""

from pathlib import Path

from bean_import.csv_demo.config import load_config
from bean_import.csv_demo.importer import CsvMappingImporter
from bean_import.csv_demo.related_batch import (
    RelatedBatchConfig,
    RelatedBatchImporter,
)

ROOT = Path(__file__).resolve().parent

bank_config = load_config(ROOT / "bank_mapping.toml")
wallet_config = load_config(ROOT / "wallet_mapping.toml")
alipay_config = load_config(ROOT / "alipay_mapping.toml")

CONFIG = [
    CsvMappingImporter(bank_config),
    CsvMappingImporter(wallet_config),
    RelatedBatchImporter(
        RelatedBatchConfig(
            root=ROOT,
            bank=bank_config,
            alipay=alipay_config,
            date_window_days=2,
        )
    ),
]
HOOKS = []
