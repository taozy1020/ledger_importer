"""Curated payee examples and short guides shipped beside a customer's ledger."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from beancount.core.data import Directive, Transaction


@dataclass(frozen=True, slots=True)
class KnowledgeExample:
    """A payee the customer has already decided how to categorize."""

    payee: str
    account: str
    note: str = ""
    source: str = "curated"


@dataclass(frozen=True, slots=True)
class KnowledgeGuide:
    """Free-text policy included in the prompt when its keywords appear."""

    keywords: tuple[str, ...]
    text: str


def examples_from_ledger(
    existing: Sequence[Directive],
    allowed_accounts: set[str],
) -> tuple[KnowledgeExample, ...]:
    """Turn confirmed ledger postings into additional payee examples."""

    found: list[KnowledgeExample] = []
    seen: set[tuple[str, str]] = set()
    for entry in existing:
        if not isinstance(entry, Transaction) or not entry.payee:
            continue
        for posting in entry.postings:
            key = (entry.payee, posting.account)
            if posting.account not in allowed_accounts or key in seen:
                continue
            seen.add(key)
            found.append(KnowledgeExample(entry.payee, posting.account, "", "ledger"))
            break
    return tuple(found)


def select_examples(
    *,
    payee: str,
    narration: str,
    source_category: str,
    curated: Sequence[KnowledgeExample],
    ledger: Sequence[KnowledgeExample],
    limit: int,
) -> tuple[KnowledgeExample, ...]:
    """Keep the few examples that actually overlap this transaction."""

    blob = f"{payee} {narration} {source_category}"
    scored: list[tuple[int, int, KnowledgeExample]] = []
    for example in curated:
        score = _example_score(example, blob, payee)
        if score:
            scored.append((score, 1, example))
    for example in ledger:
        if example.payee and example.payee == payee:
            scored.append((10 + len(example.payee), 0, example))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected: list[KnowledgeExample] = []
    seen: set[tuple[str, str]] = set()
    for _, _, example in scored:
        key = (example.payee, example.account)
        if key in seen:
            continue
        seen.add(key)
        selected.append(example)
        if len(selected) >= limit:
            break
    return tuple(selected)


def select_guides(
    *,
    payee: str,
    narration: str,
    source_category: str,
    guides: Sequence[KnowledgeGuide],
    limit: int = 4,
) -> tuple[KnowledgeGuide, ...]:
    """Include global guides and guides whose keywords appear in the text."""

    blob = f"{payee} {narration} {source_category}"
    selected = [
        guide
        for guide in guides
        if not guide.keywords or any(keyword in blob for keyword in guide.keywords)
    ]
    return tuple(selected[:limit])


def best_example(
    *,
    payee: str,
    narration: str,
    source_category: str,
    examples: Sequence[KnowledgeExample],
    allowed_accounts: Sequence[str],
) -> KnowledgeExample | None:
    """Choose the longest curated payee contained in the transaction text."""

    blob = f"{payee} {narration} {source_category}"
    allowed = set(allowed_accounts)
    matches = [
        example
        for example in examples
        if example.payee and example.payee in blob and example.account in allowed
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda example: (len(example.payee), example.source == "curated"),
    )


def _example_score(example: KnowledgeExample, blob: str, payee: str) -> int:
    if example.payee and (example.payee in blob or example.payee == payee):
        return 10 + len(example.payee)
    if example.note and example.note in blob:
        return 1
    return 0
