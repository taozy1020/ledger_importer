"""One structured completion against an OpenAI-compatible endpoint.

LangChain and LangGraph are not used. Retrieval, the model call, and account
validation are ordinary functions because this step does not branch, call tools,
or wait for a person. Fava remains the review loop.

A local Ollama server is exactly this API: `http://127.0.0.1:11434/v1`, no key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, cast

from bean_import.classify import (
    ACCEPTED,
    Classification,
    ClassificationRequest,
    unknown,
)
from bean_import.semantic.knowledge import LifeContext, describe_situation

Transport = Callable[[str, dict[str, Any], str], str]


class ClassifierError(ValueError):
    """The classifier could not return a validated account."""


class OpenAICompatibleClassifier:
    """Ask one chat-completions endpoint for an account in the allowlist."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "",
        *,
        skill: str = "",
        memory: str = "",
        transport: Transport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.skill = skill
        self.memory = memory
        self._transport = transport or urllib_transport

    def context_for(self, request: ClassificationRequest) -> LifeContext:
        """Fill the life skill with this transaction's situation and the memory."""

        return LifeContext(
            skill=self.skill,
            situation=describe_situation(request),
            memory=self.memory,
        )

    def classify(self, request: ClassificationRequest) -> Classification:
        url = (
            self.endpoint
            if self.endpoint.endswith("/chat/completions")
            else f"{self.endpoint}/chat/completions"
        )
        messages = _messages(request, self.context_for(request))
        try:
            content = self._complete(url, messages)
        except ClassifierError as error:
            return unknown(request, f"模型调用失败：{error}", self.model)
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
                return unknown(request, str(error), self.model)
        account = parsed["account"]
        if parsed["uncertain"] or account not in request.allowed_accounts:
            reason = parsed["reason"] or "账户不在允许列表中"
            return unknown(request, reason, self.model)
        return Classification(
            account=account,
            uncertain=False,
            reason=parsed["reason"],
            model_id=self.model,
            status=ACCEPTED,
        )

    def _complete(self, url: str, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
        }
        return self._transport(url, payload, self.api_key)


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


def _messages(
    request: ClassificationRequest,
    context: LifeContext,
) -> list[dict[str, str]]:
    payload = {
        "kind": request.kind,
        "role": request.role,
        "situation": context.situation,
        "memory": context.memory,
        "skill": context.skill,
        "allowed_accounts": list(request.allowed_accounts),
    }
    return [
        {
            "role": "system",
            "content": (
                "你根据这个人写下的生活说明、这笔交易的情境，以及账本记忆来选择账户。"
                "记忆不是店名规则。同一商户在不同时间和金额下可以属于不同账户。"
                "只能从 allowed_accounts 中选择一个账户。"
                "不确定时把 uncertain 设为 true。"
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
