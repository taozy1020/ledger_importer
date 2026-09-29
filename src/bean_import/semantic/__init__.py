"""Milestone 2: optional life-context classification behind `SemanticClassifier`.

Nothing in this package is imported by the deterministic stages. Only
`bean_import.app.factory`, which composes the import, reaches in here, and only
when the customer configured a model. Deleting this directory leaves milestone
1 working.
"""

from bean_import.semantic.knowledge import (
    LifeContext,
    describe_situation,
    memory_from_advice,
    memory_from_ledger,
)
from bean_import.semantic.llm import (
    ClassifierError,
    OpenAICompatibleClassifier,
    urllib_transport,
)

__all__ = [
    "ClassifierError",
    "LifeContext",
    "OpenAICompatibleClassifier",
    "describe_situation",
    "memory_from_advice",
    "memory_from_ledger",
    "urllib_transport",
]
