from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, Mapping
from urllib import error, parse, request


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
FALLBACK_MODELS = [
    item.strip()
    for item in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-2.0-flash,gemini-2.0-flash-lite,gemini-1.5-flash-latest",
    ).split(",")
    if item.strip()
]


class GeminiProxyError(RuntimeError):
    pass


def normalize_text(value: Any) -> str:
    return (
        unicodedata.normalize("NFD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def build_prompt(payload: Mapping[str, Any]) -> str:
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


def build_focus_cct_text(text: Any, limit: int = 24000) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw

    headline = raw[:9000]
    keywords = (
        "categoria",
        "operario",
        "oficial",
        "administr",
        "jornada",
        "hora",
        "horas extra",
        "antiguedad",
        "presentismo",
        "zona",
        "adicional",
        "no remunerativ",
        "licencia",
        "feriado",
        "viatico",
        "escala",
        "sueldo",
        "salario",
        "basico",
        "remunerativo",
        "aporte",
        "contribucion",
    )

    selected_lines: list[str] = []
    seen: set[str] = set()
    for raw_line in raw.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 8 or len(line) > 260:
            continue
        normalized = normalize_text(line)
        if not any(keyword in normalized for keyword in keywords):
            continue
        if line in seen:
            continue
        seen.add(line)
        selected_lines.append(line)
        if sum(len(item) for item in selected_lines) >= limit - len(headline) - 120:
            break

    focused = f"{headline}\n\nLINEAS RELEVANTES:\n" + "\n".join(selected_lines)
    return focused[:limit]


def build_cct_text_extraction_prompt(payload: Mapping[str, Any]) -> str:
    cct_text = build_focus_cct_text(payload.get("text", ""), limit=28000)
    file_name = payload.get("file_name", "CCT.pdf")
    return f"""
Sos Gemini leyendo un PDF laboral argentino para alimentar una calculadora de liquidacion.
Tu tarea NO es devolver JSON. Tu tarea es limpiar, ordenar y resumir en texto tecnico fiel.
No inventes importes, porcentajes, fechas ni categorias.
Conserva importes, porcentajes, vigencias, categorias, articulos y fuentes textuales cuando aparezcan.
Marca con "DATO NO DETECTADO" lo que no este claro.

Archivo: {file_name}

Devolve texto en estas secciones:
1. Identificacion del convenio o norma.
2. Vigencia y ambito.
3. Jornada y parametros de liquidacion.
4. Categorias y escalas detectadas.
5. Adicionales remunerativos y no remunerativos.
6. Horas extra, feriados, licencias y zona.
7. Alertas de OCR o datos dudosos.
8. Lineas fuente relevantes.

TEXTO EXTRAIDO DEL PDF:
{cct_text}
""".strip()


def build_codex_json_structuring_prompt(payload: Mapping[str, Any]) -> str:
    file_name = payload.get("file_name", "CCT.pdf")
    extracted_text = str(payload.get("extracted_text", "")).strip()
    return f"""
Sos Codex estructurando texto laboral argentino en JSON para una calculadora de CCT.
Devolve SOLO JSON valido, sin markdown, sin comentarios, sin ```json.
No inventes datos: si falta un dato, usa null y agregalo en pendientes_revision.
Si hay muchas categorias, devuelve como maximo 24 y agrega una alerta si quedaron categorias afuera.
Usa ids slug en minuscula con guion bajo.
Manten descripciones y fuentes cortas.

JSON exacto requerido:
{{
  "version": "YYYY-MM-DD",
  "archivo_fuente": "{file_name}",
  "estado": "json_codex_estructurado",
  "pipeline": {{
    "lector": "gemini",
    "estructurador": "codex"
  }},
  "convenio": {{
    "nombre": null,
    "actividad": null,
    "ambito": null,
    "cct_numero": null,
    "vigencia_detectada": null
  }},
  "parametros": {{
    "divisor_mensual": 30,
    "horas_mensuales": null,
    "horas_semanales": null,
    "base_calculo": "simple"
  }},
  "categorias": [
    {{
      "id": "slug",
      "nombre": "",
      "tipo": "jornalizado|mensualizado|administrativo|otro|null",
      "descripcion": "",
      "valor_hora": null,
      "sueldo_mensual": null,
      "fuente_textual": ""
    }}
  ],
  "adicionales": [
    {{
      "nombre": "",
      "tipo": "porcentaje|importe|formula|otro",
      "valor": null,
      "base": null,
      "condicion": null,
      "codigo_sugerido": null,
      "lsd": null,
      "fuente_textual": ""
    }}
  ],
  "reglas_liquidacion": {{
    "antiguedad": null,
    "presentismo": null,
    "zona_desfavorable": null,
    "horas_extra": null,
    "licencias": [],
    "no_remunerativos": []
  }},
  "pendientes_revision": [],
  "alertas": [],
  "nivel_confianza": 0.0
}}

TEXTO NORMALIZADO POR GEMINI:
{extracted_text}
""".strip()


def build_cct_extraction_prompt(payload: Mapping[str, Any]) -> str:
    """Compatibilidad: estructura directo a JSON si se usa el flujo viejo."""
    text_prompt = build_cct_text_extraction_prompt(payload)
    return build_codex_json_structuring_prompt(
        {
            "file_name": payload.get("file_name", "CCT.pdf"),
            "extracted_text": text_prompt,
        }
    )


def _call_gemini_once(prompt: str, active_model: str, api_key: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{parse.quote(active_model)}:generateContent?key={parse.quote(api_key)}"
    )

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.05,
            "topP": 0.8,
            "maxOutputTokens": 4096,
        },
    }

    data = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

    with request.urlopen(req, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))

    parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
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
            if exc.code == 404:
                continue
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except error.URLError as exc:
            errors.append(f"{active_model}: {exc.reason}")
        except GeminiProxyError as exc:
            errors.append(f"{active_model}: {exc}")
            break

    raise GeminiProxyError("Gemini no pudo responder temporalmente. Ultimos errores: " + " | ".join(errors[-2:]))
