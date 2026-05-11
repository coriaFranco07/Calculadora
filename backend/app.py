from __future__ import annotations

import io
import json
import os
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any
from fastapi.responses import FileResponse
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

from backend.html_generator import write_generated_calculator

from backend.gemini_proxy import (
    DEFAULT_MODEL,
    GeminiProxyError,
    build_cct_text_extraction_prompt,
    build_codex_json_structuring_prompt,
    build_prompt,
    call_gemini,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"

TEMPLATES_DIR = ROOT_DIR / "templates"



def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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


def parse_gemini_json(text: str) -> Any:
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

    return {"estado": "respuesta_no_json", "raw": text}


def normalize_calculator_payload(payload: Any, file_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "estado": "payload_invalido",
            "archivo_fuente": file_name,
            "convenio": {"nombre": "CCT cargado"},
            "parametros": {"divisor_mensual": 30, "horas_mensuales": None, "horas_semanales": None, "base_calculo": "simple"},
            "categorias": [],
            "adicionales": [],
            "reglas_liquidacion": {},
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
    payload.setdefault("adicionales", [])
    payload.setdefault("reglas_liquidacion", {})
    payload.setdefault("pendientes_revision", [])
    payload.setdefault("alertas", [])
    payload.setdefault("nivel_confianza", 0)

    if not isinstance(payload["convenio"], dict):
        payload["convenio"] = {"nombre": str(payload["convenio"])}
    if not isinstance(payload["parametros"], dict):
        payload["parametros"] = {}
    if not isinstance(payload["categorias"], list):
        payload["categorias"] = []
    if not isinstance(payload["adicionales"], list):
        payload["adicionales"] = []
    if not isinstance(payload["reglas_liquidacion"], dict):
        payload["reglas_liquidacion"] = {}
    if not isinstance(payload["pendientes_revision"], list):
        payload["pendientes_revision"] = [str(payload["pendientes_revision"])]
    if not isinstance(payload["alertas"], list):
        payload["alertas"] = [str(payload["alertas"])]

    return payload


def extract_string_field(raw_text: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"([^"]*)"', raw_text, re.S)
    if not match:
        return None
    return compact_text(match.group(1), 180) or None


def extract_number_field(raw_text: str, field: str) -> float | int | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*(null|-?\d+(?:\.\d+)?)', raw_text)
    if not match:
        return None
    return parse_numeric_token(match.group(1))


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
    payload = {
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
    return payload


def recover_partial_gemini_payload(raw_text: str, file_name: str) -> dict[str, Any] | None:
    raw = raw_text.strip()
    if not raw:
        return None

    categories: list[dict[str, Any]] = []
    category_pattern = re.compile(
        r'\{"id":"(?P<id>[^"]+)"\s*,\s*"nombre":"(?P<nombre>[^"]*)"\s*,\s*"tipo":"(?P<tipo>[^"]*)"\s*,\s*"descripcion":"(?P<descripcion>[^"]*)"\s*,\s*"valor_hora":(?P<valor_hora>null|-?\d+(?:\.\d+)?)\s*,\s*"sueldo_mensual":(?P<sueldo_mensual>null|-?\d+(?:\.\d+)?)\s*,\s*"fuente_textual":"(?P<fuente_textual>[^"]*)"',
        re.S,
    )
    for match in category_pattern.finditer(raw):
        categories.append(
            {
                "id": compact_text(match.group("id"), 48),
                "nombre": compact_text(match.group("nombre"), 120),
                "tipo": compact_text(match.group("tipo"), 40) or "otro",
                "descripcion": compact_text(match.group("descripcion"), 180),
                "valor_hora": parse_numeric_token(match.group("valor_hora")),
                "sueldo_mensual": parse_numeric_token(match.group("sueldo_mensual")),
                "fuente_textual": compact_text(match.group("fuente_textual"), 120),
            }
        )

    payload = {
        "estado": "json_recuperado_parcialmente",
        "archivo_fuente": file_name,
        "convenio": {
            "nombre": extract_string_field(raw, "nombre"),
            "actividad": extract_string_field(raw, "actividad"),
            "ambito": extract_string_field(raw, "ambito"),
            "cct_numero": extract_string_field(raw, "cct_numero") or detect_cct_number(raw),
            "vigencia_detectada": extract_string_field(raw, "vigencia_detectada"),
        },
        "parametros": {
            "divisor_mensual": extract_number_field(raw, "divisor_mensual") or 30,
            "horas_mensuales": extract_number_field(raw, "horas_mensuales"),
            "horas_semanales": extract_number_field(raw, "horas_semanales"),
            "base_calculo": extract_string_field(raw, "base_calculo") or "simple",
        },
        "categorias": dedupe_records(categories, ("id", "nombre")),
        "adicionales": [],
        "reglas_liquidacion": {},
        "pendientes_revision": [],
        "alertas": [],
        "nivel_confianza": 0.45,
    }

    if any(has_meaningful_value(value) for value in payload["convenio"].values()) or payload["categorias"]:
        return payload
    return None


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

    primary_categories = primary.get("categorias") or []
    fallback_categories = fallback.get("categorias") or []
    merged["categorias"] = dedupe_records(primary_categories + fallback_categories, ("id", "nombre"))[:24]

    primary_additionals = primary.get("adicionales") or []
    fallback_additionals = fallback.get("adicionales") or []
    merged["adicionales"] = dedupe_records(primary_additionals + fallback_additionals, ("nombre", "fuente_textual"))[:24]

    merged["pendientes_revision"] = dedupe_strings(
        [*(fallback.get("pendientes_revision") or []), *(primary.get("pendientes_revision") or [])]
    )
    merged["alertas"] = dedupe_strings([*(fallback.get("alertas") or []), *(primary.get("alertas") or [])])

    return merged


def enrich_calculator_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_calculator_payload(payload, payload.get("archivo_fuente", "CCT.pdf"))

    parametros = payload.setdefault("parametros", {})
    parametros["divisor_mensual"] = int(parametros.get("divisor_mensual") or 30)
    parametros["base_calculo"] = compact_text(parametros.get("base_calculo") or "simple", 24) or "simple"

    concept_incidence = {"jubilacion": True, "obra_social": True, "sindicato": True}
    rules = payload.get("reglas_liquidacion") or {}

    concepts = [
        {
            "codigo": "101",
            "nombre": "Sueldo Basico Proporcional",
            "tipo": "remunerativo",
            "formula": "escala_categoria * dias_trabajados / divisor_mensual",
            "lsd": "001",
            "ganancias": "gravado",
            "incidencia": concept_incidence,
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
                "incidencia": concept_incidence,
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
                "incidencia": concept_incidence,
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
                "incidencia": concept_incidence,
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
                    "incidencia": concept_incidence,
                },
                {
                    "codigo": "131",
                    "nombre": "Horas extra 100%",
                    "tipo": "remunerativo",
                    "formula": "valor_hora * horas_100 * 2",
                    "lsd": "031",
                    "ganancias": "gravado",
                    "incidencia": concept_incidence,
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
            "valor_hora": parse_numeric_token(item.get("valor_hora")),
            "sueldo_mensual": parse_numeric_token(item.get("sueldo_mensual")),
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


def extract_text_from_pdf_bytes(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n\n".join(pages).strip()
    if len(text) < 80:
        raise HTTPException(
            status_code=422,
            detail="El PDF se pudo abrir, pero no contiene suficiente texto seleccionable. Probablemente es escaneado/imagen y requiere OCR.",
        )
    return text

def extract_cct_from_text(file_name: str, text: str) -> dict[str, Any]:
    local_fallback = build_local_cct_fallback(file_name, text)

    try:
        gemini_prompt = build_cct_text_extraction_prompt({"file_name": file_name, "text": text})
        gemini_text = call_gemini(gemini_prompt, os.getenv("GEMINI_MODEL", DEFAULT_MODEL))

        codex_prompt = build_codex_json_structuring_prompt({
            "file_name": file_name,
            "extracted_text": gemini_text,
        })
        codex_text = call_gemini(
            codex_prompt,
            os.getenv("CODEX_MODEL", os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
        )

        parsed_payload = parse_gemini_json(codex_text)

        if isinstance(parsed_payload, dict) and parsed_payload.get("estado") == "respuesta_no_json":
            recovered = recover_partial_gemini_payload(codex_text, file_name) or {}
            parsed_payload = recovered or parsed_payload

        normalized_payload = normalize_calculator_payload(parsed_payload, file_name)
        merged_payload = merge_payload(normalized_payload, local_fallback)
        enriched = enrich_calculator_payload(merged_payload)
        generated_html = write_generated_calculator(enriched, TEMPLATES_DIR)

        return {
            "mode": "gemini-codex-cct",
            "pipeline": {
                "lector": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
                "estructurador": os.getenv("CODEX_MODEL", os.getenv("GEMINI_MODEL", DEFAULT_MODEL)),
            },
            "text_length": len(text),
            "intermediate_text_length": len(gemini_text),
            "result": enriched,
            "generated": generated_html,
            "html_url": generated_html["html_url"],
            
        }

    except GeminiProxyError as exc:
        fallback = enrich_calculator_payload(local_fallback)
        fallback["estado"] = "fallback_local_sin_ia"
        fallback["alertas"] = dedupe_strings([
            *fallback.get("alertas", []),
            f"Gemini no estuvo disponible: {compact_text(exc, 180)}",
            "Se devolvio un borrador local para no frenar la revision inicial.",
        ])
        fallback["pendientes_revision"] = dedupe_strings([
            *fallback.get("pendientes_revision", []),
            "Revisar manualmente categorias, reglas y parametros porque se uso fallback local.",
        ])

        generated_html = write_generated_calculator(fallback, TEMPLATES_DIR)

        return {
            "mode": "fallback-cct",
            "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
            "text_length": len(text),
            "result": fallback,
            "generated": generated_html,
            "html_url": generated_html["html_url"],
            
        }
    
    
@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "ai_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        "env_file_loaded": ENV_FILE.exists(),
    }


@app.post("/audit")
def audit(payload: AuditRequest) -> dict[str, Any]:
    prompt = build_prompt(payload.model_dump())
    try:
        text = call_gemini(prompt, os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    except GeminiProxyError as exc:
        status_code = 503 if "API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {
        "mode": "gemini",
        "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        "text": text,
    }


@app.post("/extract-cct")
def extract_cct(payload: CctExtractionRequest) -> dict[str, Any]:
    return extract_cct_from_text(payload.file_name, payload.text)



@app.get("/portal-cct.html", include_in_schema=False)
def portal_cct_page():
    path = TEMPLATES_DIR / "portal-cct.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="portal-cct.html no encontrado en templates")
    return FileResponse(path)

@app.get("/ley-26844-empleadas-domesticas-mayo-2026.html", include_in_schema=False)
def ley_26844_page():
    path = TEMPLATES_DIR / "ley-26844-empleadas-domesticas-mayo-2026.html"

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="HTML no encontrado"
        )

    return FileResponse(path)


@app.get("/crear_calculadora.html", include_in_schema=False)
def crear_calculadora_page():
    path = TEMPLATES_DIR / "crear_calculadora.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="crear_calculadora.html no encontrado en templates")
    return FileResponse(path)


@app.post("/extract-cct-pdf")
async def extract_cct_pdf(
    file: UploadFile = File(...),
    salary_file: UploadFile | None = File(None),
):
    convenio_text = extract_text_from_pdf_bytes(await file.read())

    parts = [
        f"=== ARCHIVO DEL CONVENIO: {file.filename} ===\n{convenio_text}"
    ]

    if salary_file is not None:
        salary_text = extract_text_from_pdf_bytes(await salary_file.read())
        parts.append(
            f"=== ESCALAS SALARIALES: {salary_file.filename} ===\n{salary_text}"
        )

    combined_text = "\n\n".join(parts)
    combined_name = file.filename
    if salary_file is not None:
        combined_name = f"{file.filename} + {salary_file.filename}"

    return extract_cct_from_text(combined_name, combined_text)


app.mount(
    "/generated",
    StaticFiles(directory=str(TEMPLATES_DIR / "generated"), html=True),
    name="generated",
)

app.mount("/", StaticFiles(directory=str(ROOT_DIR), html=True), name="static")


