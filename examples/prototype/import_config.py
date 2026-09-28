"""Fava import configuration for the platform prototype."""

from pathlib import Path

from bean_import.batch_importer import PlatformBatchImporter, PlatformImporter
from bean_import.customer_config import load_customer_config

ROOT = Path(__file__).resolve().parent
CUSTOMER = load_customer_config(ROOT / "ledger.toml")

CONFIG = [
    PlatformImporter(CUSTOMER),
    PlatformBatchImporter(CUSTOMER, ROOT),
]
HOOKS = []
