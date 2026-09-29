"""What the reviewer is shown when an account is left unknown.

An unknown account is not a dead end: it is the moment a person decides. Advice
carries the accounts worth considering, how strongly the past supports each one,
and the evidence in plain words, so the decision can be made in Fava without
opening the original statement.

Advice never changes a posting. Only a classifier may do that, and only if the
ledger configured it to.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_EVIDENCE = 160


@dataclass(frozen=True, slots=True)
class Candidate:
    """One account the past supports, with the reason it came up."""

    account: str
    confidence: float
    support: int
    evidence: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")
        if self.support < 0:
            raise ValueError(f"support must not be negative: {self.support}")

    def render(self) -> str:
        return f"{self.account} {self.confidence:.2f}"


@dataclass(frozen=True, slots=True)
class Advice:
    """The ranked candidates for one unresolved account, best first."""

    candidates: tuple[Candidate, ...] = ()

    @property
    def top(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def confidence(self) -> float:
        top = self.top
        return top.confidence if top is not None else 0.0

    def render(self) -> str:
        return " | ".join(candidate.render() for candidate in self.candidates)

    def evidence(self) -> str:
        top = self.top
        return top.evidence[:MAX_EVIDENCE] if top is not None else ""

    def limited_to(self, accounts: tuple[str, ...]) -> Advice:
        """Drop candidates the ledger no longer allows."""

        permitted = set(accounts)
        return Advice(
            tuple(
                candidate
                for candidate in self.candidates
                if candidate.account in permitted
            )
        )


NO_ADVICE = Advice()
