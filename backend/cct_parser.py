from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from typing import Any


def normalize_text(value: Any) -> str:
    return (
        unicodedata.normalize("NFD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )


def compact_text(value: Any, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def slugify(value: Any) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", normalize_text(value)).strip("_")
    return cleaned[:64] or "item"


def has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def to_number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return value
        return int(value)

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("$", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", ".")

    try:
        number = float(normalized)
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


def strip_markdown(markdown: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_`>#-]", " ", text)
    text = re.sub(r"\|", " | ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_markdown_tables(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if len(current) < 2:
            current = []
            return
        if not any(re.search(r"\|\s*:?-{2,}", line) for line in current):
            current = []
            return

        lines = [line.strip() for line in current if line.strip()]
        if len(lines) < 2:
            current = []
            return

        header = [cell.strip() for cell in lines[0].strip("|").split("|")]
        rows: list[list[str]] = []
        for line in lines[2:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == len(header):
                rows.append(cells)
        blocks.append({"header": header, "rows": rows, "markdown": "\n".join(lines)})
        current = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if "|" in line:
            current.append(line)
        else:
            flush()
    flush()
    return blocks


def guess_category_type(label: str) -> str:
    normalized = normalize_text(label)
    if any(term in normalized for term in ("administr", "emplead", "cajer", "escribiente")):
        return "administrativo"
    if any(term in normalized for term in ("hora", "jornal", "operario", "oficial", "medio oficial")):
        return "jornalizado"
    if any(term in normalized for term in ("mensual", "encargado", "jefe", "chofer")):
        return "mensualizado"
    return "otro"


def is_probable_category_label(label: str) -> bool:
    normalized = normalize_text(label)
    if len(normalized) < 4:
        return False

    excluded_terms = (
        "acuerdo",
        "no remunerativ",
        "bono",
        "subsidio",
        "adicional",
        "antiguedad",
        "presentismo",
        "aporte",
        "descuento",
        "licencia",
        "viatico",
        "feriado",
        "hora extra",
        "retroactivo",
        "diferencia",
        "total",
        "subtotal",
        "sac",
        "zona",
    )
    if any(term in normalized for term in excluded_terms):
        return False

    hints = (
        "categoria",
        "operario",
        "oficial",
        "medio oficial",
        "administrativo",
        "administracion",
        "encargado",
        "jefe",
        "chofer",
        "auxilio mecanico",
        "cajero",
        "maestranza",
        "cadete",
    )
    return any(hint in normalized for hint in hints)


def pick_match(text: str, pattern: str, group: int = 1) -> str | None:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return None
    return compact_text(match.group(group), 220) or None


def extract_cct_number(text: str) -> str | None:
    match = re.search(r"\b(?:cct|convenio colectivo)\s*(?:n[ro.\s]*)?(\d+\s*/\s*\d{2,4})", normalize_text(text))
    return match.group(1).replace(" ", "") if match else None


def detect_activity(text: str) -> str | None:
    return pick_match(text, r"(personal.{0,220}?dependiente.{0,160}?\.)")


def detect_ambit(text: str) -> str | None:
    return pick_match(text, r"(todo el territorio.{0,120}?\.)")


def detect_convenio_name(text: str, file_name: str) -> str:
    lines = [compact_text(line, 200) for line in text.splitlines() if compact_text(line, 200)]
    for line in lines[:20]:
        normalized = normalize_text(line)
        if "convenio" in normalized or "cct " in normalized:
            return line
    detected = extract_cct_number(text)
    return compact_text(f"{file_name} ({detected})" if detected else file_name, 180)


MONTHS_PATTERN = (
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
)


def detect_vigencia(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text)
    date_range = re.search(
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}).{0,24}?(?:al|hasta|-)\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        normalized,
        re.I,
    )
    if date_range:
        return f"{date_range.group(1)} al {date_range.group(2)}"

    month_range = re.search(
        rf"(({MONTHS_PATTERN})(?:\s+y\s+|,|\s+)(?:{MONTHS_PATTERN}).{{0,16}}?\d{{4}})",
        normalized,
        re.I,
    )
    if month_range:
        return compact_text(month_range.group(1), 80)

    month_single = re.search(rf"({MONTHS_PATTERN}\s+\d{{4}})", normalized, re.I)
    if month_single:
        return compact_text(month_single.group(1), 40)
    return None


def detect_hours(text: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text)
    monthly = re.search(r"(\d{2,3})\s*horas?\s*(?:mensuales|por mes|al mes)", normalized, re.I)
    weekly = re.search(r"(\d{2})\s*horas?\s*(?:semanales|por semana)", normalized, re.I)
    daily = re.search(r"(\d{1,2})\s*horas?\s*(?:diarias|por dia)", normalized, re.I)
    divisor = re.search(r"divisor.{0,20}?(\d{2})", normalized, re.I)

    base_calculo = "mensualizado"
    lowered = normalize_text(text)
    if "base compuesta" in lowered or "salario conformado" in lowered:
        base_calculo = "compuesta"
    elif "base integrada" in lowered:
        base_calculo = "integrada"

    return {
        "divisor_mensual": int(divisor.group(1)) if divisor else 30,
        "horas_mensuales": int(monthly.group(1)) if monthly else None,
        "horas_semanales": int(weekly.group(1)) if weekly else None,
        "horas_diarias": int(daily.group(1)) if daily else None,
        "base_calculo": base_calculo,
    }


def extract_antiguedad_rule(text: str) -> dict[str, Any] | None:
    if "antig" not in normalize_text(text):
        return None
    percentage = to_number(pick_match(text, r"antig[üu]edad[\s\S]{0,160}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%"))
    return {
        "tipo": "porcentaje_por_anio",
        "porcentaje_por_anio": percentage or 1,
        "base_monto": None,
        "fuente_textual": pick_match(text, r"(antig[üu]edad[\s\S]{0,280})", 1),
    }


def extract_presentismo_rule(text: str) -> dict[str, Any] | None:
    if "presentismo" not in normalize_text(text):
        return None
    percentage = to_number(pick_match(text, r"presentismo[\s\S]{0,120}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%"))
    return {
        "tipo": "porcentaje",
        "valor": percentage,
        "fuente_textual": pick_match(text, r"(presentismo[\s\S]{0,220})", 1),
    }


def extract_zone_rule(text: str) -> dict[str, Any] | None:
    provinces = ["Neuquen", "Rio Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"]
    if not any(province.lower() in normalize_text(text) for province in provinces):
        return None
    percentage = to_number(pick_match(text, r"(?:zona|patagoni|\bneuquen\b)[\s\S]{0,160}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%"))
    return {
        "porcentaje": percentage or 0,
        "provincias": provinces,
        "fuente_textual": pick_match(text, r"((?:zona|condiciones especiales|patagoni)[\s\S]{0,260})", 1),
    }


def extract_extra_hours_rule(text: str) -> dict[str, Any] | None:
    if "extra" not in normalize_text(text):
        return None
    recargo_50 = to_number(pick_match(text, r"(?:hora|horas)\s+extra[\s\S]{0,80}?50\s*%"))
    recargo_100 = to_number(pick_match(text, r"(?:hora|horas)\s+extra[\s\S]{0,160}?100\s*%"))
    return {
        "recargo_50": recargo_50 or 50,
        "recargo_100": recargo_100 or 100,
        "fuente_textual": pick_match(text, r"((?:hora|horas)\s+extra[\s\S]{0,220})", 1),
    }


def extract_licenses(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        if "licenc" not in normalize_text(line):
            continue
        items.append({"nombre": line[:90], "fuente_textual": line})
        if len(items) >= 12:
            break
    return dedupe_records(items, ("nombre", "fuente_textual"))


def extract_relevant_articles(text: str) -> list[dict[str, Any]]:
    article_keywords = ("antig", "licenc", "jornada", "zona", "presentismo", "vacacion", "extra", "no remunerativ")
    articles: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        normalized = normalize_text(line)
        if "art" not in normalized:
            continue
        if not any(keyword in normalized for keyword in article_keywords):
            continue
        article = pick_match(line, r"(art\.?\s*\d+[^\-:\.]*)(?:[:\-\.]|$)", 1) or line[:18]
        articles.append({"articulo": article, "tema": line[:80], "fuente_textual": line})
        if len(articles) >= 18:
            break
    return dedupe_records(articles, ("articulo", "tema"))


def extract_subsidios(text: str) -> list[dict[str, Any]]:
    names = {
        "casamiento": "Casamiento",
        "fallecimiento": "Fallecimiento",
        "nacimiento": "Nacimiento",
        "adopcion": "Adopcion",
    }
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        lowered = normalize_text(line)
        matched = next((label for key, label in names.items() if key in lowered), None)
        if not matched:
            continue
        amount = to_number(pick_match(line, r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*$"))
        items.append({"nombre": matched, "tipo": "monto_fijo", "valor": amount, "fuente_textual": line})
    return dedupe_records(items, ("nombre", "fuente_textual"))


def extract_no_remunerativos(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        lowered = normalize_text(line)
        if "no remunerativ" not in lowered and "acuerdo" not in lowered:
            continue
        amount = to_number(pick_match(line, r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*$"))
        items.append({"nombre": line[:100], "monto": amount, "fuente_textual": line})
        if len(items) >= 20:
            break
    return dedupe_records(items, ("nombre", "fuente_textual"))


def extract_additionals(text: str) -> list[dict[str, Any]]:
    keywords = {
        "antiguedad": "Antiguedad",
        "presentismo": "Presentismo",
        "zona": "Zona desfavorable",
        "viatico": "Viatico",
        "idioma": "Idioma",
        "titulo": "Titulo",
        "feriado": "Recargo por feriado",
        "extra": "Horas extra",
        "productividad": "Productividad",
        "no remunerativ": "No remunerativo",
        "bono": "Bono",
    }

    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        lowered = normalize_text(line)
        if len(line) < 6:
            continue
        matched = next((label for key, label in keywords.items() if key in lowered), None)
        if matched is None:
            continue
        percentage = to_number(pick_match(line, r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%"))
        amount = to_number(pick_match(line, r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*$"))
        items.append(
            {
                "nombre": matched,
                "tipo": "porcentaje" if percentage is not None else "monto_fijo" if amount is not None else "otro",
                "valor": percentage if percentage is not None else amount,
                "base": None,
                "condicion": None,
                "codigo_sugerido": None,
                "lsd": None,
                "fuente_textual": line,
            }
        )
        if len(items) >= 20:
            break
    return dedupe_records(items, ("nombre", "fuente_textual"))


def extract_scale_categories(markdown: str, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []

    for table in tables:
        header = [normalize_text(cell) for cell in table.get("header", [])]
        if not header:
            continue

        # Escalas simples de casas particulares:
        # Modalidad | Valor por hora
        # Con retiro | $3.547,45
        # Sin retiro | $3.805,10
        if any("modalidad" in cell for cell in header) and any(
            "valor" in cell or "hora" in cell for cell in header
        ):
            for row in table.get("rows", []):
                if len(row) < 2:
                    continue

                modalidad = compact_text(row[0], 80)
                monto = to_number(row[1])

                if not modalidad or monto is None:
                    continue

                categories.append(
                    {
                        "id": slugify(f"tareas_generales_{modalidad}"),
                        "nombre": "Tareas Generales",
                        "tipo": "jornalizado",
                        "descripcion": modalidad,
                        "basico_mensual": None,
                        "sueldo_mensual": None,
                        "valor": monto,
                        "valor_hora": monto,
                        "tipo_valor": "hora",
                        "grupo": modalidad,
                        "fuente_textual": compact_text(" | ".join(row), 180),
                    }
                )

            continue

        if not any("categoria" in cell or "cargo" in cell or "puesto" in cell or "descripcion" in cell for cell in header):
            continue
        for row in table.get("rows", []):
            if not row:
                continue
            name = compact_text(row[0], 140)
            if not is_probable_category_label(name):
                continue
            numeric_cells = [to_number(cell) for cell in row[1:] if to_number(cell) is not None]
            basico = numeric_cells[-1] if numeric_cells else None
            categories.append(
                {
                    "id": slugify(name),
                    "nombre": name,
                    "tipo": guess_category_type(name),
                    "descripcion": name,
                    "basico_mensual": basico,
                    "sueldo_mensual": basico,
                    "valor": basico,
                    "valor_hora": None,
                    "tipo_valor": "mensual",
                    "grupo": None,
                    "fuente_textual": compact_text(" | ".join(row), 180),
                }
            )

    if categories:
        return dedupe_records(categories, ("id", "nombre"))

    for raw_line in markdown.splitlines():
        line = compact_text(raw_line, 220)
        if not is_probable_category_label(line):
            continue
        amount_match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*$", line)
        amount = to_number(amount_match.group(1)) if amount_match else None
        if amount is None:
            continue
        name = compact_text(line[: amount_match.start()], 140)
        if not is_probable_category_label(name):
            continue
        categories.append(
            {
                "id": slugify(name),
                "nombre": name,
                "tipo": guess_category_type(name),
                "descripcion": name,
                "basico_mensual": amount,
                "sueldo_mensual": amount,
                "valor": amount,
                "valor_hora": None,
                "tipo_valor": "mensual",
                "grupo": None,
                "fuente_textual": line,
            }
        )
    return dedupe_records(categories, ("id", "nombre"))


def extract_cct_categories(markdown: str, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []

    for table in tables:
        header = [normalize_text(cell) for cell in table.get("header", [])]
        if header and any("categoria" in cell or "cargo" in cell or "puesto" in cell for cell in header):
            for row in table.get("rows", []):
                if not row:
                    continue
                name = compact_text(row[0], 140)
                if not is_probable_category_label(name):
                    continue
                categories.append(
                    {
                        "id": slugify(name),
                        "nombre": name,
                        "tipo": guess_category_type(name),
                        "descripcion": compact_text(" | ".join(row), 180),
                        "basico_mensual": None,
                        "sueldo_mensual": None,
                        "valor": None,
                        "valor_hora": None,
                        "tipo_valor": "mensual",
                        "grupo": None,
                        "fuente_textual": compact_text(" | ".join(row), 180),
                    }
                )

    if categories:
        return dedupe_records(categories, ("id", "nombre"))

    for raw_line in markdown.splitlines():
        line = compact_text(raw_line, 220)
        if not is_probable_category_label(line):
            continue
        categories.append(
            {
                "id": slugify(line),
                "nombre": line,
                "tipo": guess_category_type(line),
                "descripcion": line,
                "basico_mensual": None,
                "sueldo_mensual": None,
                "valor": None,
                "valor_hora": None,
                "tipo_valor": "mensual",
                "grupo": None,
                "fuente_textual": line,
            }
        )
        if len(categories) >= 24:
            break
    return dedupe_records(categories, ("id", "nombre"))


def _build_origin(provider: str, kind: str, ocr_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "proveedor": provider,
        "tipo_documento": kind,
        "modelo_ocr": ocr_payload.get("model"),
        "paginas_procesadas": len(ocr_payload.get("pages") or []),
        "tablas_detectadas": len(ocr_payload.get("tables") or []),
        "fallback_local": bool(ocr_payload.get("fallback_local")),
        "archivo_temporal": ocr_payload.get("file_name"),
    }


def parse_document(ocr_payload: dict[str, Any], *, kind: str, file_name: str, provider: str = "Mistral OCR") -> dict[str, Any]:
    markdown = str(ocr_payload.get("markdown") or "")
    plain_text = str(ocr_payload.get("text") or strip_markdown(markdown))
    tables = list(ocr_payload.get("tables") or extract_markdown_tables(markdown))
    lines_text = "\n".join(page.get("markdown", "") for page in ocr_payload.get("pages", []) if isinstance(page, dict)) or markdown

    if kind == "cct":
        categories = extract_cct_categories(lines_text, tables)
        jornada = detect_hours(plain_text)
        payload = {
            "version": date.today().isoformat(),
            "archivo_fuente": file_name,
            "estado": "parser_cct_local",
            "origen": _build_origin(provider, kind, ocr_payload),
            "ocr": {
                "markdown_preview": compact_text(markdown, 2400),
                "text_preview": compact_text(plain_text, 1600),
                "table_count": len(tables),
                "page_count": len(ocr_payload.get("pages") or []),
            },
            "convenio": {
                "nombre": detect_convenio_name(lines_text or plain_text, file_name),
                "actividad": detect_activity(plain_text),
                "ambito": detect_ambit(plain_text),
                "cct_numero": extract_cct_number(plain_text),
                "vigencia_detectada": detect_vigencia(plain_text),
            },
            "parametros": jornada,
            "jornada": jornada,
            "vigencia": detect_vigencia(plain_text),
            "categorias": categories,
            "adicionales": extract_additionals(lines_text),
            "subsidios": extract_subsidios(lines_text),
            "zonas": [extract_zone_rule(lines_text)] if extract_zone_rule(lines_text) else [],
            "reglas_liquidacion": {
                "antiguedad": extract_antiguedad_rule(lines_text),
                "presentismo": extract_presentismo_rule(lines_text),
                "zona_desfavorable": extract_zone_rule(lines_text),
                "horas_extra": extract_extra_hours_rule(lines_text),
                "licencias": extract_licenses(lines_text),
                "articulos_relevantes": extract_relevant_articles(lines_text),
                "no_remunerativos": [],
            },
            "pendientes_revision": [],
            "alertas": [],
            "nivel_confianza": 0.55,
        }

        if not categories:
            payload["pendientes_revision"].append("No se detectaron categorias claras en el convenio; revisar OCR y estructura.")
        if not payload["convenio"]["cct_numero"]:
            payload["pendientes_revision"].append("Confirmar el numero de CCT del documento.")
        if not jornada.get("horas_semanales") and not jornada.get("horas_mensuales"):
            payload["pendientes_revision"].append("Confirmar jornada legal y divisor mensual.")
        payload["nivel_confianza"] = 0.78 if categories or payload["reglas_liquidacion"]["antiguedad"] else 0.48
        return payload

    categories = extract_scale_categories(lines_text, tables)
    no_remunerativos = extract_no_remunerativos(lines_text)
    payload = {
        "version": date.today().isoformat(),
        "archivo_fuente": file_name,
        "estado": "parser_scale_local",
        "origen": _build_origin(provider, kind, ocr_payload),
        "ocr": {
            "markdown_preview": compact_text(markdown, 2400),
            "text_preview": compact_text(plain_text, 1600),
            "table_count": len(tables),
            "page_count": len(ocr_payload.get("pages") or []),
        },
        "convenio": {
            "nombre": detect_convenio_name(lines_text or plain_text, file_name),
            "vigencia_detectada": detect_vigencia(plain_text),
        },
        "vigencia": detect_vigencia(plain_text),
        "categorias": categories,
        "adicionales": [],
        "subsidios": [],
        "zonas": [],
        "no_remunerativos": no_remunerativos,
        "acuerdos": [item["fuente_textual"] for item in no_remunerativos],
        "montos": [
            {"nombre": item["nombre"], "monto": item["monto"], "fuente_textual": item["fuente_textual"]}
            for item in no_remunerativos
        ],
        "reglas_liquidacion": {},
        "pendientes_revision": [],
        "alertas": [],
        "nivel_confianza": 0.52,
    }
    if not categories:
        payload["alertas"].append("La escala OCR no devolvio categorias con basicos claros.")
    if not payload["vigencia"]:
        payload["pendientes_revision"].append("Confirmar vigencia exacta de la escala salarial.")
    payload["nivel_confianza"] = 0.84 if categories else 0.46
    return payload


def normalize_document_payload(payload: dict[str, Any], *, kind: str, file_name: str) -> dict[str, Any]:
    cloned = dict(payload or {})
    cloned.setdefault("version", date.today().isoformat())
    cloned.setdefault("archivo_fuente", file_name)
    cloned.setdefault("estado", f"{kind}_normalizado")
    cloned.setdefault("origen", {})
    cloned.setdefault("ocr", {})
    cloned.setdefault("convenio", {})
    cloned.setdefault("categorias", [])
    cloned.setdefault("adicionales", [])
    cloned.setdefault("subsidios", [])
    cloned.setdefault("zonas", [])
    cloned.setdefault("vigencia", None)
    cloned.setdefault("reglas_liquidacion", {})
    cloned.setdefault("pendientes_revision", [])
    cloned.setdefault("alertas", [])
    cloned.setdefault("nivel_confianza", 0)
    if kind == "scale":
        cloned.setdefault("no_remunerativos", [])
        cloned.setdefault("acuerdos", [])
        cloned.setdefault("montos", [])
    else:
        cloned.setdefault("parametros", {})
        cloned.setdefault("jornada", cloned.get("parametros") or {})
    return cloned


def merge_document_payloads(primary: dict[str, Any] | None, fallback: dict[str, Any], *, kind: str, file_name: str) -> dict[str, Any]:
    base = normalize_document_payload(fallback, kind=kind, file_name=file_name)
    overlay = normalize_document_payload(primary or {}, kind=kind, file_name=file_name)

    merged = dict(base)
    for key in ("version", "archivo_fuente", "vigencia", "nivel_confianza"):
        if has_meaningful_value(overlay.get(key)):
            merged[key] = overlay[key]

    for nested_key in ("origen", "ocr", "convenio", "reglas_liquidacion"):
        merged[nested_key] = {
            **(base.get(nested_key) or {}),
            **{sub_key: sub_value for sub_key, sub_value in (overlay.get(nested_key) or {}).items() if has_meaningful_value(sub_value)},
        }

    if kind == "cct":
        for nested_key in ("parametros", "jornada"):
            merged[nested_key] = {
                **(base.get(nested_key) or {}),
                **{sub_key: sub_value for sub_key, sub_value in (overlay.get(nested_key) or {}).items() if has_meaningful_value(sub_value)},
            }

    merged["categorias"] = dedupe_records((overlay.get("categorias") or []) + (base.get("categorias") or []), ("id", "nombre"))
    merged["adicionales"] = dedupe_records((overlay.get("adicionales") or []) + (base.get("adicionales") or []), ("nombre", "fuente_textual"))
    merged["subsidios"] = dedupe_records((overlay.get("subsidios") or []) + (base.get("subsidios") or []), ("nombre", "fuente_textual"))
    merged["zonas"] = [item for item in (overlay.get("zonas") or []) + (base.get("zonas") or []) if has_meaningful_value(item)]
    merged["pendientes_revision"] = dedupe_strings([*(base.get("pendientes_revision") or []), *(overlay.get("pendientes_revision") or [])])
    merged["alertas"] = dedupe_strings([*(base.get("alertas") or []), *(overlay.get("alertas") or [])])
    merged["estado"] = f"mistral_qwen_{kind}" if primary else base.get("estado")

    if kind == "scale":
        merged["no_remunerativos"] = dedupe_records(
            (overlay.get("no_remunerativos") or []) + (base.get("no_remunerativos") or []),
            ("nombre", "fuente_textual"),
        )
        merged["acuerdos"] = dedupe_strings([*(base.get("acuerdos") or []), *(overlay.get("acuerdos") or [])])
        merged["montos"] = dedupe_records((overlay.get("montos") or []) + (base.get("montos") or []), ("nombre", "fuente_textual"))

    return merged


def _category_key(item: dict[str, Any]) -> str:
    return normalize_text(item.get("nombre"))


def merge_calculator_payload(cct_json: dict[str, Any], escala_json: dict[str, Any]) -> dict[str, Any]:
    cct = normalize_document_payload(cct_json, kind="cct", file_name=str(cct_json.get("archivo_fuente") or "cct.pdf"))
    scale = normalize_document_payload(escala_json, kind="scale", file_name=str(escala_json.get("archivo_fuente") or "escala.pdf"))

    cct_by_key = {_category_key(item): item for item in cct.get("categorias", []) if _category_key(item)}
    scale_by_key = {_category_key(item): item for item in scale.get("categorias", []) if _category_key(item)}

    categories: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for key, scale_item in scale_by_key.items():
        cct_item = cct_by_key.get(key, {})
        basico = to_number(scale_item.get("basico_mensual") or scale_item.get("sueldo_mensual") or scale_item.get("valor"))
        valor_hora = to_number(scale_item.get("valor_hora"))
        categories.append(
            {
                "id": scale_item.get("id") or cct_item.get("id") or slugify(scale_item.get("nombre")),
                "nombre": scale_item.get("nombre") or cct_item.get("nombre"),
                "tipo": scale_item.get("tipo") or cct_item.get("tipo") or guess_category_type(scale_item.get("nombre", "")),
                "descripcion": cct_item.get("descripcion") or scale_item.get("descripcion") or scale_item.get("fuente_textual"),
                "basico_mensual": basico,
                "sueldo_mensual": basico,
                "valor": basico,
                "valor_hora": valor_hora,
                "tipo_valor": "hora" if valor_hora and not basico else "mensual",
                "grupo": scale_item.get("grupo") or cct_item.get("grupo"),
                "fuente_textual": scale_item.get("fuente_textual") or cct_item.get("fuente_textual"),
            }
        )
        if key not in cct_by_key:
            warnings.append(f"La escala incluye '{scale_item.get('nombre')}' pero no encontre esa categoria en el CCT.")
        seen.add(key)

    for key, cct_item in cct_by_key.items():
        if key in seen:
            continue
        categories.append(
            {
                "id": cct_item.get("id") or slugify(cct_item.get("nombre")),
                "nombre": cct_item.get("nombre"),
                "tipo": cct_item.get("tipo") or guess_category_type(cct_item.get("nombre", "")),
                "descripcion": cct_item.get("descripcion") or cct_item.get("fuente_textual"),
                "basico_mensual": None,
                "sueldo_mensual": None,
                "valor": None,
                "valor_hora": None,
                "tipo_valor": "mensual",
                "grupo": cct_item.get("grupo"),
                "fuente_textual": cct_item.get("fuente_textual"),
            }
        )
        warnings.append(f"No encontre basico de escala para la categoria '{cct_item.get('nombre')}'.")

    additionals = dedupe_records(
        [*(cct.get("adicionales") or []), *[
            {
                "nombre": item.get("nombre"),
                "tipo": "monto_fijo",
                "valor": item.get("monto"),
                "base": None,
                "condicion": "No remunerativo detectado en escala/acuerdo",
                "codigo_sugerido": "900",
                "lsd": None,
                "fuente_textual": item.get("fuente_textual"),
            }
            for item in (scale.get("no_remunerativos") or [])
        ]],
        ("nombre", "fuente_textual"),
    )

    convenio = dict(cct.get("convenio") or {})
    if not convenio.get("vigencia_detectada"):
        convenio["vigencia_detectada"] = scale.get("vigencia") or (scale.get("convenio") or {}).get("vigencia_detectada")

    reglas = dict(cct.get("reglas_liquidacion") or {})
    reglas["no_remunerativos"] = scale.get("no_remunerativos") or []
    reglas["escala_vigencia"] = scale.get("vigencia")

    confidence = (float(cct.get("nivel_confianza") or 0) + float(scale.get("nivel_confianza") or 0)) / 2

    return {
        "version": date.today().isoformat(),
        "archivo_fuente": f"{cct.get('archivo_fuente') or 'cct.pdf'} + {scale.get('archivo_fuente') or 'escala.pdf'}",
        "estado": "payload_mistral_qwen_fusionado",
        "origen": {
            "proveedor": "Mistral OCR + Qwen + Parser",
            "documentos": [cct.get("origen"), scale.get("origen")],
        },
        "convenio": convenio,
        "parametros": cct.get("parametros") or cct.get("jornada") or {"divisor_mensual": 30, "base_calculo": "mensualizado"},
        "vigencia": scale.get("vigencia") or convenio.get("vigencia_detectada"),
        "categorias": dedupe_records(categories, ("id", "nombre")),
        "adicionales": additionals,
        "subsidios": dedupe_records(cct.get("subsidios") or [], ("nombre", "fuente_textual")),
        "zonas": dedupe_records(cct.get("zonas") or [], ("fuente_textual",)),
        "reglas_liquidacion": reglas,
        "bases": {
            "origen_cct": cct.get("archivo_fuente"),
            "origen_escala": scale.get("archivo_fuente"),
        },
        "pendientes_revision": dedupe_strings([*(cct.get("pendientes_revision") or []), *(scale.get("pendientes_revision") or []), *warnings]),
        "alertas": dedupe_strings([*(cct.get("alertas") or []), *(scale.get("alertas") or [])]),
        "nivel_confianza": round(confidence, 2),
        "documentos_fuente": {"cct": cct, "escala": scale},
    }


def to_pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
