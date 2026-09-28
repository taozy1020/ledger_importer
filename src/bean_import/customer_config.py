"""Per-customer TOML: accounts, cards, suspense, and the classification corpus."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from bean_import.knowledge import KnowledgeExample, KnowledgeGuide


class CustomerConfigError(ValueError):
    """The customer ledger file is missing a required classification setting."""


@dataclass(frozen=True, slots=True)
class CustomerConfig:
    """Everything that changes from one Beancount user to another."""

    currency: str
    date_window_days: int
    accounts: dict[str, str]
    cards: dict[str, str]
    expense_accounts: tuple[str, ...]
    income_accounts: tuple[str, ...]
    suspense_expense: str
    suspense_income: str
    endpoint: str
    model: str
    api_key_env: str
    max_examples: int
    examples: tuple[KnowledgeExample, ...]
    guides: tuple[KnowledgeGuide, ...]

    def require_account(self, key: str) -> str:
        account = self.accounts.get(key, "")
        if not account:
            raise CustomerConfigError(f"ledger config is missing accounts.{key}")
        return account

    def optional_account(self, key: str) -> str:
        return self.accounts.get(key, "")

    def card_account(self, tail: str) -> str:
        account = self.cards.get(tail, "")
        if not account:
            raise CustomerConfigError(f"No account configured for card tail {tail}")
        return account

    def tail_for_account(self, account: str) -> str:
        tails = [tail for tail, mapped in self.cards.items() if mapped == account]
        if len(tails) == 1:
            return tails[0]
        return ""


def load_customer_config(path: str | Path) -> CustomerConfig:
    """Load one customer's accounts and knowledge base from TOML."""

    with Path(path).open("rb") as config_file:
        raw = tomllib.load(config_file)

    currency = _string(raw.get("currency"), "currency")
    window = raw.get("date_window_days", 2)
    if isinstance(window, bool) or not isinstance(window, int) or window < 0:
        raise CustomerConfigError("date_window_days must be a non-negative integer")

    accounts = _account_table(_table(raw, "accounts"), "accounts")
    cards = _account_table(_table(raw, "cards"), "cards")
    for key in ("wechat", "alipay", "boc_debit", "boc_credit"):
        if key not in accounts:
            raise CustomerConfigError(f"accounts.{key} is required")

    classifier = _table(raw, "classifier")
    suspense_expense = _string(
        classifier.get("suspense_expense"), "[classifier].suspense_expense"
    )
    suspense_income = _string(
        classifier.get("suspense_income"), "[classifier].suspense_income"
    )
    endpoint = classifier.get("endpoint", "")
    model = classifier.get("model", "")
    api_key_env = classifier.get("api_key_env", "BEAN_IMPORT_LLM_API_KEY")
    max_examples = classifier.get("max_examples", 8)
    if not isinstance(endpoint, str):
        raise CustomerConfigError("[classifier].endpoint must be a string")
    if not isinstance(model, str):
        raise CustomerConfigError("[classifier].model must be a string")
    if not isinstance(api_key_env, str) or not api_key_env:
        raise CustomerConfigError("[classifier].api_key_env must be a non-empty string")
    if endpoint and not model:
        raise CustomerConfigError("[classifier].model is required when endpoint is set")
    if (
        isinstance(max_examples, bool)
        or not isinstance(max_examples, int)
        or not 1 <= max_examples <= 20
    ):
        raise CustomerConfigError(
            "[classifier].max_examples must be an integer from 1 to 20"
        )

    roles = _table(raw, "roles")
    expense_accounts = _account_list(roles.get("expense"), "roles.expense")
    income_accounts = _account_list(roles.get("income"), "roles.income")
    if suspense_expense not in expense_accounts:
        expense_accounts = (*expense_accounts, suspense_expense)
    if suspense_income not in income_accounts:
        income_accounts = (*income_accounts, suspense_income)
    allowed = set(expense_accounts) | set(income_accounts)

    knowledge = raw.get("knowledge", {})
    if knowledge is None:
        knowledge = {}
    if not isinstance(knowledge, dict):
        raise CustomerConfigError("[knowledge] must be a table")
    knowledge_table = cast(dict[str, Any], knowledge)
    examples = _examples(knowledge_table.get("examples", []), allowed)
    guides = _guides(knowledge_table.get("guides", []))

    return CustomerConfig(
        currency=currency,
        date_window_days=window,
        accounts=accounts,
        cards=cards,
        expense_accounts=expense_accounts,
        income_accounts=income_accounts,
        suspense_expense=suspense_expense,
        suspense_income=suspense_income,
        endpoint=endpoint,
        model=model,
        api_key_env=api_key_env,
        max_examples=max_examples,
        examples=examples,
        guides=guides,
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


def _account_table(table: dict[str, Any], label: str) -> dict[str, str]:
    accounts: dict[str, str] = {}
    for key, value in table.items():
        accounts[str(key)] = _account(value, f"{label}.{key}")
    return accounts


def _account_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CustomerConfigError(f"{label} must be a non-empty list of accounts")
    return tuple(_account(item, label) for item in cast(list[object], value))


def _examples(value: object, allowed: set[str]) -> tuple[KnowledgeExample, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CustomerConfigError("knowledge.examples must be a list")
    examples: list[KnowledgeExample] = []
    for index, item in enumerate(cast(list[object], value), start=1):
        if not isinstance(item, dict):
            raise CustomerConfigError(f"knowledge.examples[{index}] must be a table")
        row = cast(dict[str, Any], item)
        payee = _string(row.get("payee"), f"knowledge.examples[{index}].payee")
        account = _account(row.get("account"), f"knowledge.examples[{index}].account")
        if account not in allowed:
            raise CustomerConfigError(
                f"knowledge.examples[{index}] account {account} is not in [roles]"
            )
        note = row.get("note", "")
        if not isinstance(note, str):
            raise CustomerConfigError(
                f"knowledge.examples[{index}].note must be a string"
            )
        examples.append(KnowledgeExample(payee, account, note))
    return tuple(examples)


def _guides(value: object) -> tuple[KnowledgeGuide, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CustomerConfigError("knowledge.guides must be a list")
    guides: list[KnowledgeGuide] = []
    for index, item in enumerate(cast(list[object], value), start=1):
        if not isinstance(item, dict):
            raise CustomerConfigError(f"knowledge.guides[{index}] must be a table")
        row = cast(dict[str, Any], item)
        text = _string(row.get("text"), f"knowledge.guides[{index}].text")
        raw_keywords = row.get("keywords", [])
        if not isinstance(raw_keywords, list):
            raise CustomerConfigError(
                f"knowledge.guides[{index}].keywords must be a list"
            )
        keywords: list[str] = []
        for keyword in cast(list[object], raw_keywords):
            keywords.append(_string(keyword, f"knowledge.guides[{index}].keywords"))
        guides.append(KnowledgeGuide(tuple(keywords), text))
    return tuple(guides)
