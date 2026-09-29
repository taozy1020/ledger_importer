"""Dispatch a statement file to the WeChat, Alipay, or Bank of China adapter."""

from __future__ import annotations

from pathlib import Path

from bean_import.config.customer import CustomerConfig
from bean_import.core.models import SourceRecord
from bean_import.sources.alipay import parse_alipay
from bean_import.sources.boc import parse_boc_credit, parse_boc_debit
from bean_import.sources.common import SourceParseError, csv_rows, read_text
from bean_import.sources.identity import resolve_source
from bean_import.sources.wechat import parse_wechat


def read_platform_file(path: str | Path, config: CustomerConfig) -> list[SourceRecord]:
    """Parse one supported statement into source records."""

    file_path = Path(path)
    if file_path.suffix.lower() in {".pdf", ".eml"}:
        raise SourceParseError(
            f"{file_path.name} is a PDF or email container. Save the statement table "
            "as CSV using the column layout in examples/prototype/statements."
        )
    text = read_text(file_path)
    kind = detect_kind(text)
    source = str(file_path)
    if kind is None:
        raise SourceParseError(f"Unrecognized statement format: {file_path.name}")
    instance = resolve_source(config, kind, text, file_path.name)
    if kind == "wechat":
        return parse_wechat(text, source, config, instance)
    if kind == "alipay":
        return parse_alipay(text, source, config, instance)
    if kind == "boc_debit":
        return parse_boc_debit(text, source, config, instance)
    return parse_boc_credit(text, source, config, instance)


def detect_kind(text: str) -> str | None:
    """Identify a statement without raising when the file is unrelated."""

    if "微信支付账单明细" in text:
        return "wechat"
    if "支付宝交易记录明细查询" in text or (
        "支付宝" in text and "电子客户回单" in text
    ):
        return "alipay"
    for _, cells in csv_rows(text)[:40]:
        if "记账日期" in cells and "对方账户名" in cells:
            return "boc_debit"
        if "交易日" in cells and "存入" in cells and "支出" in cells:
            return "boc_credit"
        if "交易时间" in cells and "支付方式" in cells:
            return "wechat"
        if "交易时间" in cells and ("收/付款方式" in cells or "收付款方式" in cells):
            return "alipay"
    return None
