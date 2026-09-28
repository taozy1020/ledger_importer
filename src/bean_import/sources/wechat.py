"""WeChat personal reconciliation CSV."""

from __future__ import annotations

from decimal import Decimal

from bean_import.customer_config import CustomerConfig
from bean_import.models import SourceRecord
from bean_import.sources.common import (
    SourceParseError,
    blank,
    card_tail,
    cell,
    csv_rows,
    find_amount_column,
    fingerprint,
    parse_amount,
    parse_date,
    reject_duplicate_ids,
)

CANCELLED_STATUSES = {"提现失败，已退回零钱", "对方已退还"}
HEADER_FIELDS = (
    "交易时间",
    "交易类型",
    "交易对方",
    "商品",
    "收/支",
    "支付方式",
    "当前状态",
    "交易单号",
)


def parse_wechat(
    text: str,
    source_file: str,
    config: CustomerConfig,
) -> list[SourceRecord]:
    rows = csv_rows(text)
    header_row, columns = _header(rows)
    records: list[SourceRecord] = []
    for row_number, cells in rows:
        if row_number <= header_row or not any(cells):
            continue
        status = cell(cells, columns, "当前状态", row_number)
        if status in CANCELLED_STATUSES:
            continue
        records.append(_record(cells, columns, row_number, source_file, config))
    reject_duplicate_ids([record.source_id for record in records], "WeChat")
    if not records:
        raise SourceParseError("WeChat statement contains no transaction rows")
    return records


def _header(rows: list[tuple[int, list[str]]]) -> tuple[int, dict[str, int]]:
    for row_number, cells in rows:
        if "交易时间" not in cells or "交易类型" not in cells:
            continue
        if any(name not in cells for name in HEADER_FIELDS):
            continue
        amount_index = find_amount_column(cells)
        if amount_index is None:
            continue
        columns = {name: cells.index(name) for name in HEADER_FIELDS}
        columns["金额"] = amount_index
        return row_number, columns
    raise SourceParseError("WeChat statement has no transaction header")


def _record(
    cells: list[str],
    columns: dict[str, int],
    row_number: int,
    source_file: str,
    config: CustomerConfig,
) -> SourceRecord:
    type_name = cell(cells, columns, "交易类型", row_number)
    method = cell(cells, columns, "支付方式", row_number)
    direction = cell(cells, columns, "收/支", row_number)
    status = cell(cells, columns, "当前状态", row_number)
    payee = cell(cells, columns, "交易对方", row_number)
    narration = cell(cells, columns, "商品", row_number)
    serial = cell(cells, columns, "交易单号", row_number)
    amount = _signed_amount(
        direction,
        type_name,
        parse_amount(cell(cells, columns, "金额", row_number), row_number),
        row_number,
    )
    source_account, tail, counter_account = _accounts(
        type_name, method, config, row_number
    )
    if blank(payee):
        payee = ""
    if blank(narration):
        narration = type_name
    raw_fields = {
        "交易时间": cell(cells, columns, "交易时间", row_number),
        "交易类型": type_name,
        "交易对方": payee,
        "商品": narration,
        "收/支": direction,
        "金额": cell(cells, columns, "金额", row_number),
        "支付方式": method,
        "当前状态": status,
        "交易单号": serial,
    }
    source_id = f"wechat:{serial}" if serial else fingerprint("wechat", raw_fields)
    return SourceRecord(
        source_id=source_id,
        row_number=row_number,
        transaction_date=parse_date(raw_fields["交易时间"], row_number),
        amount=amount,
        payee=payee,
        narration=narration,
        category=type_name,
        raw_fields=raw_fields,
        source_type="wechat",
        source_account=source_account,
        currency=config.currency,
        funding_method=method,
        status=status,
        card_tail=tail,
        counter_account=counter_account,
        source_file=source_file,
    )


def _signed_amount(
    direction: str,
    type_name: str,
    amount: Decimal,
    row_number: int,
) -> Decimal:
    if direction == "/" and type_name == "信用卡还款":
        direction = "支出"
    elif direction == "/" and "零钱" in type_name:
        direction = "收入"
    if type_name == "零钱提现":
        direction = "支出"
    if direction == "支出":
        return -abs(amount)
    if direction == "收入":
        return abs(amount)
    raise SourceParseError(
        f"Row {row_number} has an unknown WeChat direction {direction!r}"
    )


def _accounts(
    type_name: str,
    method: str,
    config: CustomerConfig,
    row_number: int,
) -> tuple[str, str, str]:
    if "提现" in type_name or "充值" in type_name:
        tail = card_tail(method)
        if not tail:
            raise SourceParseError(f"Row {row_number} {type_name} has no card tail")
        return config.require_account("wechat"), "", config.card_account(tail)
    if method in {"零钱", "/", ""}:
        return config.require_account("wechat"), "", ""
    if "零钱通" in method:
        account = config.optional_account("wechat_lingqiantong")
        if not account:
            raise SourceParseError(
                "accounts.wechat_lingqiantong is required for 零钱通 rows"
            )
        return account, "", ""
    tail = card_tail(method)
    if tail:
        return config.card_account(tail), tail, ""
    raise SourceParseError(
        f"Row {row_number} has an unsupported WeChat method {method!r}"
    )
