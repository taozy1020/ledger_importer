"""The boundary between the deterministic import and semantic classification.

Milestone 1 runs without any model. Adapters, normalization and rendering decide
everything that can be derived from the statements themselves; the contra account
of a plain expense or income is left unknown instead of guessed.

Milestone 2 plugs an implementation of `SemanticClassifier` into this same
interface. Nothing outside this module needs to know whether a model exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

ACCEPTED = "accepted"
UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ClassificationRequest:
    """The only facts a semantic classifier is allowed to see."""

    event_id: str
    kind: str
    role: str
    transaction_date: date
    occurred_at: str
    amount: Decimal
    currency: str
    payee: str
    narration: str
    source_category: str
    source_types: tuple[str, ...]
    allowed_accounts: tuple[str, ...]
    unknown_account: str


@dataclass(frozen=True, slots=True)
class Classification:
    """An account choice that already passed the allowlist, or the unknown one."""

    account: str
    uncertain: bool
    reason: str
    model_id: str
    status: str


class SemanticClassifier(Protocol):
    def classify(self, request: ClassificationRequest) -> Classification:
        """Choose one allowed account, or the unknown account when unsafe."""

        ...


class UnknownClassifier:
    """Milestone 1: keep the direction that is certain, refuse to invent a category."""

    def classify(self, request: ClassificationRequest) -> Classification:
        return unknown(request, "未启用语义分类，按金额方向归入未知账户")


def unknown(
    request: ClassificationRequest,
    reason: str,
    model_id: str = "",
) -> Classification:
    """Fall back to the configured unknown account without failing the import."""

    return Classification(
        account=request.unknown_account,
        uncertain=True,
        reason=reason[:200],
        model_id=model_id,
        status=UNKNOWN,
    )


def allowed_accounts_for(
    role: str,
    expense_accounts: Sequence[str],
    income_accounts: Sequence[str],
) -> tuple[str, ...]:
    if role == "income_account":
        return tuple(income_accounts)
    return tuple(expense_accounts)
