"""Bank of China debit and credit statements in their table CSV layout.

The bank delivers these rows inside PDF or email bills. This prototype reads
the same columns after that table has been saved as CSV. PDF and EML containers
are rejected with an explicit error instead of being guessed.
"""

from __future__ import annotations

from decimal import Decimal

from bean_import.config.customer import CustomerConfig, SourceInstance
from bean_import.core.models import SourceRecord
from bean_import.sources.common import (
    SourceParseError,
    blank,
    cell,
    csv_rows,
    currency_code,
    find_header,
    fingerprint,
    parse_amount,
    parse_date,
    reject_duplicate_ids,
)

DEBIT_FIELDS = {
    "记账日期",
    "记账时间",
    "币别",
    "金额",
    "交易名称",
    "渠道",
    "附言",
    "对方账户名",
}
CREDIT_FIELDS = {
    "货币",
    "交易日",
    "银行记账日",
    "卡号后四位",
    "交易描述",
    "存入",
    "支出",
}


def parse_boc_debit(
    text: str,
    source_file: str,
    config: CustomerConfig,
    instance: SourceInstance,
) -> list[SourceRecord]:
    rows = csv_rows(text)
    header_row, columns = find_header(rows, DEBIT_FIELDS)
    account = instance.account
    tail = config.tail_for_account(account)
    records: list[SourceRecord] = []
    for row_number, cells in rows:
        if row_number <= header_row or not any(cells):
            continue
        records.append(
            _debit_row(
                cells,
                columns,
                row_number,
                source_file,
                config,
                account,
                tail,
            )
        )
    reject_duplicate_ids([record.source_id for record in records], "BOC debit")
    if not records:
        raise SourceParseError("BOC debit statement contains no transaction rows")
    return records


def parse_boc_credit(
    text: str,
    source_file: str,
    config: CustomerConfig,
    instance: SourceInstance,
) -> list[SourceRecord]:
    rows = csv_rows(text)
    header_row, columns = find_header(rows, CREDIT_FIELDS)
    records: list[SourceRecord] = []
    for row_number, cells in rows:
        if row_number <= header_row or not any(cells):
            continue
        records.append(
            _credit_row(cells, columns, row_number, source_file, config, instance)
        )
    reject_duplicate_ids([record.source_id for record in records], "BOC credit")
    if not records:
        raise SourceParseError("BOC credit statement contains no transaction rows")
    return records


def _debit_row(
    cells: list[str],
    columns: dict[str, int],
    row_number: int,
    source_file: str,
    config: CustomerConfig,
    account: str,
    tail: str,
) -> SourceRecord:
    currency = currency_code(cell(cells, columns, "币别", row_number), row_number)
    _expect_currency(currency, config.currency, row_number)
    amount = parse_amount(cell(cells, columns, "金额", row_number), row_number)
    if amount == 0:
        raise SourceParseError(f"Row {row_number} has a zero amount")
    category = cell(cells, columns, "交易名称", row_number)
    narration = cell(cells, columns, "附言", row_number)
    payee = cell(cells, columns, "对方账户名", row_number)
    if blank(narration):
        narration = category
    if blank(payee):
        payee = ""
    raw_fields = {
        "记账日期": cell(cells, columns, "记账日期", row_number),
        "记账时间": cell(cells, columns, "记账时间", row_number),
        "币别": cell(cells, columns, "币别", row_number),
        "金额": cell(cells, columns, "金额", row_number),
        "交易名称": category,
        "渠道": cell(cells, columns, "渠道", row_number),
        "附言": narration,
        "对方账户名": payee,
    }
    return SourceRecord(
        source_id=fingerprint("boc_debit", raw_fields),
        row_number=row_number,
        transaction_date=parse_date(raw_fields["记账日期"], row_number),
        amount=amount,
        payee=payee,
        narration=narration,
        category=category,
        raw_fields=raw_fields,
        source_type="boc_debit",
        source_account=account,
        currency=currency,
        funding_method=raw_fields["渠道"],
        card_tail=tail,
        source_file=source_file,
        occurred_at=f"{raw_fields['记账日期']} {raw_fields['记账时间']}",
    )


def _credit_row(
    cells: list[str],
    columns: dict[str, int],
    row_number: int,
    source_file: str,
    config: CustomerConfig,
    instance: SourceInstance,
) -> SourceRecord:
    currency = currency_code(cell(cells, columns, "货币", row_number), row_number)
    _expect_currency(currency, config.currency, row_number)
    tail = cell(cells, columns, "卡号后四位", row_number)
    if len(tail) != 4 or not tail.isdigit():
        raise SourceParseError(f"Row {row_number} has an invalid card tail")
    description = cell(cells, columns, "交易描述", row_number)
    deposit = cell(cells, columns, "存入", row_number)
    expense = cell(cells, columns, "支出", row_number)
    amount = _credit_amount(deposit, expense, row_number)
    narration, payee = _split_description(description)
    account = config.find_card_account(tail) or instance.account
    raw_fields = {
        "货币": currency,
        "交易日": cell(cells, columns, "交易日", row_number),
        "银行记账日": cell(cells, columns, "银行记账日", row_number),
        "卡号后四位": tail,
        "交易描述": description,
        "存入": deposit,
        "支出": expense,
    }
    return SourceRecord(
        source_id=fingerprint("boc_credit", raw_fields),
        row_number=row_number,
        transaction_date=parse_date(raw_fields["银行记账日"], row_number),
        amount=amount,
        payee=payee,
        narration=narration,
        category="",
        raw_fields=raw_fields,
        source_type="boc_credit",
        source_account=account,
        currency=currency,
        card_tail=tail,
        source_file=source_file,
        occurred_at=raw_fields["交易日"],
    )


def _credit_amount(deposit: str, expense: str, row_number: int) -> Decimal:
    has_deposit = bool(deposit.strip())
    has_expense = bool(expense.strip())
    if has_deposit == has_expense:
        raise SourceParseError(f"Row {row_number} must have either 存入 or 支出")
    magnitude = parse_amount(deposit if has_deposit else expense, row_number)
    if magnitude == 0:
        raise SourceParseError(f"Row {row_number} has a zero amount")
    return abs(magnitude) if has_deposit else -abs(magnitude)


def _split_description(description: str) -> tuple[str, str]:
    if "-" not in description:
        return description, ""
    narration, payee = description.split("-", 1)
    return narration.strip() or description, payee.strip()


def _expect_currency(actual: str, expected: str, row_number: int) -> None:
    if actual != expected:
        raise SourceParseError(
            f"Row {row_number} currency {actual} does not match configured {expected}"
        )
