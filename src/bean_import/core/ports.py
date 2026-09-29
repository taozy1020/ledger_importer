"""Every seam in the system, in one file.

A module in `core` may depend on this file; nothing in `core` may depend on an
adapter. Each protocol below has at least two implementations, one of which is
trivial enough to use as a stand-in during a test:

    SemanticClassifier  UnknownClassifier | HistoryClassifier | the model
    AccountAdvisor      NullAdvisor       | HistoryAdvisor
    DecisionJournal     NullJournal       | InMemoryJournal | JsonlJournal
    LedgerOutcomes      outcomes in memory | a Beancount file
    Clock               FixedClock        | SystemClock
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol

from bean_import.core.advice import Advice
from bean_import.core.classification import Classification, ClassificationRequest
from bean_import.core.journal import Decision, JournalEntry, LedgerOutcome
from bean_import.core.situation import Situation


class Clock(Protocol):
    def today(self) -> date:
        """The day an import or a harvest is happening."""

        ...


class AccountAdvisor(Protocol):
    def advise(self, situation: Situation, allowed: tuple[str, ...]) -> Advice:
        """Rank allowed accounts for a situation. Never decides anything."""

        ...


class SemanticClassifier(Protocol):
    def classify(
        self,
        request: ClassificationRequest,
        advice: Advice,
    ) -> Classification:
        """Choose one allowed account, or the unknown account when unsafe."""

        ...


class DecisionJournal(Protocol):
    def record(self, entry: JournalEntry) -> None:
        """Store a proposal, replacing an earlier one for the same `event_id`.

        A decision already harvested for that `event_id` must survive.
        """

        ...

    def entries(self) -> tuple[JournalEntry, ...]:
        """Every proposal known, at most one per `event_id`, oldest first."""

        ...

    def settle(self, decisions: Mapping[str, Decision]) -> int:
        """Attach harvested decisions by `event_id`; return how many landed."""

        ...


class LedgerOutcomes(Protocol):
    def outcomes(self) -> Mapping[str, LedgerOutcome]:
        """What the ledger currently holds, keyed by `event_id`."""

        ...
