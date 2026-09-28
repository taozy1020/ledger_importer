"""Alipay mobile customer-receipt CSV."""

from __future__ import annotations

from decimal import Decimal

from bean_import.customer_config import CustomerConfig
from bean_import.models import SourceRecord
from bean_import.sources.common import (
    SourceParseError,
    card_tail,
    cell,
    csv_rows,
    find_amount_column,
    fingerprint,
    parse_amount,
    parse_date,
    reject_duplicate_ids,
)

HEADER_FIELDS = (
    "交易时间",
    "交易分类",
    "交易对方",
    "商品说明",
    "收/支",
    "交易状态",
    "交易订单号",
)


def parse_alipay(
    text: str,
    source_file: str,
    config: CustomerConfig,
) -> list[SourceRecord]:
    if "支付宝交易记录明细查询" in text:
        raise SourceParseError(
            "Alipay web export has no payment account; use the mobile CSV"
        )
    rows = csv_rows(text)
    header_row, columns = _header(rows)
    records: list[SourceRecord] = []
    for row_number, cells in rows:
        if row_number <= header_row or not any(cells):
            continue
        if cells[0].startswith("------"):
            break
        records.append(_record(cells, columns, row_number, source_file, config))
    reject_duplicate_ids([record.source_id for record in records], "Alipay")
    if not records:
        raise SourceParseError("Alipay statement contains no transaction rows")
    return records


def _header(rows: list[tuple[int, list[str]]]) -> tuple[int, dict[str, int]]:
    for row_number, cells in rows:
        if "交易时间" not in cells or "收/支" not in cells:
            continue
        if any(name not in cells for name in HEADER_FIELDS):
            continue
        method_name = next(
            (name for name in ("收/付款方式", "收付款方式") if name in cells),
            "",
        )
        amount_index = find_amount_column(cells)
        if not method_name or amount_index is None:
            continue
        columns = {name: cells.index(name) for name in HEADER_FIELDS}
        columns["收/付款方式"] = cells.index(method_name)
        columns["金额"] = amount_index
        return row_number, columns
    raise SourceParseError("Alipay statement has no transaction header")


def _record(
    cells: list[str],
    columns: dict[str, int],
    row_number: int,
    source_file: str,
    config: CustomerConfig,
) -> SourceRecord:
    category = cell(cells, columns, "交易分类", row_number)
    payee = cell(cells, columns, "交易对方", row_number)
    narration = cell(cells, columns, "商品说明", row_number)
    direction = cell(cells, columns, "收/支", row_number)
    method = cell(cells, columns, "收/付款方式", row_number)
    status = cell(cells, columns, "交易状态", row_number)
    serial = cell(cells, columns, "交易订单号", row_number)
    amount = _signed_amount(
        direction,
        narration,
        status,
        method,
        parse_amount(cell(cells, columns, "金额", row_number), row_number),
        row_number,
    )
    source_account, tail, counter_account = _accounts(
        method, narration, config, row_number
    )
    raw_fields = {
        "交易时间": cell(cells, columns, "交易时间", row_number),
        "交易分类": category,
        "交易对方": payee,
        "商品说明": narration,
        "收/支": direction,
        "金额": cell(cells, columns, "金额", row_number),
        "收/付款方式": method,
        "交易状态": status,
        "交易订单号": serial,
    }
    source_id = f"alipay:{serial}" if serial else fingerprint("alipay", raw_fields)
    return SourceRecord(
        source_id=source_id,
        row_number=row_number,
        transaction_date=parse_date(raw_fields["交易时间"], row_number),
        amount=amount,
        payee=payee,
        narration=narration,
        category=category,
        raw_fields=raw_fields,
        source_type="alipay",
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
    narration: str,
    status: str,
    method: str,
    amount: Decimal,
    row_number: int,
) -> Decimal:
    if direction == "支出":
        expense = True
    elif direction == "收入":
        expense = False
    elif direction in {"其他", "不计收支"}:
        expense = _neutral_direction(narration, status, method, row_number)
    else:
        raise SourceParseError(
            f"Row {row_number} has an unknown Alipay direction {direction!r}"
        )
    return -abs(amount) if expense else abs(amount)


def _neutral_direction(
    narration: str,
    status: str,
    method: str,
    row_number: int,
) -> bool:
    if "退款" in narration or "退款" in status:
        return False
    if method == "余额宝" and "收益" in narration:
        return False
    if narration == "余额宝-转出到余额":
        return False
    if narration == "余额宝-单次转入":
        return True
    raise SourceParseError(f"Row {row_number} has an unsupported 不计收支 transaction")


def _accounts(
    method: str,
    narration: str,
    config: CustomerConfig,
    row_number: int,
) -> tuple[str, str, str]:
    balance = config.require_account("alipay")
    yuebao = config.optional_account("alipay_yuebao")
    if narration in {"余额宝-转出到余额", "余额宝-单次转入"}:
        if not yuebao:
            raise SourceParseError(
                "accounts.alipay_yuebao is required for 余额宝 transfers"
            )
        return balance, "", yuebao
    if method in {"余额", ""}:
        return balance, "", ""
    if method == "余额宝":
        if not yuebao:
            raise SourceParseError("accounts.alipay_yuebao is required for 余额宝 rows")
        return yuebao, "", ""
    if "花呗" in method:
        huabei = config.optional_account("alipay_huabei")
        if not huabei:
            raise SourceParseError("accounts.alipay_huabei is required for 花呗 rows")
        return huabei, "", ""
    tail = card_tail(method)
    if tail:
        return config.card_account(tail), tail, ""
    raise SourceParseError(
        f"Row {row_number} has an unsupported Alipay method {method!r}"
    )
