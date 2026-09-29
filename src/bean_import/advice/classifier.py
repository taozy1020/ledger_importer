"""Turn strong advice into a proposal, when the ledger asks for it.

Off by default. The person reviewing is the classifier until they say
otherwise, and a wrong auto-filled account is worse than an obvious blank.
"""

from __future__ import annotations

from bean_import.core.advice import Advice
from bean_import.core.classification import (
    Classification,
    ClassificationRequest,
    accept,
    unknown,
)

HISTORY_MODEL_ID = "history"


class HistoryClassifier:
    """Accept the top candidate once it clears a threshold the ledger sets."""

    def __init__(self, threshold: float) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("history threshold must be inside (0, 1]")
        self.threshold = threshold

    def classify(
        self,
        request: ClassificationRequest,
        advice: Advice,
    ) -> Classification:
        top = advice.top
        if top is None or top.confidence < self.threshold:
            return unknown(request, "历史证据不足以自动归类", HISTORY_MODEL_ID)
        if top.account not in request.allowed_accounts:
            return unknown(request, "历史候选账户已不在允许列表中", HISTORY_MODEL_ID)
        return accept(top.account, top.evidence, HISTORY_MODEL_ID)
