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


class CalculatorChatRequest(BaseModel):
    question: str = ""
    calculator: dict[str, Any] = Field(default_factory=dict)
    page: str = ""
    history: list[dict[str, str]] = Field(default_factory=list)


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

    cleaned = str(token).strip()
    if not cleaned:
        return None

    cleaned = (
        cleaned.replace("$", "")
        .replace("ARS", "")
        .replace("%", "")
        .replace("\xa0", "")
        .replace(" ", "")
        .strip()
    )
    cleaned = re.sub(r"[^0-9,.\-]", "", cleaned)
    if not cleaned or cleaned in {"-", ".", ","}:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) > 2:
            cleaned = "".join(parts)
        elif len(parts[-1]) == 3 and len(parts[0]) <= 3:
            cleaned = "".join(parts)
        else:
            cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2 and all(len(part) == 3 for part in parts[1:]):
            cleaned = "".join(parts)
        elif len(parts) == 2 and len(parts[-1]) == 3 and len(parts[0]) <= 3:
            cleaned = "".join(parts)

    try:
        number = float(cleaned)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


MONEY_TOKEN_RE = re.compile(
    r"\$?\s*-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d{1,2})?"
)

MAX_REASONABLE_SALARY_AMOUNT = 50_000_000
MIN_REASONABLE_SALARY_AMOUNT = 1


def money_matches(line: str) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for match in MONEY_TOKEN_RE.finditer(line):
        token = match.group(0)
        compact = token.replace("$", "").replace(" ", "")
        digits = re.sub(r"\D", "", compact)
        next_char = line[match.end() : match.end() + 1]
        has_money_marker = "$" in token
        has_separator = "." in compact or "," in compact

        if next_char == "%" and not has_money_marker:
            continue
        if not has_money_marker and re.fullmatch(r"\d{1,2}\.\d{1,2}", compact):
            continue
        if not has_money_marker and not has_separator and 1900 <= int(digits or "0") <= 2099:
            continue
        if not has_money_marker and not has_separator and len(digits) < 4:
            continue
        matches.append(match)
    return matches


def extract_money_values(line: str) -> list[float | int]:
    values: list[float | int] = []
    for match in money_matches(line):
        value = parse_numeric_token(match.group(0))
        if value is not None:
            values.append(value)
    return values


def strip_money_tokens(line: str) -> str:
    matches = money_matches(line)
    if not matches:
        return compact_text(line, 220)

    parts: list[str] = []
    cursor = 0
    for match in matches:
        parts.append(line[cursor : match.start()])
        cursor = match.end()
    parts.append(line[cursor:])
    cleaned = "".join(parts)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([:;,.)\]])", r"\1", cleaned)
    return compact_text(cleaned.strip(" -:\t"), 220)


def is_money_only_line(line: str) -> bool:
    if not extract_money_values(line):
        return False
    rest = strip_money_tokens(line)
    rest = re.sub(r"\bA\b", "", rest)
    rest = re.sub(r"[$.,:\-()\[\]\s]", "", rest)
    return not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", rest)


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


def flatten_agreement_schema(payload: dict[str, Any], file_name: str) -> dict[str, Any]:
    data = payload.get("data")
    metadata = payload.get("metadata")
    if not isinstance(data, dict):
        return payload

    flattened = deepcopy(payload)
    identity = metadata.get("identity", {}) if isinstance(metadata, dict) else {}
    validity = metadata.get("validity", {}) if isinstance(metadata, dict) else {}
    ai_processing = metadata.get("ai_processing", {}) if isinstance(metadata, dict) else {}
    source = metadata.get("source", {}) if isinstance(metadata, dict) else {}
    agreement_rules = data.get("agreement_rules") if isinstance(data.get("agreement_rules"), dict) else {}
    salary_model = data.get("salary_model") if isinstance(data.get("salary_model"), dict) else {}

    flattened.setdefault("archivo_fuente", source.get("original_file_name") or file_name)
    current_convenio = flattened.get("convenio") if isinstance(flattened.get("convenio"), dict) else {}
    flattened["convenio"] = {
        **current_convenio,
        "nombre": identity.get("name") or identity.get("short_name") or current_convenio.get("nombre"),
        "actividad": identity.get("sector") or identity.get("subsector") or current_convenio.get("actividad"),
        "ambito": identity.get("jurisdiction") or current_convenio.get("ambito"),
        "cct_numero": identity.get("code") or current_convenio.get("cct_numero"),
        "vigencia_detectada": validity.get("valid_from") or current_convenio.get("vigencia_detectada"),
    }

    current_parametros = flattened.get("parametros") if isinstance(flattened.get("parametros"), dict) else {}
    flattened["parametros"] = {
        **current_parametros,
        "divisor_mensual": agreement_rules.get("monthly_divisor") or agreement_rules.get("divisor_mensual") or 30,
        "horas_mensuales": agreement_rules.get("monthly_hours"),
        "horas_semanales": agreement_rules.get("weekly_hours"),
    }

    categories: list[dict[str, Any]] = []
    scales: list[dict[str, Any]] = []
    for item in data.get("categories") or []:
        if not isinstance(item, dict):
            continue
        name = compact_text(item.get("name") or item.get("nombre"), 120)
        if not name:
            continue
        group = compact_text(item.get("group") or item.get("rama"), 120) or None
        category_id = compact_text(item.get("category_id") or item.get("id") or slugify(f"{group or ''} {name}"), 48)
        salary_scales = item.get("salary_scales") if isinstance(item.get("salary_scales"), list) else []
        normalized_scales: list[dict[str, Any]] = []
        for scale in salary_scales:
            if not isinstance(scale, dict):
                continue
            amount = parse_numeric_token(
                scale.get("base_salary")
                or scale.get("sueldo_mensual")
                or scale.get("amount")
                or scale.get("valor")
            )
            if amount is None:
                continue
            normalized_scales.append(
                {
                    "periodo": compact_text(scale.get("valid_from") or scale.get("period"), 40),
                    "valid_from": compact_text(scale.get("valid_from") or scale.get("period"), 40),
                    "base_salary": amount,
                    "sueldo_mensual": amount,
                    "currency": compact_text(scale.get("currency") or "ARS", 12),
                    "source_reference": compact_text(scale.get("source_reference") or scale.get("source"), 140),
                }
            )

        base_salary = parse_numeric_token(item.get("base_salary") or item.get("sueldo_mensual"))
        if base_salary is None and normalized_scales:
            base_salary = normalized_scales[-1]["base_salary"]

        category = {
            "id": category_id,
            "rama": group,
            "categoria": name,
            "nombre": f"{group} - {name}" if group and normalize_text(group) not in normalize_text(name) else name,
            "tipo": guess_category_type(f"{group or ''} {name}"),
            "descripcion": compact_text(item.get("description") or item.get("descripcion") or name, 180),
            "valor_hora": parse_numeric_token(item.get("hourly_rate") or item.get("valor_hora")),
            "basico_mensual": base_salary,
            "sueldo_mensual": base_salary,
            "basico": base_salary,
            "valor": base_salary,
            "tipo_valor": "mensual",
            "salary_scales": normalized_scales,
            "fuente_textual": compact_text(item.get("source_reference") or item.get("source") or name, 160),
        }
        categories.append(category)
        if base_salary is not None:
            scales.append(
                {
                    "id": category_id,
                    "rama": group,
                    "categoria": name,
                    "nombre": name,
                    "basico_mensual": base_salary,
                    "sueldo_mensual": base_salary,
                    "valor": base_salary,
                    "valor_hora": category["valor_hora"],
                    "columnas_detectadas": ["base_salary"],
                    "tipo_valor": "mensual",
                    "salary_scales": normalized_scales,
                    "fuente_textual": category["fuente_textual"],
                    "requiere_revision": False,
                }
            )

    if categories and not flattened.get("categorias"):
        flattened["categorias"] = categories
    if scales and not flattened.get("escalas_salariales"):
        flattened["escalas_salariales"] = scales

    additionals: list[dict[str, Any]] = []
    for bucket_name, bucket_type in (("remunerative_items", "remunerativo"), ("non_remunerative_items", "no_remunerativo")):
        for item in salary_model.get(bucket_name) or []:
            if not isinstance(item, dict):
                continue
            name = compact_text(item.get("name") or item.get("nombre") or item.get("concept"), 120)
            if not name:
                continue
            additionals.append(
                {
                    "nombre": name,
                    "tipo": compact_text(item.get("type") or bucket_type, 32),
                    "valor": parse_numeric_token(item.get("amount") or item.get("value") or item.get("valor")),
                    "base": compact_text(item.get("base"), 100) or None,
                    "condicion": compact_text(item.get("condition") or item.get("condicion"), 120) or None,
                    "codigo_sugerido": compact_text(item.get("code") or item.get("codigo_sugerido"), 12) or None,
                    "lsd": compact_text(item.get("lsd"), 16) or None,
                    "fuente_textual": compact_text(item.get("source_reference") or item.get("source") or name, 160),
                }
            )
    if additionals and not flattened.get("adicionales"):
        flattened["adicionales"] = additionals

    flattened["pendientes_revision"] = dedupe_strings(
        [
            *(flattened.get("pendientes_revision") or []),
            *(data.get("review_flags") or []),
            *(ai_processing.get("warnings") or []),
        ]
    )
    if ai_processing.get("confidence_score") is not None:
        flattened["nivel_confianza"] = ai_processing.get("confidence_score")

    return flattened


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
            "subsidios": [],
            "reglas_liquidacion": {},
            "pendientes_revision": ["La IA no devolvio un objeto JSON util."],
            "alertas": [],
            "diagnostico_ia": {},
            "nivel_confianza": 0,
            "raw": payload,
        }

    payload = flatten_agreement_schema(payload, file_name)
    payload.setdefault("archivo_fuente", file_name)
    payload.setdefault("estado", "json_calculadora_generado")
    payload.setdefault("convenio", {})
    payload.setdefault("parametros", {})
    payload.setdefault("categorias", [])
    payload.setdefault("escalas_salariales", [])
    payload.setdefault("adicionales", [])
    payload.setdefault("subsidios", [])
    payload.setdefault("reglas_liquidacion", {})
    payload.setdefault("pendientes_revision", [])
    payload.setdefault("alertas", [])
    payload.setdefault("diagnostico_ia", {})
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
    if not isinstance(payload["subsidios"], list):
        payload["subsidios"] = []
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


def is_salary_noise_line(line: str) -> bool:
    normalized = normalize_text(line)
    if not line or len(line) < 2:
        return True
    if "https://" in normalized or "http://" in normalized or "documento.errepar" in normalized:
        return True
    if re.search(r"^\d{1,2}/\d{1,2}/\d{2,4}", line):
        return True
    if re.search(r"\b\d+\s*/\s*\d+\b", line) and len(line) < 28:
        return True
    if normalized in {"categoria", "categorias", "concepto", "monto", "zona", "ano %"}:
        return True
    if "convenio colectivo" in normalized and len(line) > 60:
        return True
    return False


def is_salary_heading_line(line: str) -> bool:
    normalized = normalize_text(line)
    if "formara parte integrante" in normalized or "a todos sus efectos" in normalized:
        return False
    if normalized.startswith(("escala salarial", "escalas salariales")):
        return True
    if normalized.startswith("salarios basicos") and (
        len(normalized) < 90 or "correspondientes" in normalized or "mes de" in normalized
    ):
        return True
    if re.match(r"^\d+[.)]\s*salarios basicos", normalized):
        return True
    if normalized in {
        "rama y categoria",
        "categoria basico mensual articulo 11 multifuncionalidad",
        "por dia por mes",
        "remuneracion basica",
        "total remuneracion basica",
    }:
        return True
    if normalized.startswith("categoria basico mensual"):
        return True
    if "remuneracion basica" in normalized and len(normalized) < 120:
        return True
    if normalized.startswith("basico 1"):
        return True
    return False


def is_salary_stop_line(line: str) -> bool:
    normalized = normalize_text(line)
    stop_terms = (
        "subsidios - montos fijos",
        "subsidio casamiento",
        "concepto monto",
        "adicional por antiguedad",
        "gratificacion extraordinaria",
        "adicionales y beneficios",
        "asignacion vacacional",
        "coeficiente zonal",
        "articulo 7)",
        "homologacion",
        "retenciones",
        "obra social",
        "organismo de aplicacion",
    )
    return any(term in normalized for term in stop_terms)


def is_known_salary_branch(line: str) -> bool:
    normalized = normalize_text(line)
    branch_terms = (
        "auxilio mec",
        "auxilio mecanico",
        "playeros",
        "expendedores",
        "mecanico-aca",
        "cerrajero",
        "electricista",
        "chapista",
        "pintor",
        "canos de escape",
        "gomeros",
        "lavadores",
        "engrasadores",
        "administrativos",
        "expoaca",
        "maestranza",
        "choferes",
        "serenos",
        "operario multiple",
        "conductores",
        "personal operativo",
        "personal administrativo",
        "taller",
        "mantenimiento",
        "servicios auxiliares",
        "grupo \"i\"",
        "grupo \"ii\"",
        "grupo \"iii\"",
        "grupo \"iv\"",
        "grupo \"v\"",
    )
    return any(term in normalized for term in branch_terms)


def is_non_salary_scale_document(text: str) -> bool:
    normalized = normalize_text(text[:5000])
    if "tope indemnizatorio" not in normalized:
        return False
    salary_terms = ("escala salarial", "escalas salariales", "salarios basicos", "remuneracion basica")
    return not any(term in normalized for term in salary_terms)


def salary_values_are_reasonable(values: list[float | int]) -> bool:
    if not values:
        return False
    for value in values:
        numeric = parse_numeric_token(value)
        if numeric is None:
            return False
        if abs(float(numeric)) > MAX_REASONABLE_SALARY_AMOUNT:
            return False
    return any(abs(float(parse_numeric_token(value) or 0)) >= MIN_REASONABLE_SALARY_AMOUNT for value in values)


def looks_like_legal_prose(label: str) -> bool:
    normalized = normalize_text(label)
    prose_terms = (
        "debera",
        "deberan",
        "cuando",
        "asimismo",
        "conforme",
        "equivalente",
        "establecido",
        "previsto",
        "corresponda",
        "partir del",
        "durante el",
        "se abonara",
        "se aplicara",
        "podra",
        "cuenta",
        "banco",
        "ministerio",
        "homologacion",
        "trabajadores percibiran",
        "los trabajadores",
        "las empresas",
    )
    if any(term in normalized for term in prose_terms):
        return True
    words = re.findall(r"[a-záéíóúüñ]+", normalized)
    if len(words) > 11 and not has_category_term(label):
        return True
    return False


def is_probable_salary_label(label: str) -> bool:
    normalized = normalize_text(label)
    if not label or len(label) < 3:
        return False
    if len(label) > 120:
        return False
    if is_salary_heading_line(label) or is_salary_stop_line(label):
        return False
    rejected_terms = (
        "articulo",
        "art.",
        "bol.oficial",
        "jurisdiccion",
        "organismo",
        "pagina",
        "subsidio",
        "asignacion vacacional",
        "zona ",
        "zona 1",
        "zona 2",
        "zona 3",
        "base de calculo",
        "absorcion",
        "antiguedad",
        "expediente",
        "fojas",
        "decreto",
        "resolucion",
        "buenos aires",
        "texto s /r",
        "ley de negociacion",
        "convenio",
        "aplicacion",
        "periodo de vigencia",
        "condiciones generales",
        "cantidad de beneficiarios",
        "clausulas salariales",
        "actividad y categoria",
        "cct ",
        "ley ",
        "contrato de trabajo",
        "servicio de auxilio",
        "rotativos",
        "pesos ",
        "bateria",
        "rige de acuerdo",
        "contribucion solidaria",
        "cuota sindical",
        "comision interna",
        "suficientes que cubran",
        "septiembre",
        "horas del dia",
        "dia siguiente",
        "elementos de proteccion",
        "relacion laboral",
        "lugar de trabajo",
        "concepto de viatico",
        "por mes",
        "por dia",
    )
    if any(term in normalized for term in rejected_terms):
        return False
    if looks_like_legal_prose(label):
        return False
    if re.match(r"^\d+\s*°", label):
        return False
    if any(term in normalized for term in ("salario basico computo", "todas las categorias")):
        return False
    if re.search(r"^\d+[.) -]+", label):
        return False
    return bool(re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", label))


def has_category_term(label: str) -> bool:
    normalized = normalize_text(label)
    terms = (
        "oficial",
        "inicial",
        "administrativo",
        "maestranza",
        "categoria",
        "unica",
        "aprendiz",
        "operario",
        "operador",
        "chofer",
        "conductor",
        "sereno",
        "mecanico",
        "mec",
        "capataz",
        "analista",
        "auxiliar",
        "peon",
        "recibidor",
        "clasificador",
        "embalador",
        "recolector",
        "distribuidor",
        "ayudante",
        "encargado",
        "cajero",
        "jefe",
        "supervisor",
        "vendedor",
    )
    return any(term in normalized for term in terms)


def preprocess_salary_lines(text: str) -> list[str]:
    raw_lines = [compact_text(line, 240) for line in text.splitlines()]
    lines = [line for line in raw_lines if line and not is_salary_noise_line(line)]

    merged: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if (
            next_line
            and not extract_money_values(line)
            and not extract_money_values(next_line)
            and normalize_text(line).endswith(" de")
            and normalize_text(next_line) in {"combustibles", "servicios"}
        ):
            merged.append(compact_text(f"{line} {next_line}", 240))
            index += 2
            continue
        merged.append(line)
        index += 1
    return merged


def split_rama_categoria(label: str, current_rama: str | None) -> tuple[str | None, str]:
    cleaned = compact_text(label, 160).strip(" -:\t")
    if " - " in cleaned:
        left, right = cleaned.rsplit(" - ", 1)
        right_norm = normalize_text(right)
        if any(
            term in right_norm
            for term in (
                "oficial",
                "inicial",
                "administrativo",
                "categoria",
                "unica",
                "aprendiz",
                "especializado",
            )
        ):
            return compact_text(left, 120), compact_text(right, 120)
    return current_rama, cleaned


def normalize_salary_columns(columns: list[str] | None, values_count: int) -> list[str]:
    if columns:
        return columns[:values_count]
    defaults = ["basico_mensual", "adicional_1", "adicional_2", "adicional_3"]
    return defaults[:values_count]


def has_period_salary_columns(columns: list[str]) -> bool:
    normalized = " ".join(normalize_text(column) for column in columns)
    return bool(re.search(r"\b(?:ene|abr|may|jun|jul|ago|sep|oct|nov|dic)\b", normalized))


def build_salary_records(
    label: str,
    values: list[float | int],
    current_rama: str | None,
    source_line: str,
    columns: list[str] | None = None,
    source_rank: int = 50,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not salary_values_are_reasonable(values):
        return None

    label = strip_money_tokens(label)
    if not is_probable_salary_label(label):
        return None

    rama, categoria = split_rama_categoria(label, current_rama)
    if not is_probable_salary_label(categoria):
        return None

    column_names = normalize_salary_columns(columns, len(values))
    is_period_scale = has_period_salary_columns(column_names) and len(column_names) == len(values)
    monthly_index = next(
        (
            idx
            for idx, column_name in enumerate(column_names)
            if any(term in normalize_text(column_name) for term in ("mensual", "mes", "basico_mensual", "sueldo"))
        ),
        None,
    )
    hourly_index = next(
        (idx for idx, column_name in enumerate(column_names) if "hora" in normalize_text(column_name)),
        None,
    )
    daily_index = next(
        (idx for idx, column_name in enumerate(column_names) if "dia" in normalize_text(column_name) or "jornal" in normalize_text(column_name)),
        None,
    )
    basico_mensual = values[monthly_index] if monthly_index is not None and monthly_index < len(values) else values[0]
    sueldo_mensual = values[-1] if is_period_scale else basico_mensual
    valor_hora = values[hourly_index] if hourly_index is not None and hourly_index < len(values) else None
    valor_diario = values[daily_index] if daily_index is not None and daily_index < len(values) else None
    non_additional_indexes = {idx for idx in (monthly_index, hourly_index, daily_index) if idx is not None}
    additional_values = [value for idx, value in enumerate(values) if idx not in non_additional_indexes]
    display_name = f"{rama} - {categoria}" if rama and normalize_text(rama) not in normalize_text(categoria) else categoria
    record_id = slugify(f"{rama or ''} {categoria}")

    escala: dict[str, Any] = {
        "id": record_id,
        "rama": rama,
        "categoria": categoria,
        "nombre": categoria,
        "basico_mensual": basico_mensual,
        "sueldo_mensual": sueldo_mensual,
        "valor": sueldo_mensual,
        "valor_hora": valor_hora,
        "valor_diario": valor_diario,
        "adicional_1": additional_values[0] if len(additional_values) > 0 else None,
        "adicional_2": additional_values[1] if len(additional_values) > 1 else None,
        "adicional_3": additional_values[2] if len(additional_values) > 2 else None,
        "columnas_detectadas": column_names,
        "tipo_valor": "mensual",
        "fuente_textual": compact_text(source_line, 180),
        "requiere_revision": False,
        "_source_rank": source_rank,
    }

    for column_name, value in zip(column_names, values):
        normalized_column = normalize_text(column_name)
        if "articulo 11" in normalized_column or "art. 11" in normalized_column:
            escala["articulo_11"] = value
        if "multifuncionalidad" in normalized_column:
            escala["multifuncionalidad"] = value

    if is_period_scale:
        escala["salary_scales"] = [
            {
                "periodo": column_name,
                "valid_from": column_name,
                "base_salary": value,
                "sueldo_mensual": value,
                "currency": "ARS",
                "source_reference": compact_text(source_line, 160),
            }
            for column_name, value in zip(column_names, values)
        ]

    categoria_payload = {
        "id": record_id,
        "rama": rama,
        "categoria": categoria,
        "nombre": display_name,
        "tipo": guess_category_type(f"{rama or ''} {categoria}"),
        "descripcion": categoria,
        "valor_hora": valor_hora,
        "valor_diario": valor_diario,
        "basico_mensual": basico_mensual,
        "sueldo_mensual": sueldo_mensual,
        "basico": sueldo_mensual,
        "valor": sueldo_mensual,
        "tipo_valor": "mensual",
        "fuente_textual": compact_text(source_line, 160),
        "_source_rank": source_rank,
    }
    if escala.get("salary_scales"):
        categoria_payload["salary_scales"] = escala["salary_scales"]
    if escala.get("articulo_11") is not None:
        categoria_payload["articulo_11"] = escala["articulo_11"]
    if escala.get("multifuncionalidad") is not None:
        categoria_payload["multifuncionalidad"] = escala["multifuncionalidad"]

    return categoria_payload, escala


def detect_salary_columns_from_line(line: str) -> list[str] | None:
    normalized = normalize_text(line)
    if "por dia" in normalized and "por mes" in normalized:
        return ["valor_diario", "basico_mensual"]
    if "valor hora" in normalized or (re.search(r"\bpor\s+hora\b", normalized) and len(normalized) < 80):
        return ["valor_hora", "basico_mensual"] if "mensual" in normalized else ["valor_hora"]
    if "basico mensual" in normalized and "articulo 11" in normalized:
        return ["basico_mensual", "articulo_11", "multifuncionalidad"]
    if "remuneracion basica" in normalized and len(normalized) < 120:
        return ["basico_mensual", "adicional_1", "sueldo_mensual"]
    return None


def is_salary_table_context_line(line: str) -> bool:
    normalized = normalize_text(line)
    terms = (
        "anexo",
        "valores vigentes",
        "remuneracion basica",
        "salarios basicos",
        "escala salarial",
        "escalas salariales",
        "por dia por mes",
    )
    return any(term in normalized for term in terms)


def is_probable_stacked_category_line(line: str) -> bool:
    if extract_money_values(line) or is_salary_noise_line(line):
        return False
    cleaned = compact_text(line.strip(" -:\t"), 140)
    normalized = normalize_text(cleaned)
    if not cleaned or len(cleaned) > 95:
        return False
    if is_salary_heading_line(cleaned) or is_salary_stop_line(cleaned):
        return False
    if normalized in {"valores", "vigentes", "hasta el", "total", "basica", "adicional", "por trabajo", "en zona"}:
        return False
    if re.match(r"^[a-zñ]{1,2}\)\s+\S", normalized):
        return True
    if re.search(r"\b\d+(?:ra|da|ta|a)?\.?\s*categoria\b", normalized):
        return True
    if has_category_term(cleaned) and not looks_like_legal_prose(cleaned):
        return True
    return False


def compact_stacked_label(parts: list[str]) -> str:
    filtered: list[str] = []
    for part in parts[-7:]:
        cleaned = compact_text(part.strip(" -:\t"), 90)
        normalized = normalize_text(cleaned)
        if not cleaned:
            continue
        if is_salary_heading_line(cleaned):
            continue
        if normalized in {"percibiran", "por dia por mes", "valores", "vigentes", "hasta el"}:
            continue
        if looks_like_legal_prose(cleaned) and not re.match(r"^[a-zñ]{1,2}\)", normalized):
            continue
        filtered.append(cleaned)

    if not filtered:
        return ""

    anchor_index = 0
    for idx, part in enumerate(filtered):
        normalized = normalize_text(part)
        if re.match(r"^[a-zñ]{1,2}\)", normalized) or re.search(r"\bcategoria\b", normalized):
            anchor_index = idx
    label = " ".join(filtered[anchor_index:])
    label = re.sub(r"^[a-zñ]{1,2}\)\s*", "", label, flags=re.I)
    label = re.sub(r"\s{2,}", " ", label)
    return compact_text(label.strip(" -:\t"), 140)


def extract_stacked_salary_blocks(lines: list[str]) -> dict[str, list[dict[str, Any]]]:
    categorias: list[dict[str, Any]] = []
    escalas: list[dict[str, Any]] = []
    context_budget = 0
    current_rama: str | None = None
    current_columns: list[str] | None = None
    label_parts: list[str] = []

    index = 0
    while index < len(lines):
        line = lines[index]
        normalized = normalize_text(line)

        detected_columns = detect_salary_columns_from_line(line)
        if detected_columns:
            current_columns = detected_columns
            context_budget = max(context_budget, 35)
            index += 1
            continue

        if is_salary_table_context_line(line):
            context_budget = max(context_budget, 50)
            if is_known_salary_branch(line):
                current_rama = line
            index += 1
            continue

        if is_salary_stop_line(line):
            context_budget = 0
            label_parts = []
            index += 1
            continue

        if is_known_salary_branch(line) and not extract_money_values(line):
            current_rama = line
            context_budget = max(context_budget, 25)
            label_parts = []
            index += 1
            continue

        values = extract_money_values(line)
        if values and is_money_only_line(line) and context_budget > 0:
            block_values = list(values)
            source_parts = list(label_parts) + [line]
            index += 1
            while index < len(lines) and is_money_only_line(lines[index]) and len(block_values) < 4:
                next_values = extract_money_values(lines[index])
                if not salary_values_are_reasonable(next_values):
                    break
                block_values.extend(next_values)
                source_parts.append(lines[index])
                index += 1

            label = compact_stacked_label(label_parts)
            if label and salary_values_are_reasonable(block_values):
                columns = current_columns if current_columns and len(current_columns) <= len(block_values) else current_columns
                built = build_salary_records(label, block_values[:4], current_rama, " ".join(source_parts), columns, source_rank=35)
                if built:
                    category, scale = built
                    categorias.append(category)
                    escalas.append(scale)
                    context_budget = max(context_budget, 35)
            label_parts = []
            continue

        if context_budget > 0 and is_probable_stacked_category_line(line):
            if is_known_salary_branch(line) and not has_category_term(line):
                current_rama = line
                label_parts = []
            else:
                label_parts.append(line)
                label_parts = label_parts[-7:]
        elif context_budget > 0 and label_parts and not values:
            fragment = compact_text(line.strip(" -:\t"), 80)
            fragment_norm = normalize_text(fragment)
            if (
                fragment
                and len(fragment) <= 45
                and not is_salary_heading_line(fragment)
                and not is_salary_stop_line(fragment)
                and not looks_like_legal_prose(fragment)
                and fragment_norm not in {"percibiran", "por dia por mes", "valores", "vigentes", "hasta el"}
            ):
                label_parts.append(fragment)
                label_parts = label_parts[-7:]

        if context_budget > 0:
            context_budget -= 1
        index += 1

    return {
        "categorias": categorias,
        "escalas_salariales": escalas,
    }


def extract_generic_salary_lines(text: str) -> dict[str, Any]:
    if is_non_salary_scale_document(text):
        return {"categorias": [], "escalas_salariales": []}

    lines = preprocess_salary_lines(text)
    categorias: list[dict[str, Any]] = []
    escalas: list[dict[str, Any]] = []
    current_rama: str | None = None
    pending_label: str | None = None
    current_columns: list[str] | None = None
    period_columns: list[str] = []
    in_salary_context = False
    salary_context_budget = 0

    index = 0
    while index < len(lines):
        line = lines[index]
        normalized = normalize_text(line)

        detected_columns = detect_salary_columns_from_line(line)
        if detected_columns:
            current_columns = detected_columns
            in_salary_context = True
            salary_context_budget = max(salary_context_budget, 60)
            pending_label = None
            index += 1
            continue

        if normalized.startswith("basico") and re.search(r"\d", line) and not extract_money_values(line):
            period = re.sub(r"^\S+\s*", "", line).strip()
            if period:
                period_columns.append(compact_text(period, 40))
                current_columns = period_columns[-4:]
                in_salary_context = True
                salary_context_budget = max(salary_context_budget, 60)
            pending_label = None
            index += 1
            continue

        if is_salary_heading_line(line):
            if any(term in normalized for term in ("escala", "salarios basicos", "rama y categoria")):
                in_salary_context = True
                salary_context_budget = max(salary_context_budget, 80)
            current_rama = None
            pending_label = None
            index += 1
            continue

        if is_salary_stop_line(line):
            in_salary_context = False
            salary_context_budget = 0
            current_rama = None
            pending_label = None
            index += 1
            continue

        values = extract_money_values(line)
        if values and is_money_only_line(line):
            if pending_label and in_salary_context and salary_values_are_reasonable(values):
                block_values = list(values)
                source_parts = [pending_label, line]
                index += 1
                while index < len(lines) and is_money_only_line(lines[index]) and len(block_values) < 4:
                    next_values = extract_money_values(lines[index])
                    if not salary_values_are_reasonable(next_values):
                        break
                    block_values.extend(next_values)
                    source_parts.append(lines[index])
                    index += 1

                columns = current_columns if current_columns and len(current_columns) <= len(block_values) else None
                built = build_salary_records(
                    pending_label,
                    block_values[:4],
                    current_rama,
                    " ".join(source_parts),
                    columns,
                    source_rank=30,
                )
                if built:
                    category, scale = built
                    categorias.append(category)
                    escalas.append(scale)
                    salary_context_budget = max(salary_context_budget, 45)
                pending_label = None
                continue
            index += 1
            continue

        if values:
            if not salary_values_are_reasonable(values):
                pending_label = None
                index += 1
                continue
            if not in_salary_context and "$" not in line:
                label_preview = strip_money_tokens(line)
                first_value = parse_numeric_token(values[0]) or 0
                if not is_probable_salary_label(label_preview) or not has_category_term(label_preview) or first_value < 100:
                    pending_label = None
                    index += 1
                    continue
            if len(line) > 170 or ("%" in line and "$" not in line and not any("." in m.group(0) or "," in m.group(0) for m in money_matches(line))):
                pending_label = None
                index += 1
                continue

            label = strip_money_tokens(line)
            columns = current_columns if current_columns and len(current_columns) >= len(values) else None
            built = build_salary_records(label, values, current_rama, line, columns, source_rank=40)
            if built:
                category, scale = built
                categorias.append(category)
                escalas.append(scale)
                salary_context_budget = max(salary_context_budget, 45)
            pending_label = None
            index += 1
            continue

        if in_salary_context and is_probable_salary_label(line):
            pending_label = line
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if is_known_salary_branch(line) and not is_money_only_line(next_line):
                current_rama = line

        if in_salary_context:
            salary_context_budget -= 1
            if salary_context_budget <= 0:
                in_salary_context = False
                current_rama = None
                pending_label = None

        index += 1

    stacked = extract_stacked_salary_blocks(lines)
    return {
        "categorias": dedupe_salary_categories([*categorias, *(stacked.get("categorias") or [])]),
        "escalas_salariales": dedupe_salary_scales([*escalas, *(stacked.get("escalas_salariales") or [])]),
    }


def extract_smata_aca_salary_annex(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    if not (
        "anexo smata - aca" in normalized
        or ("cct 454/2006" in normalized and "smata" in normalized and ("aca" in normalized or "automovil club argentino" in normalized))
    ):
        return {"categorias": [], "escalas_salariales": []}

    start = normalized.find("anexo smata - aca")
    source = text[start:] if start >= 0 else text
    source_normalized = normalize_text(source)
    end_candidates = [
        pos
        for marker in ("subsidios - montos fijos", "articulo 7) adicional por antiguedad", "adicional por antiguedad")
        if (pos := source_normalized.find(marker)) > 0
    ]
    if end_candidates:
        source = source[: min(end_candidates)]

    extracted = extract_generic_salary_lines(source)
    for item in extracted["categorias"]:
        if item.get("articulo_11") is None and item.get("sueldo_mensual") is not None:
            matching = next(
                (
                    scale
                    for scale in extracted["escalas_salariales"]
                    if normalize_text(scale.get("rama")) == normalize_text(item.get("rama"))
                    and normalize_text(scale.get("categoria")) == normalize_text(item.get("categoria"))
                ),
                None,
            )
            if matching and matching.get("adicional_1") is not None:
                item["articulo_11"] = matching.get("adicional_1")
            if matching and matching.get("adicional_2") is not None:
                item["multifuncionalidad"] = matching.get("adicional_2")
        item["_source_rank"] = 10
    for item in extracted["escalas_salariales"]:
        if item.get("adicional_1") is not None and item.get("articulo_11") is None:
            item["articulo_11"] = item.get("adicional_1")
        if item.get("adicional_2") is not None and item.get("multifuncionalidad") is None:
            item["multifuncionalidad"] = item.get("adicional_2")
        if len(item.get("columnas_detectadas") or []) > 1:
            item["columnas_detectadas"] = ["basico_mensual", "articulo_11", "multifuncionalidad"][
                : len(item.get("columnas_detectadas") or [])
            ]
        item["_source_rank"] = 10
    return extracted


def dedupe_salary_categories(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in sorted(items, key=lambda row: int(row.get("_source_rank") or 99)):
        key = (
            normalize_text(item.get("rama")),
            normalize_text(item.get("categoria") or item.get("nombre")),
            str(parse_numeric_token(item.get("sueldo_mensual") or item.get("basico_mensual") or item.get("valor")) or ""),
        )
        if not key[1] or key in seen:
            continue
        seen.add(key)
        item.pop("_source_rank", None)
        result.append(item)
    return result


def dedupe_salary_scales(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in sorted(items, key=lambda row: int(row.get("_source_rank") or 99)):
        key = (
            normalize_text(item.get("rama")),
            normalize_text(item.get("categoria") or item.get("nombre")),
            str(parse_numeric_token(item.get("basico_mensual") or item.get("valor")) or ""),
        )
        if not key[1] or key in seen:
            continue
        seen.add(key)
        item.pop("_source_rank", None)
        result.append(item)
    return result


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


def canonical_subsidy_name(label: str) -> str:
    normalized = normalize_text(label)
    if "casamiento" in normalized and "nacimiento" in normalized:
        return "Casamiento / Nacimiento"
    if "casamiento" in normalized:
        return "Casamiento"
    if "nacimiento" in normalized:
        return "Nacimiento"
    if "fallecimiento" in normalized and ("hijos" in normalized or "conyuge" in normalized):
        return "Fallecimiento hijos/conyuge"
    if "fallecimiento" in normalized and ("padres" in normalized or "politicos" in normalized):
        return "Fallecimiento padres/padres politicos"
    if "fallecimiento" in normalized and "hermano" in normalized:
        return "Fallecimiento hermano"
    if "idiomas" in normalized or "extranjeros" in normalized:
        return "Idiomas extranjeros"
    if "conet" in normalized or "titulo" in normalized:
        return "Titulo habilitante CONET o similar"
    if "discapacitados" in normalized:
        return "Hijos discapacitados"
    if "caja" in normalized:
        return "Empleados de caja"
    if "asignacion vacacional" in normalized and "auxilio" in normalized:
        return "Asignacion vacacional Auxilio Mecanico"
    if "asignacion vacacional" in normalized:
        return "Asignacion vacacional restantes categorias"

    cleaned = re.sub(r"\[[^\]]*\]", " ", label)
    cleaned = re.sub(r"(?i)\bsubsidios?\s+(?:por|personal\s+que|personal\s+con)?\b", " ", cleaned)
    return compact_text(cleaned.strip(" -:/"), 120) or "Subsidio"


def build_subsidy_item(label: str, values: list[float | int], source: str) -> dict[str, Any] | None:
    if not values:
        return None
    name = canonical_subsidy_name(label)
    if not name:
        return None
    return {
        "nombre": name,
        "tipo": "monto_fijo",
        "valor": values[-1],
        "valores_detectados": values,
        "base": None,
        "condicion": None,
        "codigo_sugerido": "900",
        "lsd": None,
        "fuente_textual": compact_text(source, 180),
    }


def extract_subsidios(text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    starts = [
        pos
        for marker in ("subsidios - montos fijos", "subsidios y asignacion vacacional", "subsidio casamiento")
        if (pos := normalized.find(marker)) >= 0
    ]
    if not starts:
        return []

    source = text[min(starts) :]
    lines = preprocess_salary_lines(source)
    subsidies: list[dict[str, Any]] = []
    pending_label: str | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        line_norm = normalize_text(line)
        if index > 0 and any(term in line_norm for term in ("articulo 7", "adicional por antiguedad", "ano %")):
            break
        if line_norm.startswith("subsidios - montos fijos") or line_norm.startswith("subsidios y asignacion"):
            pending_label = None
            index += 1
            continue
        if line_norm in {"concepto", "monto"} or line_norm.startswith("1 ene") or line_norm.startswith("1 abr"):
            index += 1
            continue

        values = extract_money_values(line)
        if values and is_money_only_line(line) and pending_label:
            block_values = list(values)
            source_parts = [pending_label, line]
            index += 1
            while index < len(lines) and is_money_only_line(lines[index]):
                block_values.extend(extract_money_values(lines[index]))
                source_parts.append(lines[index])
                index += 1
            item = build_subsidy_item(pending_label, block_values, " ".join(source_parts))
            if item:
                subsidies.append(item)
            pending_label = None
            continue

        if values:
            label = strip_money_tokens(line)
            if pending_label:
                label = f"{pending_label} {label}"
                pending_label = None
            item = build_subsidy_item(label, values, line)
            if item:
                subsidies.append(item)
            index += 1
            continue

        if "subsid" in line_norm or "asignacion vacacional" in line_norm or pending_label:
            pending_label = compact_text(f"{pending_label or ''} {line}", 180)
        index += 1

    return dedupe_records(subsidies, ("nombre", "valor"))


def extract_antiguedad_rule(text: str) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    candidates: list[str] = []

    match = re.search(r"(adicional\s+por\s+antig[^\n]{0,160}(?:\n.{0,80}){0,80})", text, re.I)
    if match:
        candidates.append(match.group(1))

    scale_match = re.search(r"(antig[^\n]{0,120}?1\s*%\s+por\s+a[ñn]o[^\n]{0,180})", text, re.I)
    if scale_match:
        candidates.append(scale_match.group(1))

    if "antig" not in normalized:
        return None

    window = "\n".join(candidates) if candidates else text[:3000]
    normalized_window = normalize_text(window)
    base_match = re.search(
        r"(?:base\s+fija\s+de|salario\s+de\s+convenio\s+de)\s*\$?\s*([0-9][0-9.,]*)",
        normalized_window,
        re.I,
    )
    base_monto = parse_numeric_token(base_match.group(1)) if base_match else None

    percentage_match = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%\s+por\s+anio", normalized_window, re.I)
    porcentaje_por_anio = parse_numeric_token(percentage_match.group(1)) if percentage_match else 1

    escala: list[dict[str, Any]] = []
    for year, pct in re.findall(r"\b([1-9]|[12]\d|30)\s+([1-9]|[12]\d|30)\s*%", normalized_window):
        year_number = int(year)
        pct_number = parse_numeric_token(pct)
        if pct_number is None:
            continue
        escala.append({"anio": year_number, "porcentaje": pct_number})

    if not escala and porcentaje_por_anio:
        escala = [{"anio": year, "porcentaje": year * float(porcentaje_por_anio)} for year in range(1, 31)]

    if not base_monto and not escala:
        return None

    return {
        "tipo": "porcentaje_por_anio",
        "base_monto": base_monto,
        "porcentaje_por_anio": porcentaje_por_anio,
        "escala": escala[:30],
        "fuente_textual": compact_text(window, 180),
    }


def extract_zone_rule(text: str) -> dict[str, Any] | None:
    provinces = ["neuqu", "rio negro", "chubut", "santa cruz", "tierra del fuego"]
    pretty_provinces = ["Neuquén", "Río Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"]

    art56 = re.search(r"(art\.?\s*56[\s\S]{0,700})", text, re.I)
    zonal = re.search(r"(coeficiente\s+zonal[^\n]{0,220})", text, re.I)
    window = (art56.group(1) if art56 else "") or (zonal.group(1) if zonal else "")
    normalized_window = normalize_text(window)

    if not window:
        for line in text.splitlines():
            line_norm = normalize_text(line)
            if "zona" in line_norm and ("30%" in line or "treinta por ciento" in line_norm):
                window = line
                normalized_window = line_norm
                break

    if not window:
        return None

    percent_match = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", window)
    percentage = parse_numeric_token(percent_match.group(1)) if percent_match else None
    if percentage in (None, 0) and "treinta por ciento" in normalized_window:
        percentage = 30
    if percentage in (None, 0) and "30" in normalized_window and "zonal" in normalized_window:
        percentage = 30

    found_provinces = [
        pretty
        for raw, pretty in zip(provinces, pretty_provinces)
        if raw in normalized_window
    ]
    if percentage == 30 and ("art. 56" in normalize_text(window) or "art 56" in normalize_text(window)):
        found_provinces = pretty_provinces
    if not found_provinces and ("patagon" in normalized_window or percentage == 30):
        found_provinces = pretty_provinces

    if percentage in (None, 0):
        return None

    return {
        "tipo": "porcentaje",
        "valor": percentage,
        "porcentaje": percentage,
        "provincias": found_provinces,
        "fuente_textual": compact_text(window, 180),
    }


def extract_local_additionals(text: str, limit: int = 18) -> list[dict[str, Any]]:
    subsidies = extract_subsidios(text)

    keywords = {
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
        item = build_additional_item(name, line, code)
        if item.get("valor") is not None:
            additionals.append(item)
        if len(additionals) >= limit:
            break

    return dedupe_records([*subsidies, *additionals], ("nombre", "valor"))[:limit]


def extract_local_rules(text: str) -> dict[str, Any]:
    normalized_lines = [compact_text(line, 220) for line in text.splitlines() if compact_text(line, 220)]

    def first_line(*keywords: str) -> str | None:
        for line in normalized_lines:
            lowered = normalize_text(line)
            if all(keyword in lowered for keyword in keywords):
                return line
        return None

    antiguedad_rule = extract_antiguedad_rule(text)
    presentismo_line = first_line("presentismo")
    zona_rule = extract_zone_rule(text)
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

    presentismo_rule = rule_from_line(presentismo_line)
    if presentismo_line and any(term in normalize_text(presentismo_line) for term in ("comision", "evaluara", "contempl", "plazo")):
        presentismo_rule = None

    return {
        "antiguedad": antiguedad_rule,
        "presentismo": presentismo_rule,
        "zona_desfavorable": zona_rule,
        "horas_extra": rule_from_line(extra_line),
        "licencias": [],
        "no_remunerativos": [rule_from_line(nr_line)] if nr_line else [],
    }


def build_local_cct_fallback(file_name: str, text: str) -> dict[str, Any]:
    generic_salary = extract_generic_salary_lines(text)
    smata_salary = extract_smata_aca_salary_annex(text)
    salary_categories = dedupe_salary_categories(
        [*(smata_salary.get("categorias") or []), *(generic_salary.get("categorias") or [])]
    )
    salary_scales = dedupe_salary_scales(
        [*(smata_salary.get("escalas_salariales") or []), *(generic_salary.get("escalas_salariales") or [])]
    )
    fallback_categories = salary_categories or extract_local_categories(text)
    subsidies = extract_subsidios(text)

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
        "categorias": fallback_categories,
        "escalas_salariales": salary_scales,
        "adicionales": extract_local_additionals(text),
        "subsidios": subsidies,
        "reglas_liquidacion": extract_local_rules(text),
        "pendientes_revision": [
            "Validar escalas e importes exactos por categoria.",
            "Confirmar formulas y base de calculo antes de usar la calculadora.",
            "Revisar conceptos especiales, licencias y no remunerativos del convenio.",
        ],
        "alertas": [],
        "nivel_confianza": 0.75 if salary_categories else 0.35,
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


def salary_record_has_amount(item: dict[str, Any]) -> bool:
    return any(
        (parse_numeric_token(item.get(field)) or 0) > 0
        for field in ("sueldo_mensual", "basico_mensual", "valor_hora", "valor_diario", "valor", "basico")
    )


def salary_output_record_is_valid(item: dict[str, Any]) -> bool:
    label = compact_text(item.get("categoria") or item.get("nombre") or item.get("id"), 160)
    if not label:
        return False
    normalized = normalize_text(label)
    if normalized in {"por mes", "por dia", "por dia por mes", "a a"}:
        return False
    if any(noise in normalized for noise in ("https", "bol.oficial", "jurisdiccion", "organismo")):
        return False
    rama = compact_text(item.get("rama"), 160)
    if rama and looks_like_legal_prose(rama):
        return False
    if rama and len(rama) > 60 and re.match(r"^[a-zñ0-9]{1,2}\)", normalize_text(rama)):
        return False
    amount_values = [
        parse_numeric_token(item.get(field))
        for field in ("sueldo_mensual", "basico_mensual", "valor_hora", "valor_diario", "valor", "basico")
    ]
    amount_values = [value for value in amount_values if value is not None]
    if amount_values and not salary_values_are_reasonable(amount_values):
        return False
    if amount_values and looks_like_legal_prose(label):
        return False
    words = re.findall(r"[a-záéíóúüñ]+", normalized)
    if amount_values and len(words) <= 2 and not has_category_term(label):
        return False
    if amount_values and not (has_category_term(label) or is_probable_salary_label(label)):
        return False
    return True


def rule_percentage(rule: Any) -> float:
    if not isinstance(rule, dict):
        return 0
    value = parse_numeric_token(rule.get("porcentaje") or rule.get("valor"))
    return float(value or 0)


def merge_rules(primary_rules: dict[str, Any], fallback_rules: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(fallback_rules or {})
    for key, value in (primary_rules or {}).items():
        if not has_meaningful_value(value):
            continue
        if key == "zona_desfavorable" and rule_percentage(merged.get(key)) > rule_percentage(value):
            continue
        if key == "antiguedad" and isinstance(merged.get(key), dict):
            fallback_scale = merged[key].get("escala") or []
            primary_scale = value.get("escala") if isinstance(value, dict) else []
            if fallback_scale and not primary_scale:
                continue
        merged[key] = value
    return merged


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

    merged["reglas_liquidacion"] = merge_rules(primary.get("reglas_liquidacion") or {}, fallback.get("reglas_liquidacion") or {})

    primary_categories = primary.get("categorias") or []
    fallback_categories = fallback.get("categorias") or []
    category_candidates = sorted(
        [*primary_categories, *fallback_categories],
        key=lambda item: 0 if isinstance(item, dict) and salary_record_has_amount(item) else 1,
    )
    merged["categorias"] = dedupe_salary_categories([item for item in category_candidates if isinstance(item, dict)])[:120]
    merged["categorias"] = [item for item in merged["categorias"] if salary_output_record_is_valid(item)]

    primary_scales = primary.get("escalas_salariales") or []
    fallback_scales = fallback.get("escalas_salariales") or []
    merged["escalas_salariales"] = dedupe_salary_scales(
        [item for item in [*primary_scales, *fallback_scales] if isinstance(item, dict)]
    )[:120]
    merged["escalas_salariales"] = [item for item in merged["escalas_salariales"] if salary_output_record_is_valid(item)]

    primary_additionals = primary.get("adicionales") or []
    fallback_additionals = fallback.get("adicionales") or []
    merged["adicionales"] = dedupe_records(primary_additionals + fallback_additionals, ("nombre", "valor"))[:80]

    primary_subsidies = primary.get("subsidios") or []
    fallback_subsidies = fallback.get("subsidios") or []
    merged["subsidios"] = dedupe_records(primary_subsidies + fallback_subsidies, ("nombre", "valor"))[:80]

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
            "rama": compact_text(item.get("rama"), 120) or None,
            "categoria": compact_text(item.get("categoria") or item.get("nombre"), 120),
            "tipo": compact_text(item.get("tipo") or guess_category_type(item.get("nombre")), 40) or "otro",
            "descripcion": compact_text(item.get("descripcion"), 180),
            "valor_hora": parse_numeric_token(item.get("valor_hora")),
            "valor_diario": parse_numeric_token(item.get("valor_diario")),
            "basico_mensual": parse_numeric_token(item.get("basico_mensual") or item.get("base_salary") or item.get("basico")),
            "sueldo_mensual": parse_numeric_token(
                item.get("sueldo_mensual")
                or item.get("base_salary")
                or item.get("basico_mensual")
                or item.get("basico")
                or item.get("valor")
            ),
            "basico": parse_numeric_token(item.get("basico") or item.get("sueldo_mensual") or item.get("basico_mensual")),
            "valor": parse_numeric_token(item.get("valor") or item.get("sueldo_mensual") or item.get("basico_mensual")),
            "tipo_valor": compact_text(item.get("tipo_valor") or "mensual", 24),
            "articulo_11": parse_numeric_token(item.get("articulo_11")),
            "multifuncionalidad": parse_numeric_token(item.get("multifuncionalidad")),
            "salary_scales": item.get("salary_scales") if isinstance(item.get("salary_scales"), list) else [],
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
        if has_meaningful_value(item.get("nombre")) and (parse_numeric_token(item.get("valor")) is not None or has_meaningful_value(item.get("base")))
    ]
    payload["subsidios"] = [
        {
            "nombre": compact_text(item.get("nombre"), 120),
            "tipo": compact_text(item.get("tipo") or "monto_fijo", 32),
            "valor": parse_numeric_token(item.get("valor")),
            "valores_detectados": item.get("valores_detectados") if isinstance(item.get("valores_detectados"), list) else [],
            "fuente_textual": compact_text(item.get("fuente_textual"), 160),
        }
        for item in payload.get("subsidios", [])
        if has_meaningful_value(item.get("nombre")) and parse_numeric_token(item.get("valor")) is not None
    ]
    payload["escalas_salariales"] = [
        {
            "id": compact_text(item.get("id") or slugify(item.get("categoria") or item.get("nombre")), 48),
            "rama": compact_text(item.get("rama"), 120) or None,
            "categoria": compact_text(item.get("categoria") or item.get("nombre"), 120),
            "nombre": compact_text(item.get("nombre") or item.get("categoria"), 120),
            "basico_mensual": parse_numeric_token(item.get("basico_mensual") or item.get("base_salary")),
            "sueldo_mensual": parse_numeric_token(item.get("sueldo_mensual") or item.get("valor") or item.get("basico_mensual")),
            "valor": parse_numeric_token(item.get("valor") or item.get("sueldo_mensual") or item.get("basico_mensual")),
            "valor_hora": parse_numeric_token(item.get("valor_hora")),
            "valor_diario": parse_numeric_token(item.get("valor_diario")),
            "adicional_1": parse_numeric_token(item.get("adicional_1")),
            "adicional_2": parse_numeric_token(item.get("adicional_2")),
            "adicional_3": parse_numeric_token(item.get("adicional_3")),
            "articulo_11": parse_numeric_token(item.get("articulo_11")),
            "multifuncionalidad": parse_numeric_token(item.get("multifuncionalidad")),
            "columnas_detectadas": item.get("columnas_detectadas") if isinstance(item.get("columnas_detectadas"), list) else [],
            "salary_scales": item.get("salary_scales") if isinstance(item.get("salary_scales"), list) else [],
            "tipo_valor": compact_text(item.get("tipo_valor") or "mensual", 24),
            "fuente_textual": compact_text(item.get("fuente_textual"), 180),
            "requiere_revision": bool(item.get("requiere_revision", False)),
        }
        for item in payload.get("escalas_salariales", [])
        if has_meaningful_value(item.get("categoria") or item.get("nombre"))
    ]
    payload["pendientes_revision"] = dedupe_strings(payload.get("pendientes_revision") or [])
    payload["alertas"] = dedupe_strings(payload.get("alertas") or [])
    return clean_final_payload(payload)


def clean_final_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("categorias", [])
    payload.setdefault("escalas_salariales", [])
    payload.setdefault("adicionales", [])
    payload.setdefault("subsidios", [])
    payload.setdefault("reglas_liquidacion", {})
    payload.setdefault("pendientes_revision", [])
    payload.setdefault("alertas", [])

    payload["categorias"] = [
        item
        for item in dedupe_salary_categories([item for item in payload.get("categorias", []) if isinstance(item, dict)])
        if salary_output_record_is_valid(item)
    ]
    payload["escalas_salariales"] = dedupe_salary_scales(
        [item for item in payload.get("escalas_salariales", []) if isinstance(item, dict)]
    )
    payload["escalas_salariales"] = [
        item for item in payload["escalas_salariales"] if salary_output_record_is_valid(item)
    ]
    payload["subsidios"] = dedupe_records(
        [
            item
            for item in payload.get("subsidios", [])
            if isinstance(item, dict) and parse_numeric_token(item.get("valor")) is not None
        ],
        ("nombre", "valor"),
    )

    real_subsidy_names = {normalize_text(item.get("nombre")) for item in payload["subsidios"]}
    cleaned_additionals: list[dict[str, Any]] = []
    for item in payload.get("adicionales", []):
        if not isinstance(item, dict):
            continue
        name_norm = normalize_text(item.get("nombre"))
        value = parse_numeric_token(item.get("valor"))
        if value is None and "fallecimiento" in name_norm and any("fallecimiento" in name for name in real_subsidy_names):
            continue
        if value is None and name_norm in {"antiguedad", "presentismo", "zona desfavorable", "adicional detectado"}:
            continue
        if value is None and not has_meaningful_value(item.get("base")):
            continue
        cleaned_additionals.append(item)

    subsidy_additionals = [
        {
            "nombre": item["nombre"],
            "tipo": "monto_fijo",
            "valor": item["valor"],
            "base": None,
            "condicion": None,
            "codigo_sugerido": "900",
            "lsd": None,
            "fuente_textual": item.get("fuente_textual"),
        }
        for item in payload["subsidios"]
    ]
    payload["adicionales"] = dedupe_records([*subsidy_additionals, *cleaned_additionals], ("nombre", "valor"))[:80]

    rules = payload.get("reglas_liquidacion") or {}
    zone = rules.get("zona_desfavorable")
    if isinstance(zone, dict):
        pct = parse_numeric_token(zone.get("porcentaje") or zone.get("valor"))
        if pct and pct > 0:
            zone["porcentaje"] = pct
            zone["valor"] = pct
            payload["zona_desfavorable"] = zone
        elif pct == 0:
            rules["zona_desfavorable"] = None

    presentismo = rules.get("presentismo")
    if isinstance(presentismo, dict):
        source = normalize_text(presentismo.get("fuente_textual"))
        if parse_numeric_token(presentismo.get("valor")) is None or any(term in source for term in ("comision", "evaluara", "contempl")):
            payload["pendientes_revision"].append("Presentismo detectado como concepto futuro/no activo; no se liquida automaticamente.")
            rules["presentismo"] = None

    rules["no_remunerativos"] = [
        item
        for item in (rules.get("no_remunerativos") or [])
        if isinstance(item, dict) and parse_numeric_token(item.get("valor")) is not None
    ]
    payload["reglas_liquidacion"] = {key: value for key, value in rules.items() if has_meaningful_value(value)}

    categorias_validas = [
        item
        for item in payload["categorias"]
        if salary_output_record_is_valid(item)
    ]
    escalas_validas = [
        item
        for item in payload["escalas_salariales"]
        if salary_output_record_is_valid(item)
        and (parse_numeric_token(item.get("basico_mensual")) or parse_numeric_token(item.get("valor_hora")) or 0) > 0
    ]
    payload["diagnostico_ia"] = {
        **(payload.get("diagnostico_ia") if isinstance(payload.get("diagnostico_ia"), dict) else {}),
        "categorias_detectadas": len(payload["categorias"]),
        "categorias_validas": len(categorias_validas),
        "escalas_validas": len(escalas_validas),
    }
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

    print("GEMINI_MODEL efectivo:", os.getenv("GEMINI_MODEL"))
    print("CODEX_MODEL efectivo:", os.getenv("CODEX_MODEL"))

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
        fallback.setdefault("diagnostico_ia", {})
        fallback["diagnostico_ia"]["errores"] = dedupe_strings([
            *(fallback["diagnostico_ia"].get("errores") or []),
            compact_text(exc, 260),
        ])
        fallback["alertas"] = dedupe_strings([
            *fallback.get("alertas", []),
            f"Gemini no estuvo disponible: {compact_text(exc, 180)}",
            "Gemini no pudo procesar el documento completo; se utilizo parser local para recuperar datos.",
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
        "chat_model": os.getenv("GEMINI_CHAT_MODEL", os.getenv("GEMINI_MODEL", DEFAULT_MODEL)),
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


CHAT_NO_INFO_MESSAGE = "No cuento con esa informacion en esta calculadora."

CHAT_STOPWORDS = {
    "para",
    "pero",
    "como",
    "cual",
    "cuales",
    "cuando",
    "donde",
    "sobre",
    "tiene",
    "tener",
    "esta",
    "este",
    "estos",
    "estas",
    "cuanto",
    "cuanta",
    "cuantos",
    "cuantas",
    "valor",
    "valores",
    "info",
    "informacion",
    "dato",
    "datos",
    "decime",
    "dime",
}


def chat_format_money(value: Any) -> str:
    number = parse_numeric_token(value)
    if number is None:
        return ""
    return f"${number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def chat_tokenize(value: Any) -> list[str]:
    normalized = normalize_text(value)
    raw_tokens = re.findall(r"[a-z0-9]+", normalized)
    result: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        if len(token) < 3 or token in CHAT_STOPWORDS:
            continue
        variants = [token]
        if token.endswith("es") and len(token) > 5:
            variants.append(token[:-2])
        if token.endswith("s") and len(token) > 4:
            variants.append(token[:-1])
        for variant in variants:
            if variant not in seen and variant not in CHAT_STOPWORDS:
                seen.add(variant)
                result.append(variant)
    return result


def chat_record(title: str, text_value: str, source: str, record_type: str) -> dict[str, str]:
    return {
        "titulo": compact_text(title, 120),
        "texto": compact_text(text_value, 700),
        "fuente": compact_text(source or "Calculadora", 140),
        "tipo": record_type,
    }


def build_calculator_chat_records(calculator: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not isinstance(calculator, dict):
        return records

    convenio = calculator.get("convenio") if isinstance(calculator.get("convenio"), dict) else {}
    if convenio:
        parts = [
            f"{key}: {value}"
            for key, value in convenio.items()
            if has_meaningful_value(value) and key not in {"raw", "texto_completo"}
        ]
        if parts:
            records.append(chat_record("Convenio", ". ".join(parts), "Datos de la calculadora", "convenio"))

    parametros = calculator.get("parametros") if isinstance(calculator.get("parametros"), dict) else {}
    if parametros:
        parts = [f"{key}: {value}" for key, value in parametros.items() if has_meaningful_value(value)]
        if parts:
            records.append(chat_record("Parametros de liquidacion", ". ".join(parts), "Datos de la calculadora", "parametros"))

    for category in (calculator.get("categorias") or [])[:140]:
        if not isinstance(category, dict):
            continue
        name = compact_text(category.get("nombre") or category.get("categoria") or category.get("id"), 140)
        if not name:
            continue
        rama = compact_text(category.get("rama") or category.get("sector"), 120)
        monthly = chat_format_money(
            category.get("basico_mensual")
            or category.get("sueldo_mensual")
            or category.get("basico")
            or category.get("valor")
        )
        hourly = chat_format_money(category.get("valor_hora"))
        parts = [f"Categoria: {name}"]
        if rama:
            parts.append(f"Rama/sector: {rama}")
        if monthly:
            parts.append(f"Basico mensual: {monthly}")
        if hourly:
            parts.append(f"Valor hora: {hourly}")
        if category.get("tipo"):
            parts.append(f"Tipo: {category.get('tipo')}")
        if category.get("fuente_textual"):
            parts.append(f"Fuente textual: {category.get('fuente_textual')}")
        records.append(chat_record(f"Categoria {name}", ". ".join(parts), rama or "Categorias", "categoria"))

    for scale in (calculator.get("escalas_salariales") or [])[:180]:
        if not isinstance(scale, dict):
            continue
        name = compact_text(scale.get("categoria") or scale.get("nombre") or scale.get("id"), 140)
        if not name:
            continue
        rama = compact_text(scale.get("rama") or scale.get("sector"), 120)
        period = compact_text(scale.get("periodo") or scale.get("vigencia") or scale.get("valid_from"), 80)
        monthly = chat_format_money(
            scale.get("basico_mensual")
            or scale.get("sueldo_mensual")
            or scale.get("valor")
            or scale.get("base_salary")
        )
        hourly = chat_format_money(scale.get("valor_hora"))
        extra_parts = []
        for key in ("articulo_11", "multifuncionalidad", "adicional_1", "adicional_2", "adicional_3"):
            amount = chat_format_money(scale.get(key))
            if amount:
                extra_parts.append(f"{key}: {amount}")
        parts = [f"Categoria: {name}"]
        if rama:
            parts.append(f"Rama/sector: {rama}")
        if period:
            parts.append(f"Periodo: {period}")
        if monthly:
            parts.append(f"Basico mensual: {monthly}")
        if hourly:
            parts.append(f"Valor hora: {hourly}")
        parts.extend(extra_parts)
        if scale.get("fuente_textual"):
            parts.append(f"Fuente textual: {scale.get('fuente_textual')}")
        records.append(chat_record(f"Escala {name}", ". ".join(parts), period or rama or "Escalas", "escala"))

    for bucket_name, record_type in (
        ("adicionales", "adicional"),
        ("subsidios", "subsidio"),
        ("deducciones", "deduccion"),
        ("conceptos_liquidables", "concepto"),
    ):
        for item in (calculator.get(bucket_name) or [])[:100]:
            if not isinstance(item, dict):
                continue
            name = compact_text(item.get("nombre") or item.get("concepto") or item.get("codigo"), 140)
            if not name:
                continue
            amount = chat_format_money(item.get("valor") or item.get("monto") or item.get("importe"))
            parts = [f"{bucket_name}: {name}"]
            if amount:
                parts.append(f"Valor: {amount}")
            for key in ("tipo", "base", "formula", "condicion", "fuente_textual"):
                if has_meaningful_value(item.get(key)):
                    parts.append(f"{key}: {item.get(key)}")
            records.append(chat_record(name, ". ".join(parts), bucket_name, record_type))

    rules = calculator.get("reglas_liquidacion") if isinstance(calculator.get("reglas_liquidacion"), dict) else {}
    for name, value in rules.items():
        if not has_meaningful_value(value):
            continue
        if isinstance(value, (dict, list)):
            text_value = json.dumps(value, ensure_ascii=False)
        else:
            text_value = str(value)
        records.append(chat_record(f"Regla {name}", f"{name}: {text_value}", "Reglas de liquidacion", "regla"))

    for key in ("alertas", "pendientes_revision", "notas", "derechos"):
        values = calculator.get(key)
        if isinstance(values, list) and values:
            records.append(chat_record(key, ". ".join(compact_text(item, 180) for item in values[:30]), key, key))
        elif isinstance(values, str) and values.strip():
            records.append(chat_record(key, values, key, key))

    return [record for record in records if record["texto"]]


def rank_calculator_chat_records(question: str, records: list[dict[str, str]], limit: int = 10) -> list[dict[str, Any]]:
    tokens = chat_tokenize(question)
    if not tokens:
        return []

    ranked: list[dict[str, Any]] = []
    for record in records:
        haystack = normalize_text(f"{record.get('titulo')} {record.get('texto')} {record.get('fuente')}")
        score = 0
        for token in tokens:
            if token in haystack:
                score += 2 if len(token) >= 5 else 1
        if score:
            ranked.append({**record, "score": score})

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


def build_local_calculator_chat_answer(question: str, matches: list[dict[str, Any]]) -> str:
    if not matches:
        return CHAT_NO_INFO_MESSAGE

    bullets = []
    for item in matches[:6]:
        bullets.append(f"- {item['texto']}")

    return "Con la informacion cargada en esta calculadora:\n" + "\n".join(bullets)


def build_calculator_chat_prompt(question: str, calculator: dict[str, Any], matches: list[dict[str, Any]]) -> str:
    convenio = calculator.get("convenio") if isinstance(calculator.get("convenio"), dict) else {}
    context = json.dumps(
        [
            {
                "titulo": item.get("titulo"),
                "texto": item.get("texto"),
                "fuente": item.get("fuente"),
                "tipo": item.get("tipo"),
            }
            for item in matches[:10]
        ],
        ensure_ascii=False,
    )

    return f"""
Sos el asistente de una calculadora laboral argentina.
Responde en espanol, breve y claro.

Reglas obligatorias:
- Usa SOLO el CONTEXTO de esta calculadora.
- No inventes normas, importes, categorias ni escalas.
- Si el CONTEXTO no alcanza para responder, responde exactamente: {CHAT_NO_INFO_MESSAGE}
- No des asesoramiento legal definitivo; si corresponde, sugiere validar contra fuente oficial.

Convenio/calculadora:
{json.dumps(convenio, ensure_ascii=False)}

Pregunta:
{question}

CONTEXTO:
{context}
""".strip()


@app.post("/calculator-chat")
def calculator_chat(payload: CalculatorChatRequest) -> dict[str, Any]:
    question = compact_text(payload.question, 500)
    if not question:
        raise HTTPException(status_code=422, detail="Falta la pregunta.")

    records = build_calculator_chat_records(payload.calculator)
    matches = rank_calculator_chat_records(question, records)
    sources = [
        {
            "titulo": item.get("titulo"),
            "fuente": item.get("fuente"),
            "tipo": item.get("tipo"),
        }
        for item in matches[:5]
    ]

    if not matches:
        return {
            "mode": "local-no-info",
            "model": None,
            "answer": CHAT_NO_INFO_MESSAGE,
            "sources": [],
        }

    local_answer = build_local_calculator_chat_answer(question, matches)
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return {
            "mode": "local",
            "model": None,
            "answer": local_answer,
            "sources": sources,
        }

    model = os.getenv("GEMINI_CHAT_MODEL", os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    try:
        answer = call_gemini(build_calculator_chat_prompt(question, payload.calculator, matches), model)
        clean_answer = compact_text(answer, 3000)
        if not clean_answer:
            clean_answer = local_answer
        return {
            "mode": "gemini",
            "model": model,
            "answer": clean_answer,
            "sources": sources,
        }
    except GeminiProxyError as exc:
        return {
            "mode": "local-fallback",
            "model": model,
            "answer": local_answer,
            "sources": sources,
            "warning": compact_text(exc, 300),
        }


def generated_calculator_summary(path: Path) -> dict[str, Any]:
    html_text = path.read_text(encoding="utf-8", errors="replace")
    payload: dict[str, Any] = {}

    marker = "const DATA = "
    start = html_text.find(marker)
    if start >= 0:
        start += len(marker)
        end = html_text.find(";\nlet paso", start)
        if end < 0:
            end = html_text.find(";\r\nlet paso", start)
        if end > start:
            try:
                payload = json.loads(html_text[start:end].strip())
            except json.JSONDecodeError:
                payload = {}

    convenio = payload.get("convenio") if isinstance(payload.get("convenio"), dict) else {}
    diagnostico = payload.get("diagnostico_ia") if isinstance(payload.get("diagnostico_ia"), dict) else {}
    categorias_count = len(payload.get("categorias") or []) if isinstance(payload.get("categorias"), list) else 0
    escalas_count = len(payload.get("escalas_salariales") or []) if isinstance(payload.get("escalas_salariales"), list) else 0

    raw_title = convenio.get("nombre") or convenio.get("actividad") or path.stem.replace("-", " ").title()
    title_context = normalize_text(" ".join([str(raw_title), str(convenio.get("actividad")), str(payload.get("archivo_fuente"))]))
    if convenio.get("cct_numero") == "454/2006" and ("smata" in title_context or "automovil club argentino" in title_context):
        raw_title = "SMATA - ACA"
    elif normalize_text(raw_title).startswith("archivo del convenio") or "documento.errepar" in title_context or re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}", str(raw_title)):
        raw_title = convenio.get("actividad") or convenio.get("cct_numero") or path.stem.replace("-", " ").title()

    status = "ready" if categorias_count and (escalas_count or categorias_count) else "draft"
    modified = path.stat().st_mtime

    return {
        "title": compact_text(raw_title, 120),
        "cct": compact_text(convenio.get("cct_numero") or "CCT generado", 40),
        "status": status,
        "href": f"/generated/{path.name}",
        "engine": "Generada desde PDF",
        "scope": f"{categorias_count} categorias / {escalas_count} escalas",
        "validity": compact_text(convenio.get("vigencia_detectada") or "Generada", 60),
        "summary": compact_text(
            convenio.get("actividad")
            or f"Calculadora generada automaticamente desde {payload.get('archivo_fuente') or path.name}.",
            180,
        ),
        "features": [
            f"{diagnostico.get('categorias_validas', categorias_count)} categorias validas",
            f"{diagnostico.get('escalas_validas', escalas_count)} escalas validas",
            "JSON local",
        ],
        "source": "generated",
        "updated_at": modified,
    }


@app.get("/generated-calculators")
def list_generated_calculators() -> dict[str, Any]:
    generated_dir = TEMPLATES_DIR / "generated"
    if not generated_dir.exists():
        return {"items": []}

    files = sorted(
        generated_dir.glob("*.html"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return {"items": [generated_calculator_summary(path) for path in files]}



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


@app.get("/{page_name}.html", include_in_schema=False)
def template_html_page(page_name: str):
    safe_name = Path(page_name).name
    if safe_name != page_name or not re.fullmatch(r"[A-Za-z0-9_.-]+", page_name):
        raise HTTPException(status_code=404, detail="HTML no encontrado")

    path = TEMPLATES_DIR / f"{page_name}.html"
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="HTML no encontrado")

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


