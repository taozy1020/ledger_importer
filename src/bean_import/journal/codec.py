"""Translate journal entries to and from plain JSON.

The journal is a feature store, not a log: it keeps the features exactly as the
classifier saw them. Tokens are written out rather than recomputed on read, so
changing the tokenizer later cannot silently rewrite history.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from bean_import.core.advice import Advice, Candidate
from bean_import.core.journal import (
    SCHEMA_VERSION,
    Decision,
    JournalEntry,
    Proposal,
)
from bean_import.core.situation import Situation


class JournalFormatError(ValueError):
    """A journal record cannot be read back."""


def encode(entry: JournalEntry) -> dict[str, Any]:
    return {
        "version": entry.version,
        "recorded_on": entry.recorded_on.isoformat(),
        "event_id": entry.event_id,
        "situation": _encode_situation(entry.situation),
        "known_accounts": list(entry.known_accounts),
        "allowed_accounts": list(entry.allowed_accounts),
        "unknown_account": entry.unknown_account,
        "proposal": _encode_proposal(entry.proposal),
        "decision": _encode_decision(entry.decision),
    }


def decode(payload: object) -> JournalEntry:
    record = _object(payload, "record")
    version = record.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise JournalFormatError(f"unsupported journal version: {version!r}")
    decision = record.get("decision")
    return JournalEntry(
        situation=_decode_situation(record.get("situation")),
        known_accounts=_strings(record.get("known_accounts"), "known_accounts"),
        allowed_accounts=_strings(record.get("allowed_accounts"), "allowed_accounts"),
        unknown_account=_string(record.get("unknown_account"), "unknown_account"),
        proposal=_decode_proposal(record.get("proposal")),
        recorded_on=_date(record.get("recorded_on"), "recorded_on"),
        decision=None if decision is None else _decode_decision(decision),
        version=SCHEMA_VERSION,
    )


def _encode_situation(situation: Situation) -> dict[str, Any]:
    return {
        "event_id": situation.event_id,
        "kind": situation.kind,
        "role": situation.role,
        "on": situation.on.isoformat(),
        "clock": situation.clock,
        "weekday": situation.weekday,
        "day_part": situation.day_part,
        "is_weekend": situation.is_weekend,
        "amount": str(situation.amount),
        "currency": situation.currency,
        "payee": situation.payee,
        "narration": situation.narration,
        "source_category": situation.source_category,
        "source_types": list(situation.source_types),
        "tokens": sorted(situation.tokens),
    }


def _decode_situation(payload: object) -> Situation:
    record = _object(payload, "situation")
    amount = _decimal(record.get("amount"), "situation.amount")
    return Situation(
        event_id=_string(record.get("event_id"), "situation.event_id"),
        kind=_string(record.get("kind"), "situation.kind"),
        role=_string(record.get("role"), "situation.role"),
        on=_date(record.get("on"), "situation.on"),
        clock=_text(record.get("clock")),
        weekday=_integer(record.get("weekday"), "situation.weekday"),
        day_part=_text(record.get("day_part")),
        is_weekend=bool(record.get("is_weekend")),
        amount=amount,
        magnitude=abs(amount),
        currency=_text(record.get("currency")),
        payee=_text(record.get("payee")),
        narration=_text(record.get("narration")),
        source_category=_text(record.get("source_category")),
        source_types=_strings(record.get("source_types"), "situation.source_types"),
        tokens=frozenset(_strings(record.get("tokens"), "situation.tokens")),
    )


def _encode_proposal(proposal: Proposal) -> dict[str, Any]:
    return {
        "account": proposal.account,
        "status": proposal.status,
        "origin": proposal.origin,
        "confidence": proposal.confidence,
        "reason": proposal.reason,
        "candidates": [
            {
                "account": candidate.account,
                "confidence": candidate.confidence,
                "support": candidate.support,
                "evidence": candidate.evidence,
            }
            for candidate in proposal.advice.candidates
        ],
    }


def _decode_proposal(payload: object) -> Proposal:
    record = _object(payload, "proposal")
    raw = record.get("candidates", [])
    if not isinstance(raw, list):
        raise JournalFormatError("proposal.candidates must be a list")
    candidates = tuple(_decode_candidate(item) for item in cast(list[object], raw))
    return Proposal(
        account=_string(record.get("account"), "proposal.account"),
        status=_string(record.get("status"), "proposal.status"),
        origin=_string(record.get("origin"), "proposal.origin"),
        confidence=_number(record.get("confidence"), "proposal.confidence"),
        reason=_text(record.get("reason")),
        advice=Advice(candidates),
    )


def _decode_candidate(payload: object) -> Candidate:
    record = _object(payload, "candidate")
    return Candidate(
        account=_string(record.get("account"), "candidate.account"),
        confidence=_number(record.get("confidence"), "candidate.confidence"),
        support=_integer(record.get("support"), "candidate.support"),
        evidence=_text(record.get("evidence")),
    )


def _encode_decision(decision: Decision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "outcome": decision.outcome,
        "account": decision.account,
        "observed_on": decision.observed_on.isoformat(),
    }


def _decode_decision(payload: object) -> Decision:
    record = _object(payload, "decision")
    return Decision(
        outcome=_string(record.get("outcome"), "decision.outcome"),
        account=_text(record.get("account")),
        observed_on=_date(record.get("observed_on"), "decision.observed_on"),
    )


def _object(payload: object, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise JournalFormatError(f"{label} must be an object")
    return cast(dict[str, Any], payload)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise JournalFormatError(f"{label} must be a non-empty string")
    return value


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise JournalFormatError(f"{label} must be a list")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise JournalFormatError(f"{label} must contain only strings")
    return tuple(cast(list[str], items))


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise JournalFormatError(f"{label} must be an integer")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JournalFormatError(f"{label} must be a number")
    return float(value)


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise JournalFormatError(f"{label} must be a decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise JournalFormatError(f"{label} is not a decimal: {value!r}") from error


def _date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise JournalFormatError(f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise JournalFormatError(f"{label} is not an ISO date: {value!r}") from error
