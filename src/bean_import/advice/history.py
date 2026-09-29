"""Rank accounts from decisions this person already made.

This is the memory layer. It reads settled journal entries, scores each against
the situation at hand, and reports the accounts with the evidence behind them.
It proposes nothing on its own: the result is advice for a person, or context
for a model.

Corrections count for more than acceptances. A correction is a person
disagreeing on purpose; an acceptance may only mean the suggestion was not
worth the click. Weighting them equally is how a system convinces itself.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from bean_import.advice.similarity import DEFAULT_WEIGHTS, Weights, decay, similarity
from bean_import.core.advice import Advice, Candidate
from bean_import.core.journal import ACCEPTED, CORRECTED, JournalEntry
from bean_import.core.ports import Clock, DecisionJournal
from bean_import.core.situation import Situation

SATURATION = 1.5


@dataclass(frozen=True, slots=True)
class AdvicePolicy:
    """Everything tunable about the memory, in one place a ledger can set."""

    half_life_days: int = 180
    max_candidates: int = 3
    min_similarity: float = 0.35
    min_support: int = 1
    correction_weight: float = 1.0
    acceptance_weight: float = 0.4
    weights: Weights = field(default=DEFAULT_WEIGHTS)

    def weight_of(self, outcome: str) -> float:
        if outcome == CORRECTED:
            return self.correction_weight
        if outcome == ACCEPTED:
            return self.acceptance_weight
        return 0.0


DEFAULT_POLICY = AdvicePolicy()


@dataclass(frozen=True, slots=True)
class _Example:
    situation: Situation
    account: str
    weight: float
    on: date


class NullAdvisor:
    """No memory. Milestone 1 before the journal has anything settled."""

    def advise(self, situation: Situation, allowed: tuple[str, ...]) -> Advice:
        del situation, allowed
        return Advice()


class HistoryAdvisor:
    """Advice from settled journal entries, decayed by age."""

    def __init__(
        self,
        journal: DecisionJournal,
        clock: Clock,
        policy: AdvicePolicy = DEFAULT_POLICY,
    ) -> None:
        self._journal = journal
        self._clock = clock
        self._policy = policy
        self._examples: tuple[_Example, ...] | None = None

    def advise(self, situation: Situation, allowed: tuple[str, ...]) -> Advice:
        permitted = set(allowed)
        policy = self._policy
        today = self._clock.today()

        scores: dict[str, float] = defaultdict(float)
        support: dict[str, int] = defaultdict(int)
        latest: dict[str, date] = {}
        reasons: dict[str, tuple[str, ...]] = {}
        names: dict[str, list[str]] = defaultdict(list)

        for example in self._load():
            if example.account not in permitted:
                continue
            if example.situation.role != situation.role:
                continue
            match = similarity(situation, example.situation, policy.weights)
            if match.score < policy.min_similarity:
                continue
            age = (today - example.on).days
            score = match.score * example.weight * decay(age, policy.half_life_days)
            if score <= 0.0:
                continue
            account = example.account
            scores[account] += score
            support[account] += 1
            if account not in latest or example.on > latest[account]:
                latest[account] = example.on
                reasons[account] = match.reasons
            name = example.situation.payee or example.situation.narration
            if name and name not in names[account] and len(names[account]) < 3:
                names[account].append(name)

        eligible = {
            account: score
            for account, score in scores.items()
            if support[account] >= policy.min_support
        }
        if not eligible:
            return Advice()

        total = sum(eligible.values())
        saturation = total / (total + SATURATION)
        ranked = sorted(eligible.items(), key=lambda item: (-item[1], item[0]))
        return Advice(
            tuple(
                Candidate(
                    account=account,
                    confidence=round(score / total * saturation, 4),
                    support=support[account],
                    evidence=_evidence(
                        support[account],
                        latest[account],
                        reasons.get(account, ()),
                        names[account],
                    ),
                )
                for account, score in ranked[: policy.max_candidates]
            )
        )

    def _load(self) -> tuple[_Example, ...]:
        if self._examples is None:
            self._examples = _examples(self._journal.entries(), self._policy)
        return self._examples


def _examples(
    entries: Sequence[JournalEntry],
    policy: AdvicePolicy,
) -> tuple[_Example, ...]:
    found: list[_Example] = []
    for entry in entries:
        decision = entry.decision
        if decision is None:
            continue
        account = entry.label()
        weight = policy.weight_of(decision.outcome)
        if not account or weight <= 0.0:
            continue
        found.append(
            _Example(
                situation=entry.situation,
                account=account,
                weight=weight,
                on=entry.situation.on,
            )
        )
    return tuple(found)


def _evidence(
    support: int,
    latest: date,
    reasons: Sequence[str],
    names: Sequence[str],
) -> str:
    parts = [f"{support} 笔相似记录", f"最近 {latest.isoformat()}"]
    if reasons:
        parts.append("、".join(reasons))
    if names:
        parts.append("如 " + "、".join(names))
    return "；".join(parts)
