"""The customer TOML: what it accepts, and what it refuses to guess."""

from __future__ import annotations

from pathlib import Path

import pytest

from bean_import.config.customer import CustomerConfigError, load_customer_config
from bean_import.core.render import ADVICE_SHORT
from tests.helpers import LEDGER, LEDGER_WITH_MODEL, STATEMENTS


def rewrite(tmp_path: Path, source: Path, old: str, new: str) -> Path:
    text = source.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "ledger.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def test_the_example_ledger_stays_on_milestone_one_with_memory_enabled() -> None:
    config = load_customer_config(LEDGER)

    assert config.semantic is None
    assert config.batch_folder == STATEMENTS
    assert config.journal.enabled is True
    assert config.journal.path == config.config_dir / "decisions.jsonl"
    assert config.advice.auto_accept_above == 0.0
    assert config.advice.correction_weight > config.advice.acceptance_weight


def test_a_ledger_without_journal_or_advice_tables_still_gets_the_defaults(
    tmp_path: Path,
) -> None:
    text = LEDGER.read_text(encoding="utf-8")
    path = tmp_path / "ledger.toml"
    path.write_text(
        text[: text.index("[journal]")] + text[text.index("[roles]") :], "utf-8"
    )

    config = load_customer_config(path)

    assert config.journal.enabled is True
    assert config.advice.half_life_days == 180
    assert config.advice.metadata == ADVICE_SHORT


def test_the_ledger_chooses_how_much_advice_it_keeps_forever(
    tmp_path: Path,
) -> None:
    path = rewrite(tmp_path, LEDGER, 'metadata = "short"', 'metadata = "full"')
    assert load_customer_config(path).advice.metadata == "full"

    path = rewrite(tmp_path, LEDGER, 'metadata = "short"', 'metadata = "verbose"')
    with pytest.raises(CustomerConfigError, match=r"\[advice\].metadata"):
        load_customer_config(path)


def test_cards_are_written_in_full_and_looked_up_by_tail() -> None:
    config = load_customer_config(LEDGER)

    assert config.cards[0].number == "6217000000001234"
    assert config.card_account("1234") == "Assets:Bank:BOC:Debit"
    assert config.find_card_account("9999") == ""


def test_two_cards_sharing_a_tail_cannot_be_resolved_so_they_are_rejected(
    tmp_path: Path,
) -> None:
    path = rewrite(
        tmp_path,
        LEDGER,
        'number = "6259000000005678"',
        'number = "6259 0000 0000 1234"',
    )

    with pytest.raises(CustomerConfigError, match="share the last four digits"):
        load_customer_config(path)


def test_two_accounts_of_one_platform_must_each_declare_an_identity(
    tmp_path: Path,
) -> None:
    path = rewrite(
        tmp_path,
        LEDGER,
        '[[sources]]\ntype = "wechat"\naccount = "Assets:WeChat:Balance"\n',
        '[[sources]]\ntype = "wechat"\naccount = "Assets:WeChat:Balance"\n\n'
        '[[sources]]\ntype = "wechat"\naccount = "Assets:WeChat:Work"\n',
    )

    with pytest.raises(CustomerConfigError, match="needs an identity"):
        load_customer_config(path)


def test_the_life_skill_must_stay_beside_the_ledger(tmp_path: Path) -> None:
    path = rewrite(
        tmp_path,
        LEDGER_WITH_MODEL,
        'skill = "skills/food.md"',
        'skill = "../food.md"',
    )

    with pytest.raises(CustomerConfigError, match="escapes"):
        load_customer_config(path)


def test_advice_settings_are_bounded_so_a_typo_cannot_silence_the_memory(
    tmp_path: Path,
) -> None:
    path = rewrite(
        tmp_path, LEDGER, "auto_accept_above = 0.0", "auto_accept_above = 1.5"
    )
    with pytest.raises(CustomerConfigError, match="auto_accept_above"):
        load_customer_config(path)

    path = rewrite(tmp_path, LEDGER, "half_life_days = 180", "half_life = 30")
    with pytest.raises(CustomerConfigError, match="unsupported keys"):
        load_customer_config(path)


def test_the_journal_can_be_moved_or_turned_off(tmp_path: Path) -> None:
    text = LEDGER.read_text(encoding="utf-8")
    path = tmp_path / "ledger.toml"
    path.write_text(
        text.replace("enabled = true", "enabled = false").replace(
            'path = "decisions.jsonl"', 'path = "history/decisions.jsonl"'
        ),
        encoding="utf-8",
    )

    config = load_customer_config(path)

    assert config.journal.enabled is False
    assert config.journal.path.name == "decisions.jsonl"
    assert config.journal.path.parent.name == "history"
