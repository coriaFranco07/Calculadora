"""Utilities to parse and recover JSON returned by Gemini.

Gemini is instructed to return JSON, but production pipelines still need to
survive markdown fences, explanatory text, truncated objects and trailing
commas. These helpers keep the extraction flow useful even when the model
response is imperfect.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)


JSONValue = dict[str, Any] | list[Any]


class JsonRecoveryError(ValueError):
    """Raised when no usable JSON can be recovered from a model response."""


def _strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text


def _candidate_from_text(raw: str) -> str:
    text = _strip_markdown_fences(raw)
    starts = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
    if not starts:
        raise JsonRecoveryError("No se encontró un objeto JSON en la respuesta.")

    start = min(starts)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    end = text.rfind(closing)
    if end > start:
        return text[start : end + 1].strip()
    return text[start:].strip()


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _balance_json(candidate: str) -> str:
    stack: list[str] = []
    result: list[str] = []
    in_string = False
    escaped = False

    for char in candidate:
        result.append(char)
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in ("}", "]"):
            if stack and stack[-1] == char:
                stack.pop()

    if in_string:
        result.append('"')

    while stack:
        result.append(stack.pop())

    return "".join(result)


def repair_partial_json(raw: str) -> JSONValue:
    """Try to repair markdown/noisy/truncated JSON and return parsed data."""

    candidate = _candidate_from_text(raw)
    candidate = candidate.replace("\ufeff", "").replace("\u00a0", " ")
    candidate = candidate.replace("“", '"').replace("”", '"').replace("’", "'")
    candidate = _remove_trailing_commas(candidate)

    attempts = [
        candidate,
        _balance_json(candidate),
        _remove_trailing_commas(_balance_json(candidate)),
    ]

    last_error: Exception | None = None
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as exc:
            last_error = exc

    logger.debug("No se pudo reparar JSON parcial: %s", last_error)
    raise JsonRecoveryError("No se pudo reparar el JSON parcial.") from last_error


def parse_gemini_json(raw: str) -> JSONValue:
    """Parse a Gemini response, accepting clean JSON or recoverable variants."""

    if not raw or not raw.strip():
        raise JsonRecoveryError("La respuesta de Gemini llegó vacía.")

    stripped = _strip_markdown_fences(raw)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return repair_partial_json(stripped)


def _merge_lists(primary: list[Any], fallback: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in [*primary, *fallback]:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _deep_merge(primary: Any, fallback: Any) -> Any:
    if isinstance(primary, dict) and isinstance(fallback, dict):
        merged = deepcopy(fallback)
        for key, value in primary.items():
            if value in (None, "", [], {}):
                continue
            merged[key] = _deep_merge(value, merged.get(key))
        return merged
    if isinstance(primary, list) and isinstance(fallback, list):
        return _merge_lists(primary, fallback)
    return deepcopy(primary) if primary not in (None, "", [], {}) else deepcopy(fallback)


def recover_partial_payload(
    gemini_text: str,
    fallback_payload: dict[str, Any],
    *,
    expected_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Recover useful model data and merge it over a deterministic fallback."""

    fallback = deepcopy(fallback_payload or {})
    try:
        parsed = parse_gemini_json(gemini_text)
    except JsonRecoveryError as exc:
        fallback.setdefault("alertas", []).append(f"Gemini devolvió JSON no recuperable: {exc}")
        fallback.setdefault("pendientes_revision", []).append("Revisar extracción: se usó fallback local por JSON inválido.")
        return fallback

    if isinstance(parsed, list):
        parsed = {"items": parsed}
    if not isinstance(parsed, dict):
        fallback.setdefault("alertas", []).append("Gemini devolvió un JSON con formato no esperado.")
        return fallback

    merged = _deep_merge(parsed, fallback)
    if expected_keys:
        for key in expected_keys:
            merged.setdefault(key, deepcopy(fallback.get(key, [] if key.endswith("s") else {})))
    return merged
