"""Classifiers that need no outside world, and the way to chain them."""

from __future__ import annotations

from bean_import.core.advice import Advice
from bean_import.core.classification import (
    Classification,
    ClassificationRequest,
    unknown,
)
from bean_import.core.ports import SemanticClassifier

NO_MODEL_REASON = "未启用语义分类，按金额方向归入未知账户"


class UnknownClassifier:
    """Milestone 1: keep the direction that is certain, refuse to invent a category."""

    def classify(
        self,
        request: ClassificationRequest,
        advice: Advice,
    ) -> Classification:
        del advice
        return unknown(request, NO_MODEL_REASON)


class FirstResolved:
    """Try classifiers in order and take the first one that commits.

    This is how a ledger runs history first and a model only for what history
    cannot place, without either of them knowing the other exists.
    """

    def __init__(self, *classifiers: SemanticClassifier) -> None:
        if not classifiers:
            raise ValueError("FirstResolved needs at least one classifier")
        self._classifiers = classifiers

    def classify(
        self,
        request: ClassificationRequest,
        advice: Advice,
    ) -> Classification:
        result = unknown(request, NO_MODEL_REASON)
        for classifier in self._classifiers:
            result = classifier.classify(request, advice)
            if result.resolved:
                return result
        return result
