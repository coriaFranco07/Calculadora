from __future__ import annotations

import html
import json
import logging
import os
import re
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.calculator_builder import build_document_payload, build_full_calculator_payload, ensure_final_schema
from backend.gemini_proxy import DEFAULT_MODEL, GeminiClientError, call_gemini, gemini_enabled, gemini_status
from backend.pdf_extractor import extract_text_from_pdf_bytes as extract_pdf_document

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"
CALCULATORS_DIR = ROOT_DIR / "calculadoras"
DATA_DIR = ROOT_DIR / "data" / "calculadoras"
LEGACY_DATA_DIR = ROOT_DIR / "data" / "generated"

LOGGER = logging.getLogger(__name__)


def load_env_file(path: Path) -> None:
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


load_env_file(ROOT_DIR / ".env")
load_env_file(ENV_FILE)


class AuditRequest(BaseModel):
    periodo: str = ""
    resumen_totalizadores: dict[str, float] = Field(default_factory=dict)
    resumen_revista: dict[str, Any] = Field(default_factory=dict)
    errores_detectados: list[dict[str, Any]] = Field(default_factory=list)
    pregunta_usuario: str = ""
    contexto_documental: list[dict[str, Any]] = Field(default_factory=list)


class CctExtractionRequest(BaseModel):
    file_name: str = "CCT.pdf"
    text: str = ""


class CalculatorPageRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class MergeCalculatorRequest(BaseModel):
    cct_json: dict[str, Any] = Field(default_factory=dict)
    escala_json: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="Motor IA para Convenios y Calculadoras")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def normalize_text(value: Any) -> str:
    return (
        unicodedata.normalize("NFD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )


def compact_text(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].strip()


def slugify(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalize_text(value)).strip("_")[:48] or "categoria"


def calculator_slugify(value: str) -> str:
    cleaned = normalize_text(value)
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned[:70] or "calculadora"


def has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def parse_numeric_token(token: Any) -> float | int | None:
    if token in {None, "", "null"}:
        return None
    try:
        number = float(str(token).replace(",", "."))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def dedupe_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = compact_text(item, 240)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def dedupe_records(items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        fingerprint = "|".join(normalize_text(item.get(field)) for field in key_fields)
        if not fingerprint.strip("|") or fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(item)
    return result


def normalize_calculator_payload(payload: Any, file_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "estado": "payload_invalido",
            "archivo_fuente": file_name,
            "convenio": {"nombre": "CCT cargado"},
            "parametros": {"divisor_mensual": 30, "horas_mensuales": None, "horas_semanales": None, "base_calculo": "simple"},
            "categorias": [],
            "escalas_salariales": [],
            "adicionales": [],
            "conceptos": [],
            "reglas_liquidacion": {},
            "matriz_tecnica": [],
            "pendientes_revision": ["La IA no devolvio un objeto JSON util."],
            "alertas": [],
            "nivel_confianza": 0,
            "raw": payload,
        }

    payload.setdefault("archivo_fuente", file_name)
    payload.setdefault("estado", "json_calculadora_generado")
    payload.setdefault("convenio", {})
    payload.setdefault("parametros", {})
    payload.setdefault("categorias", [])
    payload.setdefault("escalas_salariales", [])
    payload.setdefault("adicionales", [])
    payload.setdefault("conceptos", [])
    payload.setdefault("reglas_liquidacion", {})
    payload.setdefault("matriz_tecnica", [])
    payload.setdefault("pendientes_revision", [])
    payload.setdefault("alertas", [])
    payload.setdefault("nivel_confianza", 0)

    if not isinstance(payload["convenio"], dict):
        payload["convenio"] = {"nombre": str(payload["convenio"])}
    if not isinstance(payload["parametros"], dict):
        payload["parametros"] = {}
    if not isinstance(payload["categorias"], list):
        payload["categorias"] = []
    if not isinstance(payload["escalas_salariales"], list):
        payload["escalas_salariales"] = []
    if not isinstance(payload["adicionales"], list):
        payload["adicionales"] = []
    if not isinstance(payload["conceptos"], list):
        payload["conceptos"] = []
    if not isinstance(payload["reglas_liquidacion"], dict):
        payload["reglas_liquidacion"] = {}
    if not isinstance(payload["matriz_tecnica"], list):
        payload["matriz_tecnica"] = []
    if not isinstance(payload["pendientes_revision"], list):
        payload["pendientes_revision"] = [str(payload["pendientes_revision"])]
    if not isinstance(payload["alertas"], list):
        payload["alertas"] = [str(payload["alertas"])]

    return payload


def guess_category_type(label: str) -> str:
    normalized = normalize_text(label)
    if any(term in normalized for term in ("administr", "emplead", "escribiente", "cajer")):
        return "administrativo"
    if any(term in normalized for term in ("hora", "jornal", "operario", "oficial", "medio oficial")):
        return "jornalizado"
    if any(term in normalized for term in ("mensual", "encargado", "jefe", "chofer")):
        return "mensualizado"
    return "otro"


def detect_cct_number(text: str) -> str | None:
    match = re.search(r"\b(?:cct|convenio colectivo)\s*(?:n[ro.\s]*)?(\d+\s*/\s*\d{2,4})", normalize_text(text))
    return match.group(1).replace(" ", "") if match else None


def detect_vigencia(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text)
    match = re.search(
        r"vigenc(?:ia|ias?).{0,30}?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}).{0,20}?(?:al|a|-)\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        normalized,
        re.I,
    )
    if match:
        return f"{match.group(1)} al {match.group(2)}"

    alt_match = re.search(
        r"desde\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}).{0,20}?hasta\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        normalized,
        re.I,
    )
    if alt_match:
        return f"{alt_match.group(1)} al {alt_match.group(2)}"
    return None


def detect_hours(text: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text)
    hours_month = re.search(r"(\d{2,3})\s*horas?\s*(?:mensuales|por mes|al mes)", normalized, re.I)
    hours_week = re.search(r"(\d{2})\s*horas?\s*(?:semanales|por semana)", normalized, re.I)
    divisor = re.search(r"divisor.{0,20}?(\d{2})", normalized, re.I)

    base_calculo = "simple"
    lowered = normalize_text(text)
    if "base compuesta" in lowered or "salario conformado" in lowered:
        base_calculo = "compuesta"
    elif "base integrada" in lowered:
        base_calculo = "integrada"

    return {
        "divisor_mensual": int(divisor.group(1)) if divisor else 30,
        "horas_mensuales": int(hours_month.group(1)) if hours_month else None,
        "horas_semanales": int(hours_week.group(1)) if hours_week else None,
        "base_calculo": base_calculo,
    }


def detect_activity(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text)
    match = re.search(r"(personal.{0,180}?dependiente.{0,180}?\.)", normalized, re.I)
    return compact_text(match.group(1), 180) if match else None


def detect_ambit(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text)
    match = re.search(r"(todo el territorio.{0,120}?\.)", normalized, re.I)
    return compact_text(match.group(1), 160) if match else None


def detect_convenio_name(text: str, file_name: str) -> str:
    lines = [compact_text(line, 160) for line in text.splitlines() if compact_text(line, 160)]
    for line in lines[:18]:
        lowered = normalize_text(line)
        if "convenio colectivo" in lowered or "cct " in lowered:
            return line
    cct_number = detect_cct_number(text)
    return compact_text(f"{Path(file_name).stem} ({cct_number})" if cct_number else Path(file_name).stem, 160)


def extract_local_categories(text: str, limit: int = 18) -> list[dict[str, Any]]:
    category_hints = (
        "categoria",
        "categorias",
        "operario",
        "oficial",
        "medio oficial",
        "administrativo",
        "administracion",
        "chofer",
        "cadete",
        "maestranza",
        "jefe",
        "encargado",
        "auxilio mecanico",
    )

    categories: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        if len(line) < 6:
            continue
        normalized = normalize_text(line)
        if not any(hint in normalized for hint in category_hints):
            continue

        cleaned = re.sub(r"^(art\.?|articulo)\s*\d+[:.) -]*", "", line, flags=re.I)
        cleaned = re.sub(r"^\d+[.) -]+", "", cleaned).strip(" -:\t")
        if len(cleaned) < 4:
            continue

        name, _, detail = cleaned.partition(":")
        candidate_name = compact_text(name or cleaned, 110)
        if len(candidate_name) < 4:
            candidate_name = compact_text(cleaned, 110)

        categories.append(
            {
                "id": slugify(candidate_name),
                "nombre": candidate_name,
                "tipo": guess_category_type(candidate_name),
                "descripcion": compact_text(detail or cleaned, 180),
                "valor_hora": None,
                "sueldo_mensual": None,
                "fuente_textual": compact_text(cleaned, 120),
            }
        )
        if len(categories) >= limit:
            break

    return dedupe_records(categories, ("id", "nombre"))


def build_additional_item(name: str, line: str, code: str) -> dict[str, Any]:
    percent_match = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", line)
    return {
        "nombre": name,
        "tipo": "porcentaje" if percent_match else "otro",
        "valor": parse_numeric_token(percent_match.group(1)) if percent_match else None,
        "base": None,
        "condicion": None,
        "codigo_sugerido": code,
        "lsd": None,
        "fuente_textual": compact_text(line, 120),
    }


def extract_local_additionals(text: str, limit: int = 18) -> list[dict[str, Any]]:
    keywords = {
        "antiguedad": ("Antiguedad", "102"),
        "presentismo": ("Presentismo", "103"),
        "zona": ("Zona desfavorable", "120"),
        "extra 50": ("Horas extra 50%", "130"),
        "extra 100": ("Horas extra 100%", "131"),
        "horas extra": ("Horas extra", "130"),
        "feriado": ("Recargo por feriado", "131"),
        "no remunerativ": ("No remunerativo", "900"),
        "viatico": ("Viatico", "140"),
    }

    additionals: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        normalized = normalize_text(line)
        if len(line) < 6:
            continue

        matched = None
        for keyword, descriptor in keywords.items():
            if keyword in normalized:
                matched = descriptor
                break

        if matched is None and "%" not in line:
            continue

        name, code = matched if matched else ("Adicional detectado", "150")
        additionals.append(build_additional_item(name, line, code))
        if len(additionals) >= limit:
            break

    return dedupe_records(additionals, ("nombre", "fuente_textual"))


def extract_local_rules(text: str) -> dict[str, Any]:
    normalized_lines = [compact_text(line, 220) for line in text.splitlines() if compact_text(line, 220)]

    def first_line(*keywords: str) -> str | None:
        for line in normalized_lines:
            lowered = normalize_text(line)
            if all(keyword in lowered for keyword in keywords):
                return line
        return None

    antiguedad_line = first_line("antiguedad")
    presentismo_line = first_line("presentismo")
    zona_line = first_line("zona")
    extra_line = first_line("hora", "extra") or first_line("horas", "extra")
    nr_line = first_line("no remunerativ")

    def rule_from_line(line: str | None) -> dict[str, Any] | None:
        if not line:
            return None
        percent_match = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", line)
        return {
            "tipo": "porcentaje" if percent_match else "otro",
            "valor": parse_numeric_token(percent_match.group(1)) if percent_match else None,
            "fuente_textual": compact_text(line, 140),
        }

    return {
        "antiguedad": rule_from_line(antiguedad_line),
        "presentismo": rule_from_line(presentismo_line),
        "zona_desfavorable": rule_from_line(zona_line),
        "horas_extra": rule_from_line(extra_line),
        "licencias": [],
        "no_remunerativos": [rule_from_line(nr_line)] if nr_line else [],
    }


def build_local_cct_fallback(file_name: str, text: str) -> dict[str, Any]:
    return {
        "version": os.getenv("CCT_EXTRACTION_VERSION", "local-fallback"),
        "archivo_fuente": file_name,
        "estado": "borrador_local",
        "convenio": {
            "nombre": detect_convenio_name(text, file_name),
            "actividad": detect_activity(text),
            "ambito": detect_ambit(text),
            "cct_numero": detect_cct_number(text),
            "vigencia_detectada": detect_vigencia(text),
        },
        "parametros": detect_hours(text),
        "categorias": extract_local_categories(text),
        "adicionales": extract_local_additionals(text),
        "reglas_liquidacion": extract_local_rules(text),
        "pendientes_revision": [
            "Validar escalas e importes exactos por categoria.",
            "Confirmar formulas y base de calculo antes de usar la calculadora.",
            "Revisar conceptos especiales, licencias y no remunerativos del convenio.",
        ],
        "alertas": [],
        "nivel_confianza": 0.35,
    }


def merge_payload(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(fallback)

    for top_level_key in ("version", "archivo_fuente", "estado", "nivel_confianza"):
        if has_meaningful_value(primary.get(top_level_key)):
            merged[top_level_key] = primary[top_level_key]

    for nested_key in ("convenio", "parametros"):
        merged.setdefault(nested_key, {})
        for item_key, item_value in (primary.get(nested_key) or {}).items():
            if has_meaningful_value(item_value):
                merged[nested_key][item_key] = item_value

    merged["reglas_liquidacion"] = {
        **(fallback.get("reglas_liquidacion") or {}),
        **{key: value for key, value in (primary.get("reglas_liquidacion") or {}).items() if has_meaningful_value(value)},
    }

    merged["categorias"] = dedupe_records((primary.get("categorias") or []) + (fallback.get("categorias") or []), ("id", "nombre"))[:24]
    merged["adicionales"] = dedupe_records((primary.get("adicionales") or []) + (fallback.get("adicionales") or []), ("nombre", "fuente_textual"))[:24]
    merged["pendientes_revision"] = dedupe_strings([*(fallback.get("pendientes_revision") or []), *(primary.get("pendientes_revision") or [])])
    merged["alertas"] = dedupe_strings([*(fallback.get("alertas") or []), *(primary.get("alertas") or [])])
    return merged


def enrich_calculator_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_calculator_payload(payload, payload.get("archivo_fuente", "CCT.pdf"))

    parametros = payload.setdefault("parametros", {})
    parametros["divisor_mensual"] = int(parametros.get("divisor_mensual") or 30)
    parametros["base_calculo"] = compact_text(parametros.get("base_calculo") or "simple", 24) or "simple"

    incidence = {"jubilacion": True, "obra_social": True, "sindicato": True}
    rules = payload.get("reglas_liquidacion") or {}

    concepts = [
        {
            "codigo": "101",
            "nombre": "Sueldo Basico Proporcional",
            "tipo": "remunerativo",
            "formula": "escala_categoria * dias_trabajados / divisor_mensual",
            "lsd": "001",
            "ganancias": "gravado",
            "incidencia": incidence,
        }
    ]

    if has_meaningful_value(rules.get("antiguedad")):
        concepts.append(
            {
                "codigo": "102",
                "nombre": "Antiguedad",
                "tipo": "remunerativo",
                "formula": "basico_proporcional * porcentaje_antiguedad",
                "lsd": "005",
                "ganancias": "gravado",
                "incidencia": incidence,
            }
        )

    if has_meaningful_value(rules.get("presentismo")):
        concepts.append(
            {
                "codigo": "103",
                "nombre": "Presentismo",
                "tipo": "remunerativo",
                "formula": "segun regla convencional confirmada",
                "lsd": "010",
                "ganancias": "gravado",
                "incidencia": incidence,
            }
        )

    if has_meaningful_value(rules.get("zona_desfavorable")):
        concepts.append(
            {
                "codigo": "120",
                "nombre": "Zona desfavorable",
                "tipo": "remunerativo",
                "formula": "base_convencional * porcentaje_zona",
                "lsd": "020",
                "ganancias": "gravado",
                "incidencia": incidence,
            }
        )

    if has_meaningful_value(rules.get("horas_extra")):
        concepts.extend(
            [
                {
                    "codigo": "130",
                    "nombre": "Horas extra 50%",
                    "tipo": "remunerativo",
                    "formula": "valor_hora * horas_50 * 1.5",
                    "lsd": "030",
                    "ganancias": "gravado",
                    "incidencia": incidence,
                },
                {
                    "codigo": "131",
                    "nombre": "Horas extra 100%",
                    "tipo": "remunerativo",
                    "formula": "valor_hora * horas_100 * 2",
                    "lsd": "031",
                    "ganancias": "gravado",
                    "incidencia": incidence,
                },
            ]
        )

    payload["conceptos"] = concepts
    payload["matriz_tecnica"] = [
        {
            "paso": index + 1,
            "codigo": concept["codigo"],
            "concepto": concept["nombre"],
            "formula": concept["formula"],
            "lsd": concept["lsd"],
            "ganancias": concept["ganancias"],
            "incidencia": "SI/SI/SI" if concept["incidencia"]["jubilacion"] else "NO/NO/NO",
        }
        for index, concept in enumerate(concepts)
    ]

    payload["categorias"] = [
        {
            "id": compact_text(item.get("id") or slugify(item.get("nombre")), 48),
            "nombre": compact_text(item.get("nombre"), 120),
            "tipo": compact_text(item.get("tipo") or guess_category_type(item.get("nombre")), 40) or "otro",
            "descripcion": compact_text(item.get("descripcion"), 180),
            "basico_mensual": parse_numeric_token(
                item.get("basico_mensual") or item.get("sueldo_mensual") or item.get("valor")
            ),
            "valor": parse_numeric_token(item.get("valor") or item.get("basico_mensual") or item.get("sueldo_mensual")),
            "valor_hora": parse_numeric_token(item.get("valor_hora")),
            "sueldo_mensual": parse_numeric_token(
                item.get("sueldo_mensual") or item.get("basico_mensual") or item.get("valor")
            ),
            "tipo_valor": compact_text(item.get("tipo_valor"), 24) or None,
            "grupo": compact_text(item.get("grupo"), 60) or None,
            "fuente_textual": compact_text(item.get("fuente_textual"), 120),
        }
        for item in payload.get("categorias", [])
        if has_meaningful_value(item.get("nombre"))
    ]
    payload["adicionales"] = [
        {
            "nombre": compact_text(item.get("nombre"), 120),
            "tipo": compact_text(item.get("tipo"), 32) or "otro",
            "valor": parse_numeric_token(item.get("valor")),
            "base": compact_text(item.get("base"), 100) or None,
            "condicion": compact_text(item.get("condicion"), 100) or None,
            "codigo_sugerido": compact_text(item.get("codigo_sugerido"), 12) or None,
            "lsd": compact_text(item.get("lsd"), 16) or None,
            "fuente_textual": compact_text(item.get("fuente_textual"), 120),
        }
        for item in payload.get("adicionales", [])
        if has_meaningful_value(item.get("nombre"))
    ]
    payload["pendientes_revision"] = dedupe_strings(payload.get("pendientes_revision") or [])
    payload["alertas"] = dedupe_strings(payload.get("alertas") or [])
    return payload


def build_audit_prompt(data: dict[str, Any]) -> str:
    return f"""
Revisá preventivamente esta liquidación laboral argentina.
Devolvé observaciones accionables, riesgos AFIP/LSD, inconsistencias y próximos pasos.
Si falta información, indicá qué dato pedir. No inventes normativa.

Datos:
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()


def extract_text_from_pdf_bytes(content: bytes, file_name: str = "documento.pdf") -> str:
    return extract_pdf_document(content, file_name=file_name).text


def finalize_calculator_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return ensure_final_schema(enrich_calculator_payload(payload))


def extract_cct_from_text(file_name: str, text: str) -> dict[str, Any]:
    merged = build_document_payload(
        extraction=None,
        text=text,
        kind="cct",
        file_name=file_name,
        provider="Texto plano + Gemini",
    )
    return {
        "mode": "gemini-cct",
        "model": (merged.get("diagnostico_ia") or {}).get("modelo_usado") or DEFAULT_MODEL,
        "text_length": len(text),
        "result": finalize_calculator_payload(merged),
        "diagnostics": merged.get("diagnostico_ia") or {},
    }


def run_ocr_pipeline(document_bytes: bytes, *, file_name: str, document_kind: str) -> dict[str, Any]:
    extraction = extract_pdf_document(document_bytes, file_name=file_name)
    merged = build_document_payload(
        extraction=extraction,
        text=extraction.text,
        kind=document_kind,
        file_name=file_name,
        provider="PDF local + Gemini",
    )
    return {
        "ok": True,
        "kind": document_kind,
        "source": "gemini-codex",
        "result": merged,
        "diagnostics": merged.get("diagnostico_ia") or {},
        "pdf": {
            "file_name": file_name,
            "page_count": extraction.page_count,
            "text_length": extraction.text_length,
            "chunks": len(extraction.chunks),
            "ocr_active": bool(extraction.metrics.get("ocr_active")),
            "tables_detected": extraction.metrics.get("tables_detected", 0),
            "tablas_detectadas": extraction.metrics.get("tablas_detectadas", 0),
            "montos_detectados": extraction.metrics.get("montos_detectados", 0),
            "extractors_used": extraction.metrics.get("extractors_used", []),
            "alerts": extraction.alerts,
        },
    }


def calculator_slug(payload: dict[str, Any]) -> str:
    convenio = payload.get("convenio") if isinstance(payload.get("convenio"), dict) else {}
    raw = convenio.get("cct_numero") or convenio.get("nombre") or payload.get("archivo_fuente") or "calculadora"
    base = calculator_slugify(str(raw))
    target = CALCULATORS_DIR / f"{base}.html"
    if not target.exists():
        return base
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}-{suffix}"


def calculator_html(payload: dict[str, Any], slug: str) -> str:
    convenio = payload.get("convenio") if isinstance(payload.get("convenio"), dict) else {}
    title = html.escape(str(convenio.get("nombre") or slug))
    payload_json = html.escape(json.dumps(payload, ensure_ascii=False), quote=False)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body{{margin:0;font-family:Aptos,Bahnschrift,"Trebuchet MS",sans-serif;background:#fff8ef;color:#1b2321}}
    header{{padding:28px;max-width:1180px;margin:auto}}
    a{{color:#1f6a52;font-weight:800}}
    .status{{max-width:1180px;margin:0 auto 16px;padding:12px 16px;border-radius:16px;background:#eef7f3;color:#1f6a52;font-weight:800}}
    main{{max-width:1180px;margin:auto;padding:0 20px 40px}}
  </style>
</head>
<body>
  <header>
    <a href="/">Volver al panel</a>
    <h1>{title}</h1>
    <p>Calculadora generada automaticamente desde JSON normalizado.</p>
  </header>
  <div class="status" data-generated-calculator-status>Cargando calculadora...</div>
  <main data-generated-calculator-root></main>
  <script type="application/json" id="calculator-payload">{payload_json}</script>
  <script type="module" src="/js/generated-calculator-page.js"></script>
</body>
</html>
"""


def builtin_calculators() -> list[dict[str, Any]]:
    return [
        {
            "slug": "cct-244-94-alimentacion",
            "url": "/Calculadora_CCT_244_94_Alimentacion.html",
            "nombre": "CCT 244/94 - Alimentacion",
            "actividad": "Industria de la alimentacion",
            "categorias": 26,
            "adicionales": 6,
            "creado_en": None,
            "estado": "Lista",
            "tipo": "Base",
            "resumen": "Motor principal con wizard, auditoria preventiva AFIP y capa Gemini opcional.",
            "deletable": False,
        }
    ]


def load_calculators() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEGACY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = builtin_calculators()
    seen_slugs: set[str] = set()
    for directory in (DATA_DIR, LEGACY_DATA_DIR):
        for path in sorted(directory.glob("*.json"), reverse=True):
            slug = path.stem
            if slug in seen_slugs:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            convenio = payload.get("convenio") if isinstance(payload.get("convenio"), dict) else {}
            items.append(
                {
                    "slug": slug,
                    "url": f"/calculadoras/{slug}.html",
                    "nombre": convenio.get("nombre") or slug,
                    "actividad": convenio.get("actividad") or "Calculadora generada desde JSON normalizado",
                    "categorias": len(payload.get("categorias") or []),
                    "adicionales": len(payload.get("adicionales") or []),
                    "creado_en": payload.get("creado_en"),
                    "estado": "Generada",
                    "tipo": "IA + OCR",
                    "resumen": "Calculadora publicada desde Gemini, parser inteligente y Codex.",
                    "deletable": True,
                }
            )
            seen_slugs.add(slug)
    return items


def build_dashboard_card(item: dict[str, Any]) -> str:
    delete_button = ""
    if item.get("deletable"):
        slug = html.escape(str(item.get("slug") or ""))
        name = html.escape(str(item.get("nombre") or slug))
        delete_button = (
            f'<button class="button danger" type="button" '
            f'data-delete-calculator="{slug}" '
            f'data-delete-name="{name}">Eliminar calculadora</button>'
        )

    return f"""
        <article class="card">
          <div class="card-top">
            <div class="badges">
              <span class="badge badge-ok">{html.escape(str(item.get('estado') or 'Lista'))}</span>
              <span class="badge badge-type">{html.escape(str(item.get('tipo') or 'Calculadora'))}</span>
            </div>
            <a class="ghost-link" href="{item['url']}" target="_blank" rel="noopener">Abrir en otra pestana</a>
          </div>
          <h3>{html.escape(str(item['nombre']))}</h3>
          <p>{html.escape(str(item.get('resumen') or item.get('actividad') or 'Calculadora disponible'))}</p>
          <div class="meta">
            <div><small>Actividad</small><strong>{html.escape(str(item.get('actividad') or 'Sin actividad cargada'))}</strong></div>
            <div><small>Categorias</small><strong>{item['categorias']}</strong></div>
            <div><small>Adicionales</small><strong>{item['adicionales']}</strong></div>
          </div>
          <div class="card-actions">
            <a class="button primary" href="{item['url']}">Abrir calculadora</a>
            {delete_button}
          </div>
        </article>
        """


def dashboard_html() -> str:
    calculators = load_calculators()
    total = len(calculators)
    generated = sum(1 for item in calculators if item.get("tipo") == "IA + OCR")
    categories = sum(int(item.get("categorias") or 0) for item in calculators)

    cards = "".join(build_dashboard_card(item) for item in calculators)

    return f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Calculadoras CCT</title>
    <style>
      :root {{
        --bg: #f4efe6;
        --surface: rgba(255,255,255,.82);
        --surface-strong: #fffdfa;
        --ink: #1b2321;
        --muted: #56635e;
        --line: rgba(27,35,33,.08);
        --brand: #1f6a52;
        --brand-2: #c35d27;
        --ok: #1f6a52;
        --ok-soft: rgba(31,106,82,.12);
        --warm-soft: rgba(195,93,39,.12);
        --shadow: 0 26px 70px rgba(34,27,19,.12);
      }}

      * {{ box-sizing: border-box; }}

      body {{
        margin: 0;
        min-height: 100vh;
        font-family: Aptos, Bahnschrift, "Trebuchet MS", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(circle at 10% 10%, rgba(195,93,39,.16), transparent 28%),
          radial-gradient(circle at 90% 18%, rgba(31,106,82,.16), transparent 24%),
          linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
      }}

      .shell {{
        width: min(1240px, calc(100% - 36px));
        margin: 0 auto;
        padding: 28px 0 48px;
      }}

      .hero {{
        display: grid;
        grid-template-columns: minmax(0, 1.6fr) minmax(280px, .9fr);
        gap: 22px;
        padding: 28px;
        border-radius: 30px;
        border: 1px solid var(--line);
        background:
          linear-gradient(135deg, rgba(31,106,82,.12), transparent 36%),
          linear-gradient(160deg, rgba(195,93,39,.12), transparent 48%),
          var(--surface);
        backdrop-filter: blur(14px);
        box-shadow: var(--shadow);
      }}

      .eyebrow {{
        margin: 0 0 10px;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: .14em;
        font-size: .74rem;
        font-weight: 900;
      }}

      h1 {{
        margin: 0;
        font-size: clamp(34px, 4vw, 56px);
        line-height: .96;
        letter-spacing: -.04em;
      }}

      .hero p {{
        margin: 14px 0 0;
        max-width: 720px;
        color: var(--muted);
        line-height: 1.58;
        font-size: 1rem;
      }}

      .hero-actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 22px;
      }}

      .button {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 46px;
        padding: 0 16px;
        border-radius: 16px;
        border: 1px solid var(--line);
        text-decoration: none;
        font-weight: 900;
        color: var(--ink);
        background: var(--surface-strong);
      }}

      .button.primary {{
        color: #fff;
        border-color: var(--brand);
        background: linear-gradient(135deg, var(--brand), #2a8666);
        box-shadow: 0 14px 30px rgba(31,106,82,.18);
      }}

      .button.danger {{
        color: #8b2e2e;
        border-color: rgba(139,46,46,.18);
        background: rgba(170, 58, 58, .08);
      }}

      .button[disabled] {{
        opacity: .56;
        cursor: not-allowed;
      }}

      .hero-side {{
        display: grid;
        gap: 12px;
      }}

      .hero-stat {{
        padding: 16px 18px;
        border-radius: 22px;
        border: 1px solid var(--line);
        background: rgba(255,255,255,.7);
      }}

      .hero-stat small {{
        display: block;
        color: var(--muted);
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: .08em;
      }}

      .hero-stat strong {{
        display: block;
        margin-top: 8px;
        font-size: 2rem;
        letter-spacing: -.04em;
      }}

      .section-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        margin: 26px 0 14px;
      }}

      .section-head h2 {{
        margin: 0;
        font-size: 1.3rem;
      }}

      .section-head p {{
        margin: 4px 0 0;
        color: var(--muted);
      }}

      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 18px;
      }}

      .card {{
        display: grid;
        gap: 16px;
        padding: 22px;
        border-radius: 24px;
        border: 1px solid var(--line);
        background: var(--surface-strong);
        box-shadow: 0 16px 40px rgba(27,35,33,.08);
      }}

      .card-top {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }}

      .badges {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}

      .badge {{
        display: inline-flex;
        align-items: center;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid transparent;
        font-size: .74rem;
        font-weight: 900;
        letter-spacing: .04em;
        text-transform: uppercase;
      }}

      .badge-ok {{
        color: var(--ok);
        background: var(--ok-soft);
        border-color: rgba(31,106,82,.2);
      }}

      .badge-type {{
        color: var(--brand-2);
        background: var(--warm-soft);
        border-color: rgba(195,93,39,.2);
      }}

      .ghost-link {{
        color: var(--muted);
        text-decoration: none;
        font-weight: 800;
        white-space: nowrap;
      }}

      .card h3 {{
        margin: 0;
        font-size: 1.55rem;
        letter-spacing: -.03em;
      }}

      .card p {{
        margin: 0;
        color: var(--muted);
        line-height: 1.58;
      }}

      .meta {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }}

      .meta div {{
        padding-top: 12px;
        border-top: 1px solid var(--line);
      }}

      .meta small {{
        display: block;
        color: var(--muted);
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: .06em;
        font-size: .72rem;
      }}

      .meta strong {{
        display: block;
        margin-top: 8px;
        font-size: .98rem;
        line-height: 1.42;
      }}

      .card-actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }}

      @media (max-width: 980px) {{
        .hero {{ grid-template-columns: 1fr; }}
      }}

      @media (max-width: 760px) {{
        .shell {{ width: min(100% - 20px, 1240px); }}
        .hero {{ padding: 22px; border-radius: 24px; }}
        .meta {{ grid-template-columns: 1fr; }}
        .card-top, .section-head {{ flex-direction: column; align-items: flex-start; }}
      }}
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <div>
          <p class="eyebrow">Hub de Calculadoras</p>
          <h1>Calculadoras laborales y CCT en un solo lugar</h1>
          <p>Administra tus calculadoras activas, abre los motores ya publicados y crea nuevas calculadoras desde JSON normalizado sin perder el foco del producto.</p>
          <div class="hero-actions">
            <a class="button primary" href="/constructor.html">Crear nueva calculadora</a>
            <a class="button" href="/Calculadora_CCT_244_94_Alimentacion.html">Abrir motor base</a>
          </div>
        </div>
        <div class="hero-side">
          <div class="hero-stat">
            <small>Total disponibles</small>
            <strong>{total}</strong>
          </div>
          <div class="hero-stat">
            <small>Generadas por IA</small>
            <strong>{generated}</strong>
          </div>
          <div class="hero-stat">
            <small>Categorias catalogadas</small>
            <strong>{categories}</strong>
          </div>
        </div>
      </section>

      <div class="section-head">
        <div>
          <h2>Lista de calculadoras</h2>
          <p>Portafolio actual de calculadoras listas para abrir o seguir expandiendo.</p>
        </div>
      </div>

      <section class="grid">
        {cards}
      </section>
    </main>
    <script>
      document.addEventListener("click", async (event) => {{
        const button = event.target.closest("[data-delete-calculator]");
        if (!button) return;

        const slug = button.getAttribute("data-delete-calculator");
        const name = button.getAttribute("data-delete-name") || slug;
        const confirmed = window.confirm(`Eliminar calculadora "${{name}}"? Esto borrara el HTML publicado y el JSON asociado.`);
        if (!confirmed) return;

        button.disabled = true;
        button.textContent = "Eliminando...";

        try {{
          const response = await fetch(`/delete-calculator/${{encodeURIComponent(slug)}}`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }}
          }});

          const payload = await response.json().catch(() => null);
          if (!response.ok) {{
            throw new Error(payload?.detail || `Error HTTP ${{response.status}}`);
          }}

          window.location.reload();
        }} catch (error) {{
          button.disabled = false;
          button.textContent = "Eliminar calculadora";
          window.alert(error?.message || "No pude eliminar la calculadora.");
        }}
      }});
    </script>
  </body>
</html>
"""


def write_dashboard() -> Path:
    path = ROOT_DIR / "index.html"
    path.write_text(dashboard_html(), encoding="utf-8")
    return path


def delete_generated_calculator(slug: str) -> list[str]:
    safe_slug = calculator_slugify(slug).replace("_", "-")
    if safe_slug != slug:
        raise HTTPException(status_code=400, detail="Slug de calculadora invalido.")

    builtin_slugs = {item["slug"] for item in builtin_calculators()}
    if slug in builtin_slugs:
        raise HTTPException(status_code=400, detail="La calculadora base no se puede eliminar desde el panel.")

    targets = [
        DATA_DIR / f"{slug}.json",
        LEGACY_DATA_DIR / f"{slug}.json",
        CALCULATORS_DIR / f"{slug}.html",
    ]

    removed: list[str] = []
    for path in targets:
        if path.exists():
            try:
                path.chmod(0o666)
            except OSError:
                pass
            try:
                path.unlink()
            except PermissionError as exc:
                raise HTTPException(status_code=500, detail=f"No pude eliminar {path.name}: permiso denegado.") from exc
            removed.append(str(path.relative_to(ROOT_DIR)))

    if not removed:
        raise HTTPException(status_code=404, detail="No encontre archivos asociados a esa calculadora.")

    write_dashboard()
    return removed


@app.get("/health")
def health() -> dict[str, Any]:
    status = gemini_status()
    return {
        "status": "ok",
        "ai_enabled": status["ai_enabled"],
        "model": status["model"],
        "fallback_models": status["fallback_models"],
        "env_file_loaded": ENV_FILE.exists(),
        "root_env_file_loaded": (ROOT_DIR / ".env").exists(),
        "gemini_enabled": status["gemini_enabled"],
        "api_key_source": status["api_key_source"],
        "api_base": status["api_base"],
    }


@app.get("/")
def dashboard() -> HTMLResponse:
    return HTMLResponse(dashboard_html())


@app.post("/audit")
def audit(payload: AuditRequest) -> dict[str, Any]:
    prompt = build_audit_prompt(payload.model_dump())
    try:
        result = call_gemini(
            system_prompt=(
                "Sos un auditor preventivo senior de payroll argentino, AFIP y Libro de Sueldos Digital. "
                "Responde breve, claro y accionable."
            ),
            user_prompt=prompt,
            model=os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_DEFAULT_MODEL", DEFAULT_MODEL),
            temperature=0.1,
            max_output_tokens=4096,
            stage="audit",
            response_mime_type="text/plain",
        )
        text = result.text
    except GeminiClientError as exc:
        status_code = 503 if "API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {
        "mode": "gemini",
        "model": result.model,
        "text": text,
        "usage": result.usage,
        "response_ms": result.response_ms,
        "fallback_used": result.fallback_used,
        "attempts": result.attempts,
    }


@app.post("/extract-cct")
def extract_cct(payload: CctExtractionRequest) -> dict[str, Any]:
    return extract_cct_from_text(payload.file_name, payload.text)


@app.post("/extract-cct-pdf")
async def extract_cct_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="No se recibio contenido para el CCT.")
    return run_ocr_pipeline(content, file_name=file.filename or "cct.pdf", document_kind="cct")


@app.post("/extract-escala-pdf")
async def extract_escala_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="No se recibio contenido para la escala salarial.")
    return run_ocr_pipeline(content, file_name=file.filename or "escala.pdf", document_kind="scale")


@app.post("/upload-cct")
async def upload_cct(file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="No se recibio contenido para el CCT.")
    return run_ocr_pipeline(content, file_name=file.filename or "cct.pdf", document_kind="cct")


@app.post("/upload-scale")
async def upload_scale(file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="No se recibio contenido para la escala salarial.")
    return run_ocr_pipeline(content, file_name=file.filename or "escala.pdf", document_kind="scale")


@app.post("/extract-full-calculator")
async def extract_full_calculator(
    cct_file: UploadFile = File(...),
    escala_file: UploadFile = File(...),
) -> dict[str, Any]:
    if not (cct_file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El CCT debe ser un PDF.")
    if not (escala_file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="La escala salarial debe ser un PDF.")

    cct_content = await cct_file.read()
    escala_content = await escala_file.read()
    if not cct_content or not escala_content:
        raise HTTPException(status_code=400, detail="Se deben recibir ambos PDFs.")

    cct_response = run_ocr_pipeline(cct_content, file_name=cct_file.filename or "cct.pdf", document_kind="cct")
    scale_response = run_ocr_pipeline(escala_content, file_name=escala_file.filename or "escala.pdf", document_kind="scale")
    payload = build_full_calculator_payload(cct_response["result"], scale_response["result"])
    enriched = finalize_calculator_payload(payload)
    return {
        "ok": True,
        "source": "gemini-codex",
        "result": enriched,
        "documents": {
            "cct": cct_response,
            "escala": scale_response,
        },
        "diagnostics": {
            "modelo_cct": (cct_response.get("diagnostics") or {}).get("modelo_usado"),
            "modelo_escala": (scale_response.get("diagnostics") or {}).get("modelo_usado"),
            "modelo_usado": ((scale_response.get("diagnostics") or {}).get("modelo_usado") or (cct_response.get("diagnostics") or {}).get("modelo_usado")),
            "fallback_cct": (cct_response.get("diagnostics") or {}).get("fallback_activo"),
            "fallback_escala": (scale_response.get("diagnostics") or {}).get("fallback_activo"),
            "fallback_activo": bool((cct_response.get("diagnostics") or {}).get("fallback_activo") or (scale_response.get("diagnostics") or {}).get("fallback_activo")),
            "chunks_cct": ((cct_response.get("pdf") or {}).get("chunks")),
            "chunks_escala": ((scale_response.get("pdf") or {}).get("chunks")),
            "chunks_enviados": ((cct_response.get("diagnostics") or {}).get("chunks_enviados") or 0) + ((scale_response.get("diagnostics") or {}).get("chunks_enviados") or 0),
            "ocr_activo": bool(((cct_response.get("pdf") or {}).get("ocr_active")) or ((scale_response.get("pdf") or {}).get("ocr_active"))),
            "tablas_detectadas": ((cct_response.get("pdf") or {}).get("tablas_detectadas") or 0) + ((scale_response.get("pdf") or {}).get("tablas_detectadas") or 0),
            "montos_detectados": ((cct_response.get("pdf") or {}).get("montos_detectados") or 0) + ((scale_response.get("pdf") or {}).get("montos_detectados") or 0),
            "categorias_validas": (enriched.get("metricas") or {}).get("categorias_validas"),
            "escalas_validas": (enriched.get("metricas") or {}).get("escalas_validas"),
            "tiempo_respuesta_gemini": ((cct_response.get("diagnostics") or {}).get("tiempo_respuesta_gemini") or 0) + ((scale_response.get("diagnostics") or {}).get("tiempo_respuesta_gemini") or 0),
            "alertas": enriched.get("alertas") or [],
            "pendientes_revision": enriched.get("pendientes_revision") or [],
        },
    }


@app.post("/merge-calculator-payload")
def merge_calculator(request: MergeCalculatorRequest) -> dict[str, Any]:
    payload = build_full_calculator_payload(request.cct_json, request.escala_json)
    enriched = finalize_calculator_payload(payload)
    return {
        "ok": True,
        "result": enriched,
    }


@app.get("/calculadoras-list")
def calculators_list() -> dict[str, Any]:
    return {"items": load_calculators()}


@app.post("/create-calculator-page")
def create_calculator_page(request: CalculatorPageRequest) -> dict[str, Any]:
    CALCULATORS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    payload = normalize_calculator_payload(request.payload, str(request.payload.get("archivo_fuente") or "ocr.json"))
    payload = enrich_calculator_payload(payload)
    slug = calculator_slug(payload)
    payload["slug"] = slug
    payload["creado_en"] = datetime.now().isoformat(timespec="seconds")

    json_path = DATA_DIR / f"{slug}.json"
    html_path = CALCULATORS_DIR / f"{slug}.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(calculator_html(payload, slug), encoding="utf-8")
    write_dashboard()

    return {
        "ok": True,
        "slug": slug,
        "url": f"/calculadoras/{slug}.html",
        "dashboard_url": "/",
    }


@app.post("/delete-calculator/{slug}")
def delete_calculator_page(slug: str) -> dict[str, Any]:
    removed = delete_generated_calculator(slug)
    return {
        "ok": True,
        "slug": slug,
        "removed": removed,
    }


@app.get("/constructor.html")
def constructor_page() -> FileResponse:
    path = ROOT_DIR / "constructor.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No existe constructor.html")
    return FileResponse(path)


app.mount("/", StaticFiles(directory=str(ROOT_DIR), html=True), name="static")
