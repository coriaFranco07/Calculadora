from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
FALLBACK_MODELS = [
    item.strip()
    for item in os.getenv("QWEN_FALLBACK_MODELS", "qwen-max").split(",")
    if item.strip()
]
BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class QwenClientError(RuntimeError):
    pass


def _import_openai():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise QwenClientError("Falta instalar openai en el backend. Ejecuta pip install openai.") from exc
    return OpenAI


def build_audit_prompt(payload: Mapping[str, Any]) -> str:
    return f"""
Actua como auditor preventivo senior de payroll argentino, AFIP, Libro de Sueldos Digital y normativa laboral argentina.
Responde breve, en espanol, usando el contexto documental si existe.

Pregunta: {payload.get("pregunta_usuario", "")}
Periodo: {payload.get("periodo", "")}
Totalizadores: {json.dumps(payload.get("resumen_totalizadores", {}), ensure_ascii=False)}
Revista: {json.dumps(payload.get("resumen_revista", {}), ensure_ascii=False)}
Hallazgos: {json.dumps(payload.get("errores_detectados", []), ensure_ascii=False)}
Contexto: {json.dumps(payload.get("contexto_documental", []), ensure_ascii=False)}
""".strip()


def call_qwen(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.05,
    max_tokens: int = 8192,
    stage: str = "general",
) -> dict[str, Any]:
    api_key = (os.getenv("QWEN_API_KEY") or "").strip()
    if not api_key:
        raise QwenClientError("QWEN_API_KEY no configurada.")

    OpenAI = _import_openai()
    client = OpenAI(api_key=api_key, base_url=BASE_URL)

    models_to_try: list[str] = []
    for candidate in [model or DEFAULT_MODEL, *FALLBACK_MODELS]:
        if candidate and candidate not in models_to_try:
            models_to_try.append(candidate)

    errors: list[str] = []
    for active_model in models_to_try:
        started = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=active_model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

            content = response.choices[0].message.content if response.choices else ""
            text = content.strip() if isinstance(content, str) else ""
            if not text:
                raise QwenClientError("Qwen no devolvio texto util.")

            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)

            LOGGER.info(
                "Qwen ok stage=%s model=%s response_ms=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                stage,
                active_model,
                elapsed_ms,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )

            return {
                "text": text,
                "model": active_model,
                "response_ms": elapsed_ms,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
                "fallback_used": active_model != (model or DEFAULT_MODEL),
            }
        except Exception as exc:  # pragma: no cover - network/provider dependent
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            status = getattr(exc, "status_code", None)
            errors.append(f"{active_model}: {exc}")
            LOGGER.warning(
                "Qwen error stage=%s model=%s response_ms=%s status=%s detail=%s",
                stage,
                active_model,
                elapsed_ms,
                status,
                exc,
            )
            continue

    raise QwenClientError("Qwen no pudo responder temporalmente. Ultimos errores: " + " | ".join(errors[-2:]))
