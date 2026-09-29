"""The contract between the deterministic import and anything that guesses.

Milestone 1 runs without any model. Adapters, normalization and rendering decide
everything that can be derived from the statements themselves; the contra
account of a plain expense or income is left unknown instead of guessed.

Milestone 2 plugs an implementation of `SemanticClassifier` into this same
interface. Nothing outside this module needs to know whether a model exists,
and no implementation can widen the allowlist or fail the import.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ACCEPTED = "accepted"
UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ClassificationRequest:
    """The only facts a classifier is allowed to see."""

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
    known_accounts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Classification:
    """An account choice that already passed the allowlist, or the unknown one."""

    account: str
    uncertain: bool
    reason: str
    model_id: str
    status: str

    @property
    def resolved(self) -> bool:
        return self.status == ACCEPTED


def accept(
    account: str,
    reason: str,
    model_id: str,
) -> Classification:
    """Take responsibility for an account that the caller already validated."""

    return Classification(
        account=account,
        uncertain=False,
        reason=reason[:200],
        model_id=model_id,
        status=ACCEPTED,
    )


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
