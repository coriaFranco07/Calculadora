from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib import error, parse, request


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


class GeminiProxyError(RuntimeError):
    pass


def build_prompt(payload: Mapping[str, Any]) -> str:
    return f"""
Actua como auditor preventivo senior de payroll argentino, AFIP y Libro de Sueldos Digital.

Reglas de respuesta:
- NO recalcules la liquidacion completa.
- NO inventes normas que no surjan del contexto.
- Prioriza riesgos operativos, AFIP, SAC, bases imponibles y consistencia previa a exportacion.
- Si algo falta para concluir, decilo explicitamente.
- Responde en espanol neutro, breve y ejecutivo.

Periodo: {payload.get("periodo", "")}

Resumen de totalizadores:
{json.dumps(payload.get("resumen_totalizadores", {}), ensure_ascii=False, indent=2)}

Resumen de revista:
{json.dumps(payload.get("resumen_revista", {}), ensure_ascii=False, indent=2)}

Hallazgos deterministas previos:
{json.dumps(payload.get("errores_detectados", []), ensure_ascii=False, indent=2)}

Quiero:
1. Diagnostico ejecutivo.
2. Riesgos AFIP/laborales mas importantes.
3. Acciones sugeridas en orden de prioridad.
4. Si el caso deberia bloquearse o no, y por que.
""".strip()


def call_gemini(prompt: str, model: str | None = None) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiProxyError("GEMINI_API_KEY no configurada.")

    active_model = model or DEFAULT_MODEL
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

    try:
        with request.urlopen(req, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GeminiProxyError(f"Gemini rechazo la solicitud: {detail}") from exc
    except error.URLError as exc:
        raise GeminiProxyError(f"No se pudo contactar Gemini: {exc.reason}") from exc

    parts = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
    if not text.strip():
        raise GeminiProxyError("Gemini no devolvio texto util.")
    return text.strip()
