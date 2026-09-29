"""The model adapter: never widens the allowlist, never fails the import."""

from __future__ import annotations

import json
from typing import Any

from bean_import.core.advice import NO_ADVICE, Advice, Candidate
from bean_import.semantic.knowledge import NO_MEMORY, memory_from_advice
from bean_import.semantic.llm import ClassifierError, OpenAICompatibleClassifier
from tests.helpers import make_request

SKILL = "外卖是送到手里的一餐。简餐是顺手吃掉的一餐。"


def classifier(
    transport: Any,
    *,
    skill: str = SKILL,
    memory: str = "",
) -> OpenAICompatibleClassifier:
    return OpenAICompatibleClassifier(
        "http://127.0.0.1:9/v1",
        "demo-model",
        skill=skill,
        memory=memory,
        transport=transport,
    )


def replies(*bodies: str) -> tuple[Any, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []
    remaining = list(bodies)

    def transport(url: str, payload: dict[str, Any], api_key: str) -> str:
        del url, api_key
        sent.append(payload)
        if not remaining:
            raise ClassifierError("没有更多响应")
        return remaining.pop(0)

    return transport, sent


def test_the_prompt_carries_the_skill_the_moment_and_the_allowed_accounts() -> None:
    transport, sent = replies(
        json.dumps(
            {"account": "Expenses:Food:Quick", "uncertain": False, "reason": "简餐"}
        )
    )

    result = classifier(transport).classify(make_request(), NO_ADVICE)

    assert result.resolved is True
    assert result.account == "Expenses:Food:Quick"
    message = str(sent[0]["messages"])
    assert "外卖" in message
    assert "星期二" in message
    assert "早晨" in message
    assert "Expenses:Food:Delivery" in message


def test_an_account_outside_the_allowlist_becomes_unknown_not_an_error() -> None:
    transport, _ = replies(
        json.dumps(
            {"account": "Expenses:NotOpen", "uncertain": False, "reason": "猜的"}
        )
    )

    result = classifier(transport).classify(make_request(), NO_ADVICE)

    assert result.status == "unknown"
    assert result.account == "Expenses:Unknown"


def test_broken_json_is_retried_once_and_then_given_up_on() -> None:
    good = json.dumps(
        {"account": "Expenses:Food:Quick", "uncertain": False, "reason": "简餐"}
    )
    transport, sent = replies("not json", good)

    result = classifier(transport).classify(make_request(), NO_ADVICE)

    assert result.resolved is True
    assert len(sent) == 2

    transport, sent = replies("not json", "still not json")
    result = classifier(transport).classify(make_request(), NO_ADVICE)
    assert result.status == "unknown"


def test_an_unreachable_endpoint_leaves_the_transaction_unknown() -> None:
    def transport(url: str, payload: dict[str, Any], api_key: str) -> str:
        del url, payload, api_key
        raise ClassifierError("connection refused")

    result = classifier(transport).classify(make_request(), NO_ADVICE)

    assert result.status == "unknown"
    assert "模型调用失败" in result.reason


def test_retrieved_memory_replaces_the_coarse_ledger_summary() -> None:
    advice = Advice((Candidate("Expenses:Food:Quick", 0.7, 4, "4 笔相似记录；中午"),))
    transport, sent = replies(
        json.dumps(
            {"account": "Expenses:Food:Quick", "uncertain": False, "reason": "x"}
        )
    )

    classifier(transport, memory="账户概览").classify(make_request(), advice)

    message = str(sent[0]["messages"])
    assert "4 笔相似记录" in message
    assert "账户概览" not in message


def test_without_any_memory_the_model_is_told_so_plainly() -> None:
    assert memory_from_advice(NO_ADVICE) == ""
    assert NO_MEMORY.startswith("账本里还没有")
