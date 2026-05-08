"""Gemini-only client with model fallback and production logging."""

from __future__ import annotations

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_gemini_env() -> None:
    """Load project env files before checking Gemini settings."""

    backend_dir = Path(__file__).resolve().parent
    root_dir = backend_dir.parent
    _load_env_file(root_dir / ".env")
    _load_env_file(backend_dir / ".env")


load_gemini_env()

DEFAULT_MODEL = os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
FALLBACK_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash-latest",
]
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "90"))


class GeminiClientError(RuntimeError):
    """Raised when every Gemini model attempt fails."""

    def __init__(self, message: str, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


@dataclass(slots=True)
class GeminiResponse:
    text: str
    model: str
    fallback_used: bool
    attempts: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    response_ms: int = 0


def gemini_enabled() -> bool:
    load_gemini_env()
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _api_key() -> str:
    load_gemini_env()
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise GeminiClientError("Falta configurar GEMINI_API_KEY o GOOGLE_API_KEY.")
    return key


def _model_order(preferred: str | None = None) -> list[str]:
    configured_default = os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_DEFAULT_MODEL") or DEFAULT_MODEL
    ordered = [preferred or configured_default, *FALLBACK_MODELS]
    result: list[str] = []
    for model in ordered:
        if model and model not in result:
            result.append(model)
    return result


def gemini_status() -> dict[str, Any]:
    load_gemini_env()
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    has_google = bool(os.getenv("GOOGLE_API_KEY"))
    enabled = has_gemini or has_google
    print("GEMINI ENABLED:", enabled)
    logger.info("GEMINI ENABLED: %s", enabled)
    return {
        "ai_enabled": enabled,
        "gemini_enabled": enabled,
        "api_key_source": "GEMINI_API_KEY" if has_gemini else "GOOGLE_API_KEY" if has_google else None,
        "model": os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_DEFAULT_MODEL") or DEFAULT_MODEL,
        "fallback_models": FALLBACK_MODELS,
        "api_base": os.getenv("GEMINI_API_BASE", GEMINI_API_BASE),
    }


def _extract_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _request_model(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_output_tokens: int,
    timeout: float,
    response_mime_type: str | None,
) -> tuple[str, dict[str, Any], int]:
    url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={_api_key()}"
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    if response_mime_type:
        body["generationConfig"]["responseMimeType"] = response_mime_type
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    response_ms = int((time.perf_counter() - started) * 1000)
    text = _extract_text(response_payload)
    if not text:
        raise GeminiClientError("Gemini respondió sin texto utilizable.")
    return text, response_payload, response_ms


def call_gemini(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.05,
    max_output_tokens: int = 8192,
    timeout: float = GEMINI_TIMEOUT_SECONDS,
    stage: str = "gemini",
    validate: Callable[[str], Any] | None = None,
    response_mime_type: str | None = "application/json",
) -> GeminiResponse:
    """Call Gemini and automatically fallback through the configured models."""

    attempts: list[dict[str, Any]] = []
    models = _model_order(model)
    for index, candidate_model in enumerate(models):
        started = time.perf_counter()
        try:
            logger.info(
                "Gemini request: stage=%s model=%s prompt_chars=%s",
                stage,
                candidate_model,
                len(user_prompt),
            )
            text, raw_payload, response_ms = _request_model(
                model=candidate_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout=timeout,
                response_mime_type=response_mime_type,
            )
            if validate:
                validate(text)
            usage = raw_payload.get("usageMetadata") or {}
            attempts.append(
                {
                    "model": candidate_model,
                    "ok": True,
                    "response_ms": response_ms,
                    "usage": usage,
                }
            )
            logger.info(
                "Gemini OK: stage=%s model=%s fallback=%s ms=%s",
                stage,
                candidate_model,
                index > 0,
                response_ms,
            )
            return GeminiResponse(
                text=text,
                model=candidate_model,
                fallback_used=index > 0,
                attempts=attempts,
                usage=usage,
                response_ms=response_ms,
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            error = f"HTTP {exc.code}: {body}"
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            error = f"Timeout/conexión: {exc}"
        except (json.JSONDecodeError, GeminiClientError, ValueError) as exc:
            error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive production guard
            error = f"Error inesperado: {exc}"

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        attempts.append({"model": candidate_model, "ok": False, "error": error, "response_ms": elapsed_ms})
        logger.warning(
            "Gemini fallback: stage=%s model=%s ms=%s error=%s",
            stage,
            candidate_model,
            elapsed_ms,
            error,
        )

    raise GeminiClientError("Todos los modelos Gemini fallaron.", attempts=attempts)
