from __future__ import annotations

import json
import re
from typing import Any

from backend.qwen_client import DEFAULT_MODEL, QwenClientError, call_qwen


class QwenStructurerError(RuntimeError):
    pass


def _parse_json(text: str) -> Any:
    raw = text.strip()
    candidates: list[str] = []

    fenced = re.findall(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", raw)
    candidates.extend(item.strip() for item in fenced if item.strip())
    candidates.append(raw)

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        cleaned = candidate.strip().removeprefix("json").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            continue

    raise QwenStructurerError("Qwen no devolvio un JSON parseable.")


def _build_user_prompt(
    *,
    markdown: str,
    tables: list[dict[str, Any]],
    parser_payload: dict[str, Any],
    document_kind: str,
    file_name: str,
) -> str:
    markdown_excerpt = markdown[:45000]
    tables_excerpt = json.dumps(tables[:8], ensure_ascii=False)
    parser_excerpt = json.dumps(
        {
            "convenio": parser_payload.get("convenio"),
            "vigencia": parser_payload.get("vigencia"),
            "categorias": parser_payload.get("categorias", [])[:18],
            "adicionales": parser_payload.get("adicionales", [])[:18],
            "subsidios": parser_payload.get("subsidios", [])[:12],
            "zonas": parser_payload.get("zonas", [])[:8],
            "reglas_liquidacion": parser_payload.get("reglas_liquidacion"),
            "no_remunerativos": parser_payload.get("no_remunerativos", [])[:18],
        },
        ensure_ascii=False,
    )

    target_note = (
        "Documento tipo CCT: prioriza categorias, jornada, antiguedad, adicionales, subsidios, zona, licencias y articulos relevantes."
        if document_kind == "cct"
        else "Documento tipo ESCALA: prioriza categorias, basicos, vigencia, no remunerativos y acuerdos."
    )

    return f"""
Archivo: {file_name}
Tipo: {document_kind}
Modelo deseado: {DEFAULT_MODEL}

{target_note}

JSON requerido:
{{
  "convenio": {{}},
  "categorias": [],
  "adicionales": [],
  "subsidios": [],
  "zonas": [],
  "vigencia": null,
  "reglas_liquidacion": {{}},
  "no_remunerativos": [],
  "acuerdos": [],
  "montos": [],
  "pendientes_revision": [],
  "alertas": [],
  "nivel_confianza": 0.0
}}

BORRADOR DEL PARSER DETERMINISTICO:
{parser_excerpt}

TABLAS OCR:
{tables_excerpt}

MARKDOWN OCR:
{markdown_excerpt}
""".strip()


def build_calculator_json(
    ocr_markdown: str,
    *,
    document_kind: str,
    file_name: str,
    tables: list[dict[str, Any]] | None = None,
    parser_payload: dict[str, Any] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    system_prompt = (
        "Sos un experto en convenios colectivos argentinos, escalas salariales y estructuras de liquidacion laboral. "
        "Debes transformar OCR markdown en JSON estructurado para calculadoras laborales. "
        "No inventes datos. Si algo no esta claro, usa null o lista vacia. Devolve solo JSON puro."
    )
    user_prompt = _build_user_prompt(
        markdown=ocr_markdown,
        tables=tables or [],
        parser_payload=parser_payload or {},
        document_kind=document_kind,
        file_name=file_name,
    )

    try:
        result = call_qwen(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=0.05,
            max_tokens=8192,
            stage=f"structure_{document_kind}",
        )
    except QwenClientError as exc:
        raise QwenStructurerError(str(exc)) from exc

    parsed = _parse_json(result["text"])
    if not isinstance(parsed, dict):
        raise QwenStructurerError("Qwen devolvio una estructura que no es objeto JSON.")

    parsed.setdefault("convenio", {})
    parsed.setdefault("categorias", [])
    parsed.setdefault("adicionales", [])
    parsed.setdefault("subsidios", [])
    parsed.setdefault("zonas", [])
    parsed.setdefault("vigencia", None)
    parsed.setdefault("reglas_liquidacion", {})
    parsed.setdefault("no_remunerativos", [])
    parsed.setdefault("acuerdos", [])
    parsed.setdefault("montos", [])
    parsed.setdefault("pendientes_revision", [])
    parsed.setdefault("alertas", [])
    parsed.setdefault("nivel_confianza", 0)
    parsed["estado"] = f"qwen_{document_kind}_estructurado"
    parsed["archivo_fuente"] = file_name
    parsed["origen"] = {
        "proveedor": "Qwen",
        "modelo": result["model"],
        "response_ms": result["response_ms"],
        "usage": result["usage"],
        "fallback_used": result["fallback_used"],
    }
    return parsed
