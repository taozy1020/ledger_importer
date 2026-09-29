"""The no-model classifier and the chain that lets others take over."""

from __future__ import annotations

import pytest

from bean_import.core.advice import NO_ADVICE, Advice
from bean_import.core.classification import (
    Classification,
    ClassificationRequest,
    accept,
    unknown,
)
from bean_import.core.classifiers import FirstResolved, UnknownClassifier
from tests.helpers import make_request


class Fixed:
    """A stand-in classifier: it always answers the same way."""

    def __init__(self, result: Classification | None, name: str) -> None:
        self.result = result
        self.name = name
        self.calls = 0

    def classify(
        self,
        request: ClassificationRequest,
        advice: Advice,
    ) -> Classification:
        del advice
        self.calls += 1
        return self.result or unknown(request, f"{self.name} 放弃", self.name)


def test_without_a_model_the_direction_is_kept_and_nothing_is_guessed() -> None:
    result = UnknownClassifier().classify(make_request(), NO_ADVICE)

    assert result.status == "unknown"
    assert result.resolved is False
    assert result.account == "Expenses:Unknown"
    assert result.model_id == ""
    assert "未启用语义分类" in result.reason


def test_the_chain_stops_at_the_first_classifier_that_commits() -> None:
    first = Fixed(None, "history")
    second = Fixed(accept("Expenses:Food:Quick", "简餐", "model"), "model")
    third = Fixed(None, "never")

    result = FirstResolved(first, second, third).classify(make_request(), NO_ADVICE)

    assert result.account == "Expenses:Food:Quick"
    assert (first.calls, second.calls, third.calls) == (1, 1, 0)


def test_a_chain_that_never_commits_still_returns_the_last_honest_answer() -> None:
    result = FirstResolved(Fixed(None, "history"), UnknownClassifier()).classify(
        make_request(), NO_ADVICE
    )

    assert result.status == "unknown"
    assert result.account == "Expenses:Unknown"


def test_an_empty_chain_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FirstResolved()
