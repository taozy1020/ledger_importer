"""Reading real statement files, including telling two accounts apart."""

from __future__ import annotations

from pathlib import Path

import pytest

from bean_import.config.customer import load_customer_config
from bean_import.sources import read_platform_file
from bean_import.sources.common import SourceParseError
from bean_import.sources.identity import match_rank
from tests.helpers import LEDGER, STATEMENTS


def test_an_alipay_export_in_gbk_is_read_and_attributed_to_its_card(
    tmp_path: Path,
) -> None:
    config = load_customer_config(LEDGER)
    path = tmp_path / "alipay.csv"
    path.write_bytes(
        (STATEMENTS / "alipay.csv").read_text(encoding="utf-8").encode("gbk")
    )

    records = read_platform_file(path, config)

    assert records[0].payee == "瑞幸咖啡"
    assert records[0].source_account == "Assets:Bank:BOC:Debit"


def test_containers_and_desktop_exports_are_refused_rather_than_half_parsed(
    tmp_path: Path,
) -> None:
    config = load_customer_config(LEDGER)
    pdf = tmp_path / "statement.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(SourceParseError, match="PDF or email"):
        read_platform_file(pdf, config)

    web = tmp_path / "web.csv"
    web.write_text("支付宝交易记录明细查询\n", encoding="utf-8")
    with pytest.raises(SourceParseError, match="mobile"):
        read_platform_file(web, config)


def test_two_wechat_accounts_are_told_apart_by_the_statement_header(
    tmp_path: Path,
) -> None:
    text = (
        (LEDGER)
        .read_text(encoding="utf-8")
        .replace(
            '[[sources]]\ntype = "wechat"\naccount = "Assets:WeChat:Balance"\n',
            '[[sources]]\ntype = "wechat"\n'
            'account = "Assets:WeChat:Balance"\nidentity = "小明"\n\n'
            '[[sources]]\ntype = "wechat"\n'
            'account = "Assets:WeChat:Work"\nidentity = "小明工作号"\n',
        )
    )
    ledger = tmp_path / "ledger.toml"
    ledger.write_text(text, encoding="utf-8")
    config = load_customer_config(ledger)
    assert len(config.sources_of("wechat")) == 2

    personal = (STATEMENTS / "wechat.csv").read_text(encoding="utf-8")
    work = tmp_path / "wechat-work.csv"
    work.write_text(
        personal.replace("微信昵称：[小明]", "微信昵称：[小明工作号]"), "utf-8"
    )

    assert read_platform_file(STATEMENTS / "wechat.csv", config)[0].source_account == (
        "Assets:WeChat:Balance"
    )
    assert read_platform_file(work, config)[0].source_account == "Assets:WeChat:Work"


def test_an_unknown_identity_fails_instead_of_landing_in_the_wrong_account(
    tmp_path: Path,
) -> None:
    text = (
        (LEDGER)
        .read_text(encoding="utf-8")
        .replace(
            '[[sources]]\ntype = "wechat"\naccount = "Assets:WeChat:Balance"\n',
            '[[sources]]\ntype = "wechat"\n'
            'account = "Assets:WeChat:Balance"\nidentity = "小明"\n\n'
            '[[sources]]\ntype = "wechat"\n'
            'account = "Assets:WeChat:Work"\nidentity = "小明工作号"\n',
        )
    )
    ledger = tmp_path / "ledger.toml"
    ledger.write_text(text, encoding="utf-8")
    config = load_customer_config(ledger)

    stranger = tmp_path / "wechat-stranger.csv"
    stranger.write_text(
        (STATEMENTS / "wechat.csv")
        .read_text(encoding="utf-8")
        .replace("微信昵称：[小明]", "微信昵称：[路人]"),
        encoding="utf-8",
    )

    with pytest.raises(SourceParseError, match="matches none of the configured"):
        read_platform_file(stranger, config)


def test_an_exact_identity_beats_a_substring_of_a_longer_one() -> None:
    assert match_rank("小明", "小明") == 3
    assert match_rank("6217000000001234", "621700******1234") == 2
    assert match_rank("小明", "小明工作号") == 1
    assert match_rank("小明", "老王") == 0
