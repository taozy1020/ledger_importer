"""Fava import configuration for the platform prototype.

Fava shows one import entry: this config file itself. Selecting it imports every
statement in `[batch].folder`, so new downloads need no edit here.
"""

from pathlib import Path

from bean_import.batch_importer import PlatformBatchImporter
from bean_import.customer_config import load_customer_config

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "ledger.toml"
CUSTOMER = load_customer_config(LEDGER)

CONFIG = [PlatformBatchImporter(CUSTOMER, LEDGER)]
HOOKS = []
