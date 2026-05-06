from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib import error, parse, request


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
FALLBACK_MODELS = [
    item.strip()
    for item in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-1.5-flash,gemini-1.5-flash-8b").split(",")
    if item.strip()
]


class GeminiProxyError(RuntimeError):
    pass


def build_prompt(payload: Mapping[str, Any]) -> str:
    return f"""
Actua como auditor preventivo senior de payroll argentino, AFIP, Libro de Sueldos Digital y normativa laboral argentina.

Reglas de respuesta:
- Responde la pregunta concreta del usuario.
- Usa primero el contexto documental interno si fue provisto.
- NO recalcules la liquidacion completa.
- NO inventes normas que no surjan del contexto.
- Si el contexto documental no alcanza, decilo explicitamente.
- Prioriza riesgos operativos, AFIP, SAC, bases imponibles y consistencia previa a exportacion.
- Responde en espanol claro, breve y ejecutivo.
- Si mencionas una fuente, usa el nombre y fragmento provisto.

Pregunta del usuario:
{payload.get("pregunta_usuario", "")}

Periodo:
{payload.get("periodo", "")}

Resumen de totalizadores:
{json.dumps(payload.get("resumen_totalizadores", {}), ensure_ascii=False, indent=2)}

Resumen de revista:
{json.dumps(payload.get("resumen_revista", {}), ensure_ascii=False, indent=2)}

Hallazgos deterministas previos:
{json.dumps(payload.get("errores_detectados", []), ensure_ascii=False, indent=2)}

Contexto documental interno:
{json.dumps(payload.get("contexto_documental", []), ensure_ascii=False, indent=2)}

Quiero:
1. Respuesta directa a la pregunta.
2. Fundamento con base interna cuando exista.
3. Riesgo laboral/AFIP si corresponde.
4. Accion sugerida si corresponde.
""".strip()


def _call_gemini_once(prompt: str, active_model: str, api_key: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{parse.quote(active_model)}:generateContent?key={parse.quote(api_key)}"
    )

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 900,
        },
    }

    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))

    parts = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
    if not text.strip():
        raise GeminiProxyError("Gemini no devolvio texto util.")
    return text.strip()


def call_gemini(prompt: str, model: str | None = None) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiProxyError("GEMINI_API_KEY no configurada.")

    models_to_try = []
    first_model = model or DEFAULT_MODEL
    for candidate in [first_model, *FALLBACK_MODELS]:
        if candidate and candidate not in models_to_try:
            models_to_try.append(candidate)

    errors: list[str] = []
    for active_model in models_to_try:
        try:
            return _call_gemini_once(prompt, active_model, api_key)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{active_model}: {detail}")
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except error.URLError as exc:
            errors.append(f"{active_model}: {exc.reason}")
        except GeminiProxyError as exc:
            errors.append(f"{active_model}: {exc}")
            break

    raise GeminiProxyError("Gemini no pudo responder con los modelos disponibles: " + " | ".join(errors))
