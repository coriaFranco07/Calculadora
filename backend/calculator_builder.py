"""Gemini + local parser orchestration for calculator-ready JSON."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

from backend.cct_parser import merge_calculator_payload, merge_document_payloads, parse_document
from backend.escala_parser import normalize_salary_scales
from backend.gemini_proxy import GeminiClientError, call_gemini, gemini_enabled
from backend.json_repair import JsonRecoveryError, parse_gemini_json, recover_partial_payload
from backend.pdf_extractor import PdfExtractionResult, smart_chunking


logger = logging.getLogger(__name__)

FINAL_SCHEMA_KEYS = [
    "version",
    "archivo_fuente",
    "convenio",
    "parametros",
    "categorias",
    "escalas_salariales",
    "adicionales",
    "conceptos",
    "reglas_liquidacion",
    "matriz_tecnica",
    "pendientes_revision",
    "alertas",
    "nivel_confianza",
]


DOCUMENT_SYSTEM_PROMPT = """Sos un analista laboral argentino especializado en CCT, escalas salariales y liquidación de haberes.
Extraé datos técnicos de documentos legales y salariales con precisión.
No inventes importes, porcentajes, fechas ni reglas. Usá null cuando falte información.
Respondé únicamente JSON válido, sin markdown ni comentarios externos."""


def _document_prompt(
    *,
    kind: str,
    file_name: str,
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    local_payload: dict[str, Any],
) -> str:
    expected = {
        "version": "1.0",
        "archivo_fuente": file_name,
        "tipo_documento": kind,
        "convenio": {},
        "actividad": None,
        "ambito": None,
        "vigencias": [],
        "categorias": [],
        "escalas_salariales": [
            {
                "categoria": "",
                "basico": None,
                "valor_hora": None,
                "vigencia_desde": "",
                "vigencia_hasta": "",
                "jornada": "",
                "tipo": "",
                "fuente_textual": "",
            }
        ],
        "adicionales": [],
        "conceptos": [],
        "reglas_liquidacion": {},
        "matriz_tecnica": [],
        "pendientes_revision": [],
        "alertas": [],
        "nivel_confianza": 0,
    }
    return f"""
Analizá el siguiente fragmento de un documento laboral argentino.

Documento: {file_name}
Tipo: {kind}
Fragmento: {chunk_index + 1} de {total_chunks}

Objetivo:
- Detectar convenio, actividad, ámbito y fechas de vigencia.
- Detectar categorías, básicos, valor hora, jornadas, adicionales, presentismo, antigüedad, viáticos, no remunerativos, descuentos, incidencias y reglas de liquidación.
- Detectar tablas, listas y texto corrido de escalas salariales.
- Mantener fuente_textual breve para importes o reglas importantes.
- No inventar datos. Usar null cuando un dato no esté explícito.
- Agregar pendientes_revision y alertas si falta contexto o hay ambigüedad.
- Informar nivel_confianza entre 0 y 100.

JSON esperado:
{json.dumps(expected, ensure_ascii=False, indent=2)}

Señales locales ya detectadas para ayudarte, no las copies si contradicen el texto:
{json.dumps(local_payload, ensure_ascii=False)[:12000]}

Texto del fragmento:
{chunk_text}
""".strip()


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = deepcopy(payload)
    for key in ("texto_original", "markdown", "text", "pages", "chunks"):
        compact.pop(key, None)
    return compact


def _merge_document_results(results: list[dict[str, Any]], fallback: dict[str, Any], *, kind: str, file_name: str) -> dict[str, Any]:
    merged = deepcopy(fallback)
    direct_scales: list[dict[str, Any]] = []
    direct_concepts: list[dict[str, Any]] = []
    direct_matrix: list[dict[str, Any]] = []
    for result in results:
        direct_scales.extend([item for item in result.get("escalas_salariales", []) or [] if isinstance(item, dict)])
        direct_concepts.extend([item for item in result.get("conceptos", []) or [] if isinstance(item, dict)])
        direct_matrix.extend([item for item in result.get("matriz_tecnica", []) or [] if isinstance(item, dict)])
        merged = merge_document_payloads(result, merged, kind=kind, file_name=file_name)
    merged.setdefault("alertas", [])
    merged.setdefault("pendientes_revision", [])
    merged.setdefault("categorias", [])
    merged.setdefault("adicionales", [])
    merged.setdefault("conceptos", [])
    merged.setdefault("reglas_liquidacion", {})
    merged.setdefault("matriz_tecnica", [])
    merged.setdefault("nivel_confianza", 0)
    merged["escalas_salariales"] = normalize_salary_scales(
        {**merged, "escalas_salariales": direct_scales + (merged.get("escalas_salariales") or [])},
        file_name=file_name,
    )
    if direct_concepts:
        merged["conceptos"] = direct_concepts + [item for item in merged.get("conceptos", []) or [] if isinstance(item, dict)]
    if direct_matrix:
        merged["matriz_tecnica"] = direct_matrix + [item for item in merged.get("matriz_tecnica", []) or [] if isinstance(item, dict)]
    return merged


def _validate_json_response(text: str) -> None:
    parsed = parse_gemini_json(text)
    if not isinstance(parsed, dict):
        raise JsonRecoveryError("Gemini no devolvió un objeto JSON.")


def _normalize_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(payload)
    for category in normalized.get("categorias", []) or []:
        if isinstance(category, dict) and not category.get("nombre") and category.get("categoria"):
            category["nombre"] = category.get("categoria")
    for concept in normalized.get("conceptos", []) or []:
        if isinstance(concept, dict) and not concept.get("nombre") and concept.get("concepto"):
            concept["nombre"] = concept.get("concepto")
    return normalized


def build_document_payload(
    *,
    extraction: PdfExtractionResult | None,
    text: str,
    kind: str,
    file_name: str,
    provider: str = "Gemini + Parser local",
) -> dict[str, Any]:
    """Analyze one CCT/scale document with Gemini, falling back locally."""

    ocr_payload = extraction.to_ocr_payload(provider=provider) if extraction else {
        "provider": provider,
        "file_name": file_name,
        "markdown": text,
        "text": text,
        "pages": [],
        "tables": [],
        "chunks": smart_chunking(text),
        "text_length": len(text or ""),
        "page_count": 0,
        "alerts": [],
    }
    fallback = parse_document(ocr_payload, kind=kind, file_name=file_name, provider="PDF local + Parser")
    fallback.setdefault("diagnostico_ia", {})
    fallback.setdefault("alertas", [])
    fallback.setdefault("pendientes_revision", [])
    fallback["escalas_salariales"] = normalize_salary_scales(fallback, file_name=file_name)

    chunks = ocr_payload.get("chunks") or smart_chunking(text)
    diagnostics: dict[str, Any] = {
        "gemini_enabled": gemini_enabled(),
        "modelo_usado": None,
        "fallback_activo": False,
        "chunks_enviados": 0,
        "intentos": [],
        "errores": [],
        "text_length": len(text or ""),
    }

    if not gemini_enabled():
        fallback["alertas"].append("Gemini no está configurado; se generó borrador local automático.")
        fallback["pendientes_revision"].append("Configurar GEMINI_API_KEY para validar el análisis con IA.")
        fallback["diagnostico_ia"] = diagnostics
        return fallback

    gemini_results: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        try:
            response = call_gemini(
                system_prompt=DOCUMENT_SYSTEM_PROMPT,
                user_prompt=_document_prompt(
                    kind=kind,
                    file_name=file_name,
                    chunk_text=chunk,
                    chunk_index=index,
                    total_chunks=len(chunks),
                    local_payload=_compact_payload(fallback),
                ),
                stage=f"{kind}_chunk_{index + 1}",
                max_output_tokens=8192,
                validate=_validate_json_response,
            )
            parsed = _normalize_model_payload(recover_partial_payload(response.text, fallback, expected_keys=FINAL_SCHEMA_KEYS))
            parsed.setdefault("archivo_fuente", file_name)
            parsed.setdefault("tipo_documento", kind)
            parsed.setdefault("alertas", [])
            parsed.setdefault("pendientes_revision", [])
            parsed["diagnostico_ia"] = {
                "modelo_usado": response.model,
                "fallback_activo": response.fallback_used,
                "response_ms": response.response_ms,
            }
            gemini_results.append(parsed)
            diagnostics["modelo_usado"] = diagnostics["modelo_usado"] or response.model
            diagnostics["fallback_activo"] = bool(diagnostics["fallback_activo"] or response.fallback_used)
            diagnostics["chunks_enviados"] += 1
            diagnostics["intentos"].extend(response.attempts)
        except GeminiClientError as exc:
            diagnostics["errores"].append({"chunk": index + 1, "error": str(exc), "attempts": exc.attempts})
            diagnostics["intentos"].extend(exc.attempts)
            logger.warning("Gemini falló para %s chunk %s/%s: %s", kind, index + 1, len(chunks), exc)
        except Exception as exc:  # pragma: no cover - defensive production guard
            diagnostics["errores"].append({"chunk": index + 1, "error": str(exc)})
            logger.exception("Error inesperado analizando %s chunk %s/%s", kind, index + 1, len(chunks))

    if not gemini_results:
        fallback["alertas"].append("Gemini no pudo analizar el documento; se usó fallback local inteligente.")
        fallback["pendientes_revision"].append("Revisar manualmente importes, vigencias y adicionales detectados localmente.")
        fallback["diagnostico_ia"] = diagnostics
        return fallback

    merged = _merge_document_results(gemini_results, fallback, kind=kind, file_name=file_name)
    merged["diagnostico_ia"] = diagnostics
    merged.setdefault("alertas", []).extend(extraction.alerts if extraction else [])
    if diagnostics["errores"]:
        merged.setdefault("alertas", []).append(
            f"Gemini no pudo procesar {len(diagnostics['errores'])} chunk(s); el JSON conserva los datos recuperados y fallback local."
        )
        merged.setdefault("pendientes_revision", []).append("Revisar fragmentos con error Gemini antes de publicar la calculadora.")
    return merged


def ensure_final_schema(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload or {})
    defaults: dict[str, Any] = {
        "version": "1.0",
        "archivo_fuente": "",
        "convenio": {},
        "parametros": {},
        "categorias": [],
        "escalas_salariales": [],
        "adicionales": [],
        "conceptos": [],
        "reglas_liquidacion": {},
        "matriz_tecnica": [],
        "pendientes_revision": [],
        "alertas": [],
        "nivel_confianza": 0,
    }
    for key, value in defaults.items():
        if result.get(key) in (None, ""):
            result[key] = deepcopy(value)
        else:
            result.setdefault(key, deepcopy(value))

    result["escalas_salariales"] = normalize_salary_scales(result, file_name=str(result.get("archivo_fuente") or ""))
    if not result["escalas_salariales"]:
        result["escalas_salariales"] = []

    try:
        confidence = float(result.get("nivel_confianza") or 0)
        if 0 < confidence <= 1:
            confidence *= 100
        result["nivel_confianza"] = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        result["nivel_confianza"] = 0

    return {key: result.get(key) for key in FINAL_SCHEMA_KEYS} | {
        key: value for key, value in result.items() if key not in FINAL_SCHEMA_KEYS
    }


def build_full_calculator_payload(cct_payload: dict[str, Any], scale_payload: dict[str, Any]) -> dict[str, Any]:
    """Fuse Gemini/local document payloads into calculator-ready technical JSON."""

    merged = merge_calculator_payload(cct_payload, scale_payload)
    merged.setdefault("alertas", [])
    merged.setdefault("pendientes_revision", [])
    merged.setdefault("diagnostico_ia", {})
    source_scales = [
        *[item for item in cct_payload.get("escalas_salariales", []) or [] if isinstance(item, dict)],
        *[item for item in scale_payload.get("escalas_salariales", []) or [] if isinstance(item, dict)],
        *[item for item in merged.get("escalas_salariales", []) or [] if isinstance(item, dict)],
    ]
    merged["escalas_salariales"] = normalize_salary_scales(
        {**merged, "escalas_salariales": source_scales},
        file_name=str(merged.get("archivo_fuente") or ""),
    )
    if not merged["escalas_salariales"]:
        merged["alertas"].append("No se detectaron escalas salariales completas en los documentos.")
        merged["pendientes_revision"].append("Completar o revisar escalas salariales antes de generar una calculadora final.")
    return ensure_final_schema(merged)
