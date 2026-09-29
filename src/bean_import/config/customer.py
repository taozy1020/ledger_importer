"""Per-customer TOML: statement sources, cards, unknown accounts, optional model.

`[[sources]]` is one funding account per platform account, not per platform. A
person with two WeChat accounts writes two entries and tells them apart by the
identity printed in the statement header.

`[[cards]]` holds full card numbers. Statements only ever show the last four
digits, so lookups match on the tail; two configured cards sharing a tail are
rejected instead of guessed.

`[semantic]` is the whole milestone 2 surface. A ledger without that table is a
complete milestone 1 configuration and never reaches a model.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from bean_import.core.render import ADVICE_DETAIL, ADVICE_SHORT

SOURCE_TYPES = ("wechat", "alipay", "boc_debit", "boc_credit")
SUB_ACCOUNTS = {
    "wechat": ("lingqiantong",),
    "alipay": ("yuebao", "huabei"),
    "boc_debit": (),
    "boc_credit": (),
}
MASK_CHARACTERS = "*xX# "


class CustomerConfigError(ValueError):
    """The customer ledger file is missing a required classification setting."""


@dataclass(frozen=True, slots=True)
class SourceInstance:
    """One platform account: a statement belongs to exactly one of these."""

    source_type: str
    account: str
    identity: str
    sub_accounts: dict[str, str]

    @property
    def label(self) -> str:
        if self.identity:
            return f"{self.source_type}({self.identity})"
        return self.source_type

    def sub_account(self, name: str) -> str:
        return self.sub_accounts.get(name, "")


@dataclass(frozen=True, slots=True)
class Card:
    """A bank card written in full, matched by its last four digits."""

    number: str
    account: str

    @property
    def tail(self) -> str:
        return self.number[-4:]


@dataclass(frozen=True, slots=True)
class JournalConfig:
    """Where proposals are recorded so decisions can be harvested later."""

    path: Path
    enabled: bool


@dataclass(frozen=True, slots=True)
class AdviceConfig:
    """How much the past is allowed to say about the present.

    `auto_accept_above` is zero by default: history informs the reviewer and
    never fills an account in on its own until the ledger asks for it.

    `metadata` decides how much of the advice the ledger keeps forever. Fava
    writes the entry exactly as the reviewer saw it, so `full` leaves the
    evidence sentence in the ledger permanently; `short` keeps one line of
    candidates; `none` keeps nothing.
    """

    half_life_days: int = 180
    max_candidates: int = 3
    min_similarity: float = 0.35
    min_support: int = 1
    correction_weight: float = 1.0
    acceptance_weight: float = 0.4
    auto_accept_above: float = 0.0
    metadata: str = ADVICE_SHORT


@dataclass(frozen=True, slots=True)
class SemanticConfig:
    """Milestone 2 settings; absent until the customer runs a model."""

    endpoint: str
    model: str
    api_key_env: str
    max_memories: int
    skill_text: str


@dataclass(frozen=True, slots=True)
class CustomerConfig:
    """Everything that changes from one Beancount user to another."""

    currency: str
    date_window_days: int
    sources: tuple[SourceInstance, ...]
    cards: tuple[Card, ...]
    expense_accounts: tuple[str, ...]
    income_accounts: tuple[str, ...]
    unknown_expense: str
    unknown_income: str
    config_dir: Path
    batch_folder: Path
    journal: JournalConfig
    advice: AdviceConfig
    semantic: SemanticConfig | None

    def sources_of(self, source_type: str) -> tuple[SourceInstance, ...]:
        return tuple(
            source for source in self.sources if source.source_type == source_type
        )

    def find_card_account(self, tail: str) -> str:
        for card in self.cards:
            if card.tail == tail:
                return card.account
        return ""

    def card_account(self, tail: str) -> str:
        account = self.find_card_account(tail)
        if not account:
            raise CustomerConfigError(f"No card configured with tail {tail}")
        return account

    def tail_for_account(self, account: str) -> str:
        tails = [card.tail for card in self.cards if card.account == account]
        if len(tails) == 1:
            return tails[0]
        return ""


def load_customer_config(path: str | Path) -> CustomerConfig:
    """Load one customer's accounts, cards, and optional model settings."""

    config_path = Path(path)
    with config_path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    root = config_path.parent

    currency = _string(raw.get("currency"), "currency")
    window = raw.get("date_window_days", 2)
    if isinstance(window, bool) or not isinstance(window, int) or window < 0:
        raise CustomerConfigError("date_window_days must be a non-negative integer")

    sources = _sources(raw.get("sources"))
    cards = _cards(raw.get("cards"))

    table = _table(raw, "unknown")
    unknown_expense = _account(table.get("expense"), "[unknown].expense")
    unknown_income = _account(table.get("income"), "[unknown].income")

    roles = _table(raw, "roles")
    expense_accounts = _account_list(roles.get("expense"), "roles.expense")
    income_accounts = _account_list(roles.get("income"), "roles.income")
    if unknown_expense not in expense_accounts:
        expense_accounts = (*expense_accounts, unknown_expense)
    if unknown_income not in income_accounts:
        income_accounts = (*income_accounts, unknown_income)

    return CustomerConfig(
        currency=currency,
        date_window_days=window,
        sources=sources,
        cards=cards,
        expense_accounts=expense_accounts,
        income_accounts=income_accounts,
        unknown_expense=unknown_expense,
        unknown_income=unknown_income,
        config_dir=root,
        batch_folder=_batch_folder(raw.get("batch"), root),
        journal=_journal(raw.get("journal"), root),
        advice=_advice(raw.get("advice")),
        semantic=_semantic(raw.get("semantic"), root),
    )


def _sources(value: object) -> tuple[SourceInstance, ...]:
    if not isinstance(value, list) or not value:
        raise CustomerConfigError("At least one [[sources]] entry is required")
    sources = tuple(
        _source(item, index)
        for index, item in enumerate(cast(list[object], value), start=1)
    )
    for source_type in SOURCE_TYPES:
        instances = [item for item in sources if item.source_type == source_type]
        if len(instances) < 2:
            continue
        identities = [item.identity for item in instances]
        if not all(identities):
            raise CustomerConfigError(
                f"Every [[sources]] entry of type {source_type} needs an identity "
                "when the ledger has more than one"
            )
        if len(set(identities)) != len(identities):
            raise CustomerConfigError(
                f"Two [[sources]] entries of type {source_type} share an identity"
            )
    return sources


def _source(value: object, index: int) -> SourceInstance:
    if not isinstance(value, dict):
        raise CustomerConfigError(f"[[sources]] entry {index} must be a table")
    table = cast(dict[str, Any], value)
    source_type = _string(table.get("type"), f"[[sources]] entry {index} type")
    if source_type not in SOURCE_TYPES:
        supported = ", ".join(SOURCE_TYPES)
        raise CustomerConfigError(
            f"[[sources]] type {source_type!r} is not one of: {supported}"
        )
    account = _account(table.get("account"), f"[[sources]] entry {index} account")
    identity = table.get("identity", "")
    if not isinstance(identity, str):
        raise CustomerConfigError(
            f"[[sources]] entry {index} identity must be a string"
        )
    allowed = SUB_ACCOUNTS[source_type]
    unknown = sorted(set(table) - {"type", "account", "identity"} - set(allowed))
    if unknown:
        supported = ", ".join(allowed) or "none"
        raise CustomerConfigError(
            f"[[sources]] entry {index} has unsupported keys: {', '.join(unknown)}. "
            f"{source_type} supports: {supported}"
        )
    sub_accounts = {
        name: _account(table[name], f"[[sources]] entry {index} {name}")
        for name in allowed
        if name in table
    }
    return SourceInstance(
        source_type=source_type,
        account=account,
        identity=identity.strip(),
        sub_accounts=sub_accounts,
    )


def _cards(value: object) -> tuple[Card, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CustomerConfigError("[[cards]] must be a list of tables")
    cards: list[Card] = []
    for index, item in enumerate(cast(list[object], value), start=1):
        if not isinstance(item, dict):
            raise CustomerConfigError(f"[[cards]] entry {index} must be a table")
        table = cast(dict[str, Any], item)
        number = _card_number(table.get("number"), index)
        account = _account(table.get("account"), f"[[cards]] entry {index} account")
        cards.append(Card(number=number, account=account))
    tails = [card.tail for card in cards]
    duplicates = sorted({tail for tail in tails if tails.count(tail) > 1})
    if duplicates:
        raise CustomerConfigError(
            "Two configured cards share the last four digits: "
            f"{', '.join(duplicates)}. Statements only show the tail, so this "
            "cannot be resolved."
        )
    return tuple(cards)


def _card_number(value: object, index: int) -> str:
    number = _string(value, f"[[cards]] entry {index} number")
    cleaned = "".join(
        character
        for character in number
        if character not in MASK_CHARACTERS and character != "-"
    )
    if len(cleaned) < 8 or not cleaned[-4:].isdigit():
        raise CustomerConfigError(
            f"[[cards]] entry {index} number must be the full card number; "
            "digits may be masked except the last four"
        )
    return cleaned


def _batch_folder(value: object, root: Path) -> Path:
    if value is None:
        return root
    if not isinstance(value, dict):
        raise CustomerConfigError("[batch] must be a table")
    table = cast(dict[str, Any], value)
    folder = table.get("folder", "")
    if folder == "":
        return root
    if not isinstance(folder, str):
        raise CustomerConfigError("[batch].folder must be a string")
    return (root / folder).resolve()


def _journal(value: object, root: Path) -> JournalConfig:
    path = root / "decisions.jsonl"
    if value is None:
        return JournalConfig(path=path, enabled=True)
    if not isinstance(value, dict):
        raise CustomerConfigError("[journal] must be a table")
    table = cast(dict[str, Any], value)
    enabled = table.get("enabled", True)
    if not isinstance(enabled, bool):
        raise CustomerConfigError("[journal].enabled must be true or false")
    raw_path = table.get("path", "")
    if raw_path != "":
        if not isinstance(raw_path, str):
            raise CustomerConfigError("[journal].path must be a string")
        path = (root / raw_path).resolve()
    return JournalConfig(path=path, enabled=enabled)


def _advice(value: object) -> AdviceConfig:
    if value is None:
        return AdviceConfig()
    if not isinstance(value, dict):
        raise CustomerConfigError("[advice] must be a table")
    table = cast(dict[str, Any], value)
    defaults = AdviceConfig()
    unsupported = sorted(set(table) - _ADVICE_KEYS)
    if unsupported:
        raise CustomerConfigError(
            f"[advice] has unsupported keys: {', '.join(unsupported)}"
        )
    return AdviceConfig(
        half_life_days=_bounded_int(
            table.get("half_life_days", defaults.half_life_days),
            "[advice].half_life_days",
            1,
            36500,
        ),
        max_candidates=_bounded_int(
            table.get("max_candidates", defaults.max_candidates),
            "[advice].max_candidates",
            1,
            10,
        ),
        min_similarity=_fraction(
            table.get("min_similarity", defaults.min_similarity),
            "[advice].min_similarity",
        ),
        min_support=_bounded_int(
            table.get("min_support", defaults.min_support),
            "[advice].min_support",
            1,
            100,
        ),
        correction_weight=_fraction(
            table.get("correction_weight", defaults.correction_weight),
            "[advice].correction_weight",
        ),
        acceptance_weight=_fraction(
            table.get("acceptance_weight", defaults.acceptance_weight),
            "[advice].acceptance_weight",
        ),
        auto_accept_above=_fraction(
            table.get("auto_accept_above", defaults.auto_accept_above),
            "[advice].auto_accept_above",
        ),
        metadata=_advice_detail(table.get("metadata", defaults.metadata)),
    )


def _advice_detail(value: object) -> str:
    if value not in ADVICE_DETAIL:
        allowed = ", ".join(ADVICE_DETAIL)
        raise CustomerConfigError(f"[advice].metadata must be one of: {allowed}")
    return cast(str, value)


_ADVICE_KEYS = {
    "half_life_days",
    "max_candidates",
    "min_similarity",
    "min_support",
    "correction_weight",
    "acceptance_weight",
    "auto_accept_above",
    "metadata",
}


def _bounded_int(value: object, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CustomerConfigError(f"{label} must be an integer")
    if not low <= value <= high:
        raise CustomerConfigError(f"{label} must be between {low} and {high}")
    return value


def _fraction(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CustomerConfigError(f"{label} must be a number between 0 and 1")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise CustomerConfigError(f"{label} must be between 0 and 1")
    return number


def _semantic(value: object, root: Path) -> SemanticConfig | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CustomerConfigError("[semantic] must be a table")
    table = cast(dict[str, Any], value)
    endpoint = _string(table.get("endpoint"), "[semantic].endpoint")
    model = _string(table.get("model"), "[semantic].model")
    api_key_env = table.get("api_key_env", "BEAN_IMPORT_LLM_API_KEY")
    max_memories = table.get("max_memories", 8)
    if not isinstance(api_key_env, str) or not api_key_env:
        raise CustomerConfigError("[semantic].api_key_env must be a non-empty string")
    if (
        isinstance(max_memories, bool)
        or not isinstance(max_memories, int)
        or not 1 <= max_memories <= 20
    ):
        raise CustomerConfigError(
            "[semantic].max_memories must be an integer from 1 to 20"
        )
    return SemanticConfig(
        endpoint=endpoint,
        model=model,
        api_key_env=api_key_env,
        max_memories=max_memories,
        skill_text=_skill_text(table.get("skill", ""), root),
    )


def _table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise CustomerConfigError(f"[{key}] is required")
    return cast(dict[str, Any], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CustomerConfigError(f"{label} must be a non-empty string")
    return value


def _account(value: object, label: str) -> str:
    account = _string(value, label)
    if ":" not in account:
        raise CustomerConfigError(f"{label} must be a Beancount account")
    return account


def _account_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CustomerConfigError(f"{label} must be a non-empty list of accounts")
    return tuple(_account(item, label) for item in cast(list[object], value))


def _skill_text(skill: object, root: Path) -> str:
    if skill == "":
        return ""
    if not isinstance(skill, str) or "\\" in skill:
        raise CustomerConfigError("[semantic].skill must be a relative markdown path")
    path = (root / skill).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise CustomerConfigError(
            "[semantic].skill escapes the ledger directory"
        ) from error
    if path.suffix.casefold() != ".md" or not path.is_file():
        raise CustomerConfigError(f"Life-context skill does not exist: {skill}")
    return path.read_text(encoding="utf-8")
