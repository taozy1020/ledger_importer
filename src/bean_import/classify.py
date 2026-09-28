"""One structured completion against an OpenAI-compatible endpoint.

LangChain and LangGraph are not used. Retrieval, the model call, and account
validation are ordinary functions because this step does not branch, call tools,
or wait for a person. Fava remains the review loop.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, cast

from bean_import.knowledge import KnowledgeExample, KnowledgeGuide, best_example

Transport = Callable[[str, dict[str, Any], str], str]


class ClassifierError(ValueError):
    """The classifier could not return a validated account."""


@dataclass(frozen=True, slots=True)
class ClassificationRequest:
    """The only fields a semantic classifier is allowed to see."""

    event_id: str
    kind: str
    role: str
    transaction_date: date
    amount: Decimal
    currency: str
    payee: str
    narration: str
    source_category: str
    source_types: tuple[str, ...]
    allowed_accounts: tuple[str, ...]
    suspense_account: str
    examples: tuple[KnowledgeExample, ...]
    guides: tuple[KnowledgeGuide, ...]


@dataclass(frozen=True, slots=True)
class Classification:
    """A validated account choice, or an explicit suspense fallback."""

    account: str
    uncertain: bool
    reason: str
    model_id: str
    status: str


class SemanticClassifier(Protocol):
    def classify(self, request: ClassificationRequest) -> Classification:
        """Choose one allowed account, or suspense when the choice is unsafe."""

        ...


class KnowledgeClassifier:
    """Use a curated payee example when no model endpoint is configured."""

    def classify(self, request: ClassificationRequest) -> Classification:
        match = best_example(
            payee=request.payee,
            narration=request.narration,
            source_category=request.source_category,
            examples=request.examples,
            allowed_accounts=request.allowed_accounts,
        )
        if match is None:
            return suspense(request, "知识库没有匹配的商户示例", "knowledge")
        return Classification(
            account=match.account,
            uncertain=False,
            reason=f"知识库示例“{match.payee}”",
            model_id="knowledge",
            status="accepted",
        )


class OpenAICompatibleClassifier:
    """Ask one chat-completions endpoint for an account in the allowlist."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "",
        transport: Transport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._transport = transport or urllib_transport

    def classify(self, request: ClassificationRequest) -> Classification:
        url = (
            self.endpoint
            if self.endpoint.endswith("/chat/completions")
            else f"{self.endpoint}/chat/completions"
        )
        messages = _messages(request)
        try:
            content = self._complete(url, messages)
        except ClassifierError as error:
            return suspense(request, f"模型调用失败：{error}", self.model)
        try:
            parsed = _parse_choice(content)
        except ClassifierError:
            try:
                content = self._complete(
                    url,
                    [
                        *messages,
                        {
                            "role": "user",
                            "content": "上一次响应不是要求的 JSON。请只重发 JSON。",
                        },
                    ],
                )
                parsed = _parse_choice(content)
            except ClassifierError as error:
                return suspense(request, str(error), self.model)
        account = parsed["account"]
        if parsed["uncertain"] or account not in request.allowed_accounts:
            reason = parsed["reason"] or "账户不在允许列表中"
            return suspense(request, reason, self.model)
        return Classification(
            account=account,
            uncertain=False,
            reason=parsed["reason"],
            model_id=self.model,
            status="accepted",
        )

    def _complete(self, url: str, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
        }
        return self._transport(url, payload, self.api_key)


def suspense(
    request: ClassificationRequest,
    reason: str,
    model_id: str,
) -> Classification:
    return Classification(
        account=request.suspense_account,
        uncertain=True,
        reason=reason[:200],
        model_id=model_id,
        status="suspense",
    )


def urllib_transport(url: str, payload: dict[str, Any], api_key: str) -> str:
    """POST a chat-completions request and return the message content."""

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise ClassifierError(str(error)) from error
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError as error:
        raise ClassifierError("模型服务返回的不是 JSON") from error
    if not isinstance(parsed, dict):
        raise ClassifierError("模型服务返回的不是 JSON 对象")
    payload_object = cast(dict[str, Any], parsed)
    choices = payload_object.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ClassifierError("模型服务没有返回 choices")
    first = cast(list[object], choices)[0]
    if not isinstance(first, dict):
        raise ClassifierError("模型服务返回的 choice 无效")
    message = cast(dict[str, Any], first).get("message")
    if not isinstance(message, dict):
        raise ClassifierError("模型服务没有返回 message")
    content = cast(dict[str, Any], message).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ClassifierError("模型服务返回了空内容")
    return content


def _messages(request: ClassificationRequest) -> list[dict[str, str]]:
    payload = {
        "kind": request.kind,
        "role": request.role,
        "date": request.transaction_date.isoformat(),
        "amount": str(request.amount),
        "currency": request.currency,
        "payee": request.payee,
        "narration": request.narration,
        "source_category": request.source_category,
        "source_types": list(request.source_types),
        "allowed_accounts": list(request.allowed_accounts),
        "examples": [
            {"payee": example.payee, "account": example.account, "note": example.note}
            for example in request.examples
        ],
        "guides": [guide.text for guide in request.guides],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是记账分类器。只能从 allowed_accounts 中选择一个账户。"
                "不要改写金额、日期或事件类型。不确定时把 uncertain 设为 true。"
                '只输出 JSON：{"account":"账户","uncertain":false,"reason":"简短原因"}'
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _parse_choice(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        fence = stripped.rfind("```")
        if fence >= 0:
            stripped = stripped[:fence]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ClassifierError("模型响应里没有 JSON 对象")
    try:
        parsed: object = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as error:
        raise ClassifierError("模型响应不是有效 JSON") from error
    if not isinstance(parsed, dict):
        raise ClassifierError("模型响应不是 JSON 对象")
    item = cast(dict[str, Any], parsed)
    account = item.get("account")
    reason = item.get("reason", "")
    uncertain = item.get("uncertain", False)
    if not isinstance(account, str) or not account:
        raise ClassifierError("模型响应缺少 account")
    if not isinstance(reason, str):
        raise ClassifierError("模型响应的 reason 必须是字符串")
    if not isinstance(uncertain, bool):
        raise ClassifierError("模型响应的 uncertain 必须是布尔值")
    return {"account": account, "reason": reason[:200], "uncertain": uncertain}


def allowed_accounts_for(
    role: str,
    expense_accounts: Sequence[str],
    income_accounts: Sequence[str],
) -> tuple[str, ...]:
    if role == "income_account":
        return tuple(income_accounts)
    return tuple(expense_accounts)
