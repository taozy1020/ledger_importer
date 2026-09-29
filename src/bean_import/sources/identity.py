"""Decide which configured platform account a statement file belongs to.

Every export prints who it belongs to in its header block:

- WeChat writes ``微信昵称：[nickname]``
- Alipay writes ``姓名：`` and ``支付宝账户：`` in its 导出信息 block
- Bank of China writes ``客户姓名：`` and the full card number
- Bank of China credit statements only carry the card tail per row

Matching is fail-closed. When a folder holds statements from two WeChat
accounts and neither identity matches the ledger, the batch stops instead of
merging both wallets into one account.
"""

from __future__ import annotations

import re

from bean_import.customer_config import CustomerConfig, SourceInstance
from bean_import.sources.common import SourceParseError

HEADER_CHARACTERS = 4000
IDENTITY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "wechat": (re.compile(r"微信昵称\s*[：:]\s*\[?([^\]\n,，]+)"),),
    "alipay": (
        re.compile(r"支付宝账[户号]\s*[：:]\s*\[?([^\]\n,，]+)"),
        re.compile(r"姓\s*名\s*[：:]\s*\[?([^\]\n,，]+)"),
    ),
    "boc_debit": (
        re.compile(r"卡号\s*[：:]\s*([0-9*xX\s-]{8,})"),
        re.compile(r"(?<!\d)(\d{16,19})(?!\d)"),
        re.compile(r"客户姓名\s*[：:]\s*([^\s,，\n]+)"),
    ),
    "boc_credit": (
        re.compile(r"卡号\s*[：:]\s*([0-9*xX\s-]{8,})"),
        re.compile(r"客户姓名\s*[：:]\s*([^\s,，\n]+)"),
    ),
}


def statement_identities(kind: str, text: str) -> tuple[str, ...]:
    """Collect every identity printed in the statement header block."""

    header = text[:HEADER_CHARACTERS]
    found: list[str] = []
    for pattern in IDENTITY_PATTERNS.get(kind, ()):
        for match in pattern.finditer(header):
            value = match.group(1).strip()
            if value and value not in found:
                found.append(value)
    return tuple(found)


def resolve_source(
    config: CustomerConfig,
    kind: str,
    text: str,
    source_file: str,
) -> SourceInstance:
    """Pick the one configured source this statement belongs to."""

    instances = config.sources_of(kind)
    if not instances:
        raise SourceParseError(
            f"{source_file} is a {kind} statement but the ledger has no "
            f'[[sources]] entry with type = "{kind}"'
        )
    found = statement_identities(kind, text)
    ranked = [
        (
            max((match_rank(instance.identity, value) for value in found), default=0),
            instance,
        )
        for instance in instances
    ]
    best = max((rank for rank, _ in ranked), default=0)
    matched = [instance for rank, instance in ranked if rank == best and rank > 0]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        names = ", ".join(instance.account for instance in matched)
        raise SourceParseError(
            f"{source_file} matches more than one {kind} source: {names}"
        )
    if len(instances) == 1 and not (found and instances[0].identity):
        return instances[0]
    printed = ", ".join(found) if found else "nothing"
    configured = ", ".join(
        instance.identity or instance.account for instance in instances
    )
    raise SourceParseError(
        f"{source_file} header identifies {printed}, which matches none of the "
        f"configured {kind} sources: {configured}"
    )


def match_rank(configured: str, printed: str) -> int:
    """Score one configured identity against one printed in a header.

    Exact beats card tail beats substring. A weaker match is only used when no
    source matched more strongly, so "小明" never steals "小明工作号".
    """

    left = _normalize(configured)
    right = _normalize(printed)
    if not left or not right:
        return 0
    if left == right:
        return 3
    left_digits = _digits(left)
    right_digits = _digits(right)
    if (
        len(left_digits) >= 8
        and len(right_digits) >= 8
        and left_digits[-4:] == right_digits[-4:]
    ):
        return 2
    if left in right or right in left:
        return 1
    return 0


def _normalize(value: str) -> str:
    return "".join(value.split()).strip("[]").casefold()


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())
