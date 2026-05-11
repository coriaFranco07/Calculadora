from __future__ import annotations

import json
import re
import unicodedata
from abc import ABC, abstractmethod
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
    raw = compact_text(label, 240)
    normalized = normalize_text(label)
    if len(normalized) < 4 or len(raw) > 90:
        return False
    if len(normalized.split()) > 9:
        return False
    if re.search(r"https?://|www\.|@|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", normalized):
        return False
    if re.search(r"\b(?:bol\.?\s*oficial|boletin oficial|expediente|resolucion|decreto|ley\s+\d|articulo|clausula|anexo|pagina|page)\b", normalized):
        return False
    if normalized in {
        "categoria",
        "categorias",
        "categorias profesionales",
        "categoria profesional",
        "descripcion",
        "puesto",
        "cargo",
        "basico",
        "basicos",
        "sueldo basico",
        "remuneracion",
        "remuneraciones",
    }:
        return False
    if re.fullmatch(r"[\d\s.,$/%-]+", normalized):
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
        "vigencia",
        "desde",
        "hasta",
        "homolog",
        "partes",
        "convenio",
        "colectivo",
        "trabajo",
        "firmantes",
        "ministerio",
        "secretaria",
        "art.",
        "art ",
    )
    if any(term in normalized for term in excluded_terms):
        return False

    hints = (
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
        "vendedor",
        "supervisor",
        "tecnico",
        "técnico",
        "peon",
        "peón",
        "ayudante",
        "aprendiz",
    )
    return any(hint in normalized for hint in hints)


def is_valid_salary_amount(value: Any) -> bool:
    amount = to_number(value)
    return amount is not None and amount > 0


def is_valid_scale_row_name(name: str) -> bool:
    if not is_probable_category_label(name):
        return False
    normalized = normalize_text(name)
    if ":" in name and re.search(r"\d", name):
        return False
    if any(term in normalized for term in ("escala salarial", "rama", "periodo", "mes", "año", "ano")):
        return False
    return True


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
    normalized = normalize_text(text)
    if "antig" not in normalized:
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
        raw_header = [compact_text(cell, 80) for cell in table.get("header", [])]

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

                if not modalidad or not is_valid_salary_amount(monto):
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

        name_col = next(
            (
                index
                for index, cell in enumerate(header)
                if "categoria" in cell or "cargo" in cell or "puesto" in cell or "descripcion" in cell
            ),
            0,
        )
        for row in table.get("rows", []):
            if not row:
                continue
            if len(row) <= name_col:
                continue
            name = compact_text(row[name_col], 90)
            if not is_valid_scale_row_name(name):
                continue
            numeric_cells: list[tuple[int, int | float]] = []
            for index, cell in enumerate(row):
                if index == name_col:
                    continue
                text_cell = str(cell or "")
                if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text_cell):
                    continue
                number = to_number(text_cell)
                if is_valid_salary_amount(number):
                    numeric_cells.append((index, number))
            if not numeric_cells:
                continue
            amount_col, basico = numeric_cells[-1]
            amount_header = normalize_text(raw_header[amount_col] if amount_col < len(raw_header) else "")
            is_hourly = "hora" in amount_header or "jornal" in amount_header
            categories.append(
                {
                    "id": slugify(name),
                    "nombre": name,
                    "tipo": guess_category_type(name),
                    "descripcion": name,
                    "basico_mensual": None if is_hourly else basico,
                    "sueldo_mensual": None if is_hourly else basico,
                    "valor": basico,
                    "valor_hora": basico if is_hourly else None,
                    "tipo_valor": "hora" if is_hourly else "mensual",
                    "grupo": None,
                    "vigencia_desde": raw_header[amount_col] if amount_col < len(raw_header) else None,
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
        if not is_valid_salary_amount(amount):
            continue
        name = compact_text(line[: amount_match.start()], 140)
        if not is_valid_scale_row_name(name):
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
                name = compact_text(row[0], 90)
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


def parse_document(ocr_payload: dict[str, Any], *, kind: str, file_name: str, provider: str = "PDF local + Parser") -> dict[str, Any]:
    markdown = str(ocr_payload.get("markdown") or "")
    plain_text = str(ocr_payload.get("text") or strip_markdown(markdown))
    tables = list(ocr_payload.get("tables") or extract_markdown_tables(markdown))
    lines_text = "\n".join(page.get("markdown", "") for page in ocr_payload.get("pages", []) if isinstance(page, dict)) or markdown

    # ========================================================================
    # CAPA 1: Parser genérico
    # ========================================================================
    generic_parsed = extract_generic_salary_lines(lines_text or plain_text)

    # ========================================================================
    # CAPA 2: Parsers especializados
    # ========================================================================
    specialized_parsed = run_specialized_parsers(lines_text or plain_text)

    if kind == "cct":
        # Extraer también con los métodos locales legacy
        local_categories = extract_cct_categories(lines_text, tables)
        jornada = detect_hours(plain_text)

        # Mergear: specialized > generic > local
        all_categorias = (
            dedupe_records(specialized_parsed.get("categorias") or [], ("nombre", "rama"))
            + dedupe_records(generic_parsed.get("categorias") or [], ("nombre", "rama"))
            + local_categories
        )
        all_categorias = dedupe_records(all_categorias, ("nombre", "rama"))

        # Mergear reglas
        reglas_liquidacion = {
            "antiguedad": extract_antiguedad_rule(lines_text),
            "presentismo": extract_presentismo_rule(lines_text),
            "zona_desfavorable": extract_zone_rule(lines_text),
            "horas_extra": extract_extra_hours_rule(lines_text),
            "licencias": extract_licenses(lines_text),
            "articulos_relevantes": extract_relevant_articles(lines_text),
            "no_remunerativos": [],
        }

        # Sobrescribir con valores especializados si existen
        if specialized_parsed.get("reglas_liquidacion"):
            reglas_liquidacion.update(specialized_parsed["reglas_liquidacion"])

        # Mergear subsidios
        all_subsidios = (
            dedupe_records(specialized_parsed.get("subsidios") or [], ("nombre", "fuente_textual"))
            + extract_subsidios(lines_text)
        )
        all_subsidios = dedupe_records(all_subsidios, ("nombre", "fuente_textual"))

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
            "categorias": all_categorias,
            "adicionales": extract_additionals(lines_text),
            "subsidios": all_subsidios,
            "zonas": [extract_zone_rule(lines_text)] if extract_zone_rule(lines_text) else [],
            "reglas_liquidacion": reglas_liquidacion,
            "pendientes_revision": [],
            "alertas": [],
            "nivel_confianza": 0.55,
        }

        if not all_categorias:
            payload["pendientes_revision"].append("No se detectaron categorias claras en el convenio; revisar OCR y estructura.")
        if not payload["convenio"]["cct_numero"]:
            payload["pendientes_revision"].append("Confirmar el numero de CCT del documento.")
        if not jornada.get("horas_semanales") and not jornada.get("horas_mensuales"):
            payload["pendientes_revision"].append("Confirmar jornada legal y divisor mensual.")
        payload["nivel_confianza"] = 0.78 if all_categorias or payload["reglas_liquidacion"]["antiguedad"] else 0.48
        
        # Apply normalizations
        apply_payload_normalizations(payload)
        return payload

    # ========================================================================
    # PARA ESCALAS (kind == "scale")
    # ========================================================================
    local_categories = extract_scale_categories(lines_text, tables)

    # Mergear: specialized > generic > local
    all_categorias = (
        dedupe_records(specialized_parsed.get("categorias") or [], ("nombre", "rama"))
        + dedupe_records(generic_parsed.get("categorias") or [], ("nombre", "rama"))
        + local_categories
    )
    all_categorias = dedupe_records(all_categorias, ("nombre", "rama"))

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
        "categorias": all_categorias,
        "adicionales": [],
        "subsidios": dedupe_records(specialized_parsed.get("subsidios") or [], ("nombre", "fuente_textual")),
        "zonas": [],
        "no_remunerativos": no_remunerativos,
        "acuerdos": [item["fuente_textual"] for item in no_remunerativos],
        "montos": [
            {"nombre": item["nombre"], "monto": item["monto"], "fuente_textual": item["fuente_textual"]}
            for item in no_remunerativos
        ],
        "reglas_liquidacion": specialized_parsed.get("reglas_liquidacion") or {},
        "pendientes_revision": [],
        "alertas": [],
        "nivel_confianza": 0.52,
    }
    if not all_categorias:
        payload["alertas"].append("La escala OCR no devolvio categorias con basicos claros.")
    if not payload["vigencia"]:
        payload["pendientes_revision"].append("Confirmar vigencia exacta de la escala salarial.")
    payload["nivel_confianza"] = 0.84 if all_categorias else 0.46
    
    # Apply normalizations
    apply_payload_normalizations(payload)
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
    merged["estado"] = f"gemini_codex_{kind}" if primary else base.get("estado")

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
        "estado": "payload_gemini_codex_fusionado",
        "origen": {
            "proveedor": "Gemini + Codex + Parser local",
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


# ============================================================================
# CAPA 1: PARSER GENÉRICO PARA LÍNEAS SALARIALES
# ============================================================================


def _detect_branch_from_line(line: str) -> str | None:
    """
    Detecta si una línea sin monto es una rama/sección.
    Retorna el nombre de la rama o None si no es una rama válida.
    """
    normalized = normalize_text(line)
    text_compact = compact_text(line, 100)

    # Si tiene números, probablemente sea una escala, no una rama
    if re.search(r"\d", text_compact):
        return None

    # Ramas conocidas
    known_branches = (
        "auxilio mecanico",
        "administrativos",
        "maestranza",
        "operarios",
        "produccion",
        "logistica",
        "choferes",
        "tecnicos",
        "playeros",
        "gomeros",
        "lavadores",
        "expendedores",
        "combustibles",
        "engrasadores",
        "cerrajero",
        "electricista",
        "chapista",
        "pintor",
        "caños de escape",
        "expo",
        "serenos",
        "multiple",
        "multifuncionalidad",
    )

    # Buscar coincidencias con ramas conocidas
    for branch in known_branches:
        if branch in normalized:
            return text_compact

    # Si es una línea corta en mayúsculas/título que precede filas con montos
    if len(text_compact) < 80 and len(text_compact) > 5:
        if re.match(r"^[A-ZÁÉÍÓÚÑ]", text_compact):
            return text_compact

    return None


def _parse_salary_line(line: str, current_branch: str | None = None) -> tuple[str | None, list[float]] | tuple[str | None, str | None, list[float]]:
    """
    Intenta parsear una línea de escala salarial.
    Retorna (categoría_nombre, [montos]) o (rama_detectada, None, []) si detecta rama.
    """
    text = compact_text(line, 220)
    normalized = normalize_text(text)

    # Ignorar líneas muy cortas, URLs, fechas, etc
    if len(text) < 6:
        return None, []

    if re.search(r"https?://|www\.|@", normalized):
        return None, []

    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text):
        return None, []

    # Detectar ramas
    branch = _detect_branch_from_line(text)
    if branch:
        return branch, None, []

    # Extraer todos los números que se ven como montos
    # Patrón: $1.234,56 o 1234,56 o 1,234.56 o 1234.56
    money_pattern = r"(?:\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d{4,}(?:[.,]\d{2})?)"
    matches = re.finditer(money_pattern, text)
    montos: list[float] = []

    for match in matches:
        monto_text = match.group(1).replace("$", "").strip()
        # Normalizar el formato
        if "," in monto_text and "." in monto_text:
            monto_text = monto_text.replace(".", "").replace(",", ".")
        else:
            monto_text = monto_text.replace(",", ".")
        try:
            monto = float(monto_text)
            if monto > 0:
                montos.append(monto)
        except ValueError:
            pass

    if not montos:
        return None, []

    # Extraer la parte de texto antes del primer monto
    first_match = re.search(money_pattern, text)
    if first_match:
        category_text = text[: first_match.start()].strip()
    else:
        category_text = text.strip()

    category_text = re.sub(r"[-•*]\s*$", "", category_text).strip()

    if not category_text or len(category_text) < 3:
        return None, montos

    # Validar que sea un nombre de categoría probable
    if not is_probable_category_label(category_text):
        return None, montos

    return category_text, montos


def extract_generic_salary_lines(text: str) -> dict[str, Any]:
    """
    Parser genérico para detectar líneas salariales de cualquier convenio.

    Detecta:
    - Categorías con 1 a 4 montos
    - Ramas/secciones
    - Genera escalas con basico_mensual y adicional_1/2/3

    Retorna:
    {
        "categorias": [...],
        "escalas_salariales": [],
        "ramas_detectadas": [...]
    }
    """
    categorias: list[dict[str, Any]] = []
    escalas: list[dict[str, Any]] = []
    ramas_set: set[str] = set()
    current_branch: str | None = None

    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        if not line:
            continue

        parsed = _parse_salary_line(line, current_branch)

        if len(parsed) == 3:
            # Es una rama
            rama, _, _ = parsed
            if rama:
                current_branch = rama
                ramas_set.add(rama)
            continue

        categoria_nombre, montos = parsed

        if not categoria_nombre or not montos:
            continue

        if len(montos) > 4:
            # Si hay más de 4 montos, probablemente sea ruido
            # Tomar solo los primeros 4
            montos = montos[:4]

        # Crear categoría
        categoria_id = slugify(f"{current_branch}_{categoria_nombre}" if current_branch else categoria_nombre)
        categorias.append(
            {
                "id": categoria_id,
                "rama": current_branch,
                "nombre": categoria_nombre,
                "categoria": categoria_nombre,
                "descripcion": None,
                "fuente_textual": line,
                "requiere_revision": False,
            }
        )

        # Crear escala salarial
        basico = montos[0] if montos else None
        escala_id = slugify(f"escala_{current_branch}_{categoria_nombre}_{basico}" if current_branch else f"escala_{categoria_nombre}_{basico}")

        escala: dict[str, Any] = {
            "id": escala_id,
            "rama": current_branch,
            "categoria": categoria_nombre,
            "nombre": categoria_nombre,
            "basico_mensual": basico,
            "sueldo_mensual": basico,
            "valor": basico,
            "adicional_1": montos[1] if len(montos) > 1 else None,
            "adicional_2": montos[2] if len(montos) > 2 else None,
            "adicional_3": montos[3] if len(montos) > 3 else None,
            "columnas_detectadas": [],
            "tipo_valor": "mensual",
            "fuente_textual": line,
            "requiere_revision": len(montos) > 2,  # Marcar para revisión si hay múltiples montos
        }

        # Detectar nombres de columnas cercanos
        for keyword in ("articulo 11", "multifuncionalidad", "no remunerativo", "adicional", "comision"):
            if keyword in normalize_text(line):
                escala["columnas_detectadas"].append(keyword)

        escalas.append(escala)

    # Deduplicar
    categorias = dedupe_records(categorias, ("nombre", "rama"))
    escalas = dedupe_records(escalas, ("categoria", "rama", "basico_mensual"))

    return {
        "categorias": categorias,
        "escalas_salariales": escalas,
        "ramas_detectadas": sorted(list(ramas_set)),
    }


# ============================================================================
# CAPA 2: PARSERS ESPECIALIZADOS
# ============================================================================


class SpecializedParser(ABC):
    """Base class for specialized CCT parsers."""

    @abstractmethod
    def can_handle(self, text: str) -> bool:
        """Check if this parser can handle the given text."""
        pass

    @abstractmethod
    def parse(self, text: str) -> dict[str, Any]:
        """Parse the text and return structured data."""
        pass


class SmatAcaParser(SpecializedParser):
    """Specialized parser for CCT 454/2006 SMATA - ACA."""

    def can_handle(self, text: str) -> bool:
        """Detect if text is from SMATA ACA CCT."""
        normalized = normalize_text(text)
        indicators = [
            "454/2006" in normalized or "454 / 2006" in normalized,
            "smata" in normalized,
            ("aca" in normalized or "automovil club argentino" in normalized),
            "anexo smata" in normalized,
        ]
        # Need at least 2 indicators or a very explicit one
        return sum(indicators) >= 2 or "anexo smata" in normalized

    def _detect_current_branch(self, line: str, known_branches: list[str], current_branch: str | None) -> str | None:
        """Detect if line is a branch header."""
        normalized = normalize_text(line)
        for branch in known_branches:
            if normalize_text(branch) in normalized:
                return line.strip()
        return current_branch

    def _extract_smata_subsidios(self, text: str) -> list[dict[str, Any]]:
        """Extract SMATA-specific subsidios."""
        subsidios_map = {
            "casamiento": 280,
            "nacimiento": 280,
            "fallecimiento hijos": 560,
            "fallecimiento conyugal": 560,
            "fallecimiento hermano": 450,
            "idiomas": 112,
            "titulo": 110,
            "discapacitados": 112,
            "caja": 220,
        }

        subsidios: list[dict[str, Any]] = []
        for nombre_key, monto_default in subsidios_map.items():
            for raw_line in text.splitlines():
                line = compact_text(raw_line, 220)
                if nombre_key.lower() not in normalize_text(line):
                    continue

                monto_match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*$", line)
                monto = to_number(monto_match.group(1)) if monto_match else monto_default

                subsidios.append(
                    {
                        "nombre": nombre_key.replace("_", " ").title(),
                        "tipo": "monto_fijo",
                        "valor": monto,
                        "fuente_textual": line,
                    }
                )
                break

        return dedupe_records(subsidios, ("nombre", "fuente_textual"))

    def _extract_smata_antiguedad(self, text: str) -> dict[str, Any] | None:
        """Extract SMATA-specific antiguedad rule."""
        pattern = r"adicional\s+por\s+antig[üu]edad\s+sobre\s+salario\s+(?:de\s+)?conveni?o?\s+de\s*\$?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)"
        match = re.search(pattern, normalize_text(text), re.I)

        if not match:
            return None

        base_monto_text = match.group(1).replace(".", "").replace(",", ".")
        try:
            base_monto = float(base_monto_text)
        except ValueError:
            return None

        # Construir escala de 1 a 30 años
        escala = [{"anio": i, "porcentaje": i} for i in range(1, 31)]

        return {
            "tipo": "porcentaje_por_anio",
            "base_monto": base_monto,
            "porcentaje_por_anio": 1,
            "escala": escala,
            "fuente_textual": pick_match(text, r"(adicional\s+por\s+antig[üu]edad[\s\S]{0,280})", 1),
        }

    def _extract_smata_zona(self, text: str) -> dict[str, Any] | None:
        """Extract SMATA zone desfavorable rule."""
        # Look for Art. 56 or explicit 30% mention
        pattern = r"(?:art\.?\s*56|condiciones especiales|patagoni[\s\S]{0,200}?)(treinta\s+por\s+ciento|30\s*%)"
        match = re.search(pattern, normalize_text(text), re.I)

        if not match:
            return None

        provinces = ["Neuquén", "Río Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"]

        return {
            "porcentaje": 30,
            "provincias": provinces,
            "fuente_textual": pick_match(text, r"((?:art\.?\s*56|condiciones especiales)[\s\S]{0,280})", 1),
        }

    def parse(self, text: str) -> dict[str, Any]:
        """Parse SMATA ACA CCT text."""
        known_branches = [
            "Auxilio Mecánico",
            "Playeros y expendedores de combustibles",
            "Mecánico-ACA",
            "Cerrajero",
            "Electricista",
            "Chapista",
            "Pintor",
            "Caños de escape",
            "Gomeros",
            "Lavadores",
            "Engrasadores",
            "Administrativos - ExpoACA",
            "Maestranza - Choferes y Serenos",
            "Operario Múltiple",
        ]

        categorias: list[dict[str, Any]] = []
        escalas: list[dict[str, Any]] = []
        current_branch: str | None = None

        for raw_line in text.splitlines():
            line = compact_text(raw_line, 220)
            if not line:
                continue

            # Check if line is a branch
            new_branch = self._detect_current_branch(line, known_branches, current_branch)
            if new_branch and new_branch != current_branch:
                current_branch = new_branch
                continue

            # Try to parse salary line
            parsed = _parse_salary_line(line, current_branch)
            if len(parsed) == 3:
                continue

            categoria_nombre, montos = parsed
            if not categoria_nombre or not montos:
                continue

            if len(montos) > 4:
                montos = montos[:4]

            # Create category
            categoria_id = slugify(f"{current_branch}_{categoria_nombre}" if current_branch else categoria_nombre)
            categorias.append(
                {
                    "id": categoria_id,
                    "rama": current_branch,
                    "nombre": categoria_nombre,
                    "categoria": categoria_nombre,
                    "descripcion": None,
                    "fuente_textual": line,
                    "requiere_revision": False,
                }
            )

            # Create salary scale with SMATA-specific column names
            escala_id = slugify(f"escala_smata_{current_branch}_{categoria_nombre}_{montos[0]}" if current_branch else f"escala_smata_{categoria_nombre}_{montos[0]}")

            escala: dict[str, Any] = {
                "id": escala_id,
                "rama": current_branch,
                "categoria": categoria_nombre,
                "nombre": categoria_nombre,
                "basico_mensual": montos[0] if montos else None,
                "sueldo_mensual": montos[0] if montos else None,
                "valor": montos[0] if montos else None,
                "adicional_1": None,
                "adicional_2": None,
                "adicional_3": None,
                "columnas_detectadas": [],
                "tipo_valor": "mensual",
                "fuente_textual": line,
                "requiere_revision": False,
            }

            # Assign column names based on position and context
            if len(montos) > 1:
                escala["articulo_11"] = montos[1]
                escala["columnas_detectadas"].append("articulo_11")
            if len(montos) > 2:
                escala["multifuncionalidad"] = montos[2]
                escala["columnas_detectadas"].append("multifuncionalidad")
            if len(montos) > 3:
                escala["adicional_3"] = montos[3]
                escala["columnas_detectadas"].append("adicional_3")

            escalas.append(escala)

        subsidios = self._extract_smata_subsidios(text)
        antiguedad = self._extract_smata_antiguedad(text)
        zona = self._extract_smata_zona(text)

        return {
            "categorias": dedupe_records(categorias, ("nombre", "rama")),
            "escalas_salariales": dedupe_records(escalas, ("categoria", "rama", "basico_mensual")),
            "subsidios": subsidios,
            "antiguedad": antiguedad,
            "zona_desfavorable": zona,
        }


# Registry of all specialized parsers
SPECIALIZED_PARSERS: list[SpecializedParser] = [
    SmatAcaParser(),
]


def run_specialized_parsers(text: str) -> dict[str, Any]:
    """Run all applicable specialized parsers and merge results."""
    results: dict[str, Any] = {
        "categorias": [],
        "escalas_salariales": [],
        "subsidios": [],
        "adicionales": [],
        "reglas_liquidacion": {},
    }

    for parser in SPECIALIZED_PARSERS:
        if not parser.can_handle(text):
            continue

        try:
            parsed = parser.parse(text)
            results["categorias"].extend(parsed.get("categorias") or [])
            results["escalas_salariales"].extend(parsed.get("escalas_salariales") or [])
            results["subsidios"].extend(parsed.get("subsidios") or [])

            # Agregar reglas específicas
            if parsed.get("antiguedad"):
                results["reglas_liquidacion"]["antiguedad"] = parsed["antiguedad"]
            if parsed.get("zona_desfavorable"):
                results["reglas_liquidacion"]["zona_desfavorable"] = parsed["zona_desfavorable"]

        except Exception as e:
            # Log error but continue with other parsers
            print(f"Error in parser {parser.__class__.__name__}: {e}")

    # Deduplicar resultados
    results["categorias"] = dedupe_records(results["categorias"], ("nombre", "rama"))
    results["escalas_salariales"] = dedupe_records(results["escalas_salariales"], ("categoria", "rama", "basico_mensual"))
    results["subsidios"] = dedupe_records(results["subsidios"], ("nombre", "fuente_textual"))

    return results


# ============================================================================
# PARSERS LOCALES REFORZADOS
# ============================================================================


SMATA_ACA_BRANCHES = [
    "Auxilio Mecánico",
    "Playeros y expendedores de combustibles",
    "Mecánico-ACA",
    "Cerrajero",
    "Electricista",
    "Chapista",
    "Pintor",
    "Caños de escape",
    "Gomeros",
    "Lavadores",
    "Engrasadores",
    "Administrativos - ExpoACA",
    "Maestranza - Choferes y Serenos",
    "Operario Múltiple",
]


def _matches_smata_aca(text: str) -> bool:
    normalized = normalize_text(text)
    indicators = [
        "454/2006" in normalized or "454 / 2006" in normalized,
        "smata" in normalized,
        "aca" in normalized or "automovil club argentino" in normalized,
        "anexo smata" in normalized,
    ]
    return sum(indicators) >= 2 or "454/2006" in normalized or "anexo smata" in normalized


def extract_antiguedad_rule(text: str) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    if "antig" not in normalized:
        return None

    fuente = pick_match(text, r"(antig[\w\s%$.,/-]{0,420})", 1)
    percentage = to_number(pick_match(text, r"antig[\w\s%$.,/-]{0,220}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%")) or 1
    base_monto_text = pick_match(
        pick_match(
            text,
            r"antig[\w\s%$.,/-]{0,220}?(?:salario|sueldo|basico|b[aá]sico)[\w\s%$.,/-]{0,40}?\$?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
        )
    )

    escala_matches = re.findall(r"\b([1-9]|[12]\d|30)\s*(?:anos?|a(?:n|ñ)o?s?)?\s*(\d{1,2})\s*%", normalized, re.I)
    escala: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    for anio_text, porcentaje_text in escala_matches:
        anio = int(anio_text)
        porcentaje_item = int(porcentaje_text)
        if 1 <= anio <= 30 and porcentaje_item > 0 and anio not in seen_years:
            seen_years.add(anio)
            escala.append({"anio": anio, "porcentaje": porcentaje_item})

    if not escala and percentage:
        escala = [{"anio": i, "porcentaje": i * percentage} for i in range(1, 31)]

    return {
        "tipo": "porcentaje_por_anio",
        "base_monto": base_monto,
        "porcentaje_por_anio": percentage,
        "escala": escala or None,
        "fuente_textual": fuente,
    }


def extract_zone_rule(text: str) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    provinces = ["Neuquén", "Río Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"]
    province_tokens = ["neuquen", "rio negro", "chubut", "santa cruz", "tierra del fuego"]
    if not any(token in normalized for token in province_tokens):
        return None

    has_art_56 = bool(re.search(r"\bart\.?\s*56\b", normalized))
    has_thirty = bool(re.search(r"\b30\s*%|\btreinta\s+por\s+ciento\b", normalized, re.I))
    percentage = to_number(pick_match(text, r"(?:zona|patagoni|\bneuquen\b|art\.?\s*56)[\s\S]{0,220}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%"))
    if has_thirty and (has_art_56 or percentage in (None, 0)):
        percentage = 30

    return {
        "porcentaje": percentage or 0,
        "provincias": provinces,
        "fuente_textual": pick_match(text, r"((?:art\.?\s*56|zona|condiciones especiales|patagoni)[\s\S]{0,320})", 1),
    }


def extract_subsidios(text: str) -> list[dict[str, Any]]:
    patterns = [
        (r"casamiento", "Casamiento", None),
        (r"nacimiento", "Nacimiento", None),
        (r"adopcion", "Adopcion", None),
        (r"fallecimiento[\s:/-]+(?:hijos?|hijo|conyuge|c[oó]nyuge)", "Fallecimiento hijos/cónyuge", 560),
        (r"fallecimiento[\s:/-]+(?:padres?|padres?\s+politicos|padres?\s+pol[ií]ticos)", "Fallecimiento padres/padres políticos", 560),
        (r"fallecimiento[\s:/-]+herman", "Fallecimiento hermano", 450),
        (r"idiomas?\s+extranjeros?", "Idiomas extranjeros", 112),
        (r"titulo\s+habi", "Título habilitante", 110),
        (r"hijos?\s+discapacitados?", "Hijos discapacitados", 112),
        (r"empleados?\s+de\s+caja", "Empleados de caja", 220),
        (r"fallecimiento", "Fallecimiento", None),
    ]
    items: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        lowered = normalize_text(line)
        matched: tuple[str, int | None] | None = None
        for pattern, label, fallback_amount in patterns:
            if re.search(pattern, lowered, re.I):
                matched = (label, fallback_amount)
                break
        if not matched:
            continue
        amount = to_number(pick_match(line, r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*$")) or matched[1]
        if amount is None:
            continue
        items.append({"nombre": matched[0], "tipo": "monto_fijo", "valor": amount, "fuente_textual": line})
    return dedupe_records(items, ("nombre", "fuente_textual"))


def _detect_branch_from_line(line: str) -> str | None:
    normalized = normalize_text(line)
    text_compact = compact_text(line, 100)
    if re.search(r"\d", text_compact):
        return None
    if any(token in normalized for token in ("anexo", "escalas salariales", "convenio colectivo", "boletin oficial", "art.")):
        return None
    known_branches = (
        "auxilio mecanico",
        "administrativos",
        "maestranza",
        "operario multiple",
        "operarios",
        "produccion",
        "logistica",
        "choferes",
        "tecnicos",
        "playeros",
        "gomeros",
        "lavadores",
        "expendedores",
        "combustibles",
        "engrasadores",
        "cerrajero",
        "electricista",
        "chapista",
        "pintor",
        "canos de escape",
        "expoaca",
        "serenos",
        "multiple",
        "mecanico-aca",
        "mecanico aca",
    )
    for branch in known_branches:
        if branch in normalized:
            return text_compact
    if 5 < len(text_compact) < 80 and re.match(r"^[A-ZÃÃ‰ÃÃ“ÃšÃ‘]", text_compact):
        return text_compact
    return None


def _parse_salary_line(line: str, current_branch: str | None = None) -> tuple[str | None, list[float]] | tuple[str | None, str | None, list[float]]:
    text = compact_text(line, 220)
    normalized = normalize_text(text)
    if len(text) < 6:
        return None, []
    if re.search(r"https?://|www\.|@", normalized):
        return None, []
    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text):
        return None, []

    branch = _detect_branch_from_line(text)
    if branch:
        return branch, None, []

    money_pattern = r"(?:\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d{4,}(?:[.,]\d{2})?)"
    matches = list(re.finditer(money_pattern, text))
    montos: list[float] = []
    for match in matches:
        monto_text = match.group(1).replace("$", "").strip()
        if "," in monto_text and "." in monto_text:
            monto_text = monto_text.replace(".", "").replace(",", ".")
        else:
            monto_text = monto_text.replace(",", ".")
        try:
            monto = float(monto_text)
        except ValueError:
            continue
        if monto > 0:
            montos.append(monto)
    if not montos:
        return None, []

    first_match = matches[0] if matches else None
    category_text = text[: first_match.start()].strip() if first_match else text.strip()
    category_text = re.sub(r"[-â€¢*]\s*$", "", category_text).strip()
    if not category_text or len(category_text) < 3:
        return None, montos
    if not is_probable_category_label(category_text):
        return None, montos
    return category_text, montos


def _detect_column_headers(line: str) -> list[str]:
    normalized = normalize_text(line)
    headers: list[str] = []
    if any(token in normalized for token in ("articulo 11", "art. 11", "art 11")):
        headers.append("articulo_11")
    if "multifuncionalidad" in normalized:
        headers.append("multifuncionalidad")
    if "no remunerativ" in normalized:
        headers.append("no_remunerativo")
    if "adicional" in normalized:
        headers.append("adicional")
    if "comision" in normalized:
        headers.append("comision")
    return headers


def _assign_detected_columns(escala: dict[str, Any], montos: list[float], column_headers: list[str]) -> None:
    for index, monto in enumerate(montos[1:], start=1):
        header = column_headers[index - 1] if index - 1 < len(column_headers) else None
        fallback_key = f"adicional_{index}"
        target_key = header or fallback_key
        if header:
            escala.setdefault("columnas_detectadas", []).append(header)
        escala[target_key] = monto


def extract_generic_salary_lines(text: str) -> dict[str, Any]:
    categorias: list[dict[str, Any]] = []
    escalas: list[dict[str, Any]] = []
    ramas_set: set[str] = set()
    current_branch: str | None = None
    current_column_headers: list[str] = []
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        if not line:
            continue
        if not re.search(r"\d", line):
            detected_headers = _detect_column_headers(line)
            if detected_headers:
                current_column_headers = detected_headers

        parsed = _parse_salary_line(line, current_branch)
        if len(parsed) == 3:
            rama, _, _ = parsed
            if rama:
                current_branch = rama
                ramas_set.add(rama)
            continue

        categoria_nombre, montos = parsed
        if not categoria_nombre or not montos:
            continue

        montos = montos[:4]
        basico = montos[0]
        categorias.append(
            {
                "id": slugify(f"{current_branch}_{categoria_nombre}" if current_branch else categoria_nombre),
                "rama": current_branch,
                "nombre": categoria_nombre,
                "categoria": categoria_nombre,
                "descripcion": None,
                "basico_mensual": basico,
                "sueldo_mensual": basico,
                "valor": basico,
                "valor_hora": None,
                "tipo_valor": "mensual",
                "grupo": current_branch,
                "fuente_textual": line,
                "requiere_revision": False,
                "parser_origen": "generico_local",
            }
        )

        escala = {
            "id": slugify(f"escala_{current_branch}_{categoria_nombre}_{basico}" if current_branch else f"escala_{categoria_nombre}_{basico}"),
            "rama": current_branch,
            "categoria": categoria_nombre,
            "nombre": categoria_nombre,
            "basico_mensual": basico,
            "sueldo_mensual": basico,
            "valor": basico,
            "valor_hora": None,
            "columnas_detectadas": [],
            "tipo_valor": "mensual",
            "fuente_textual": line,
            "requiere_revision": len(montos) > 2 and not current_column_headers,
            "parser_origen": "generico_local",
        }
        _assign_detected_columns(escala, montos, current_column_headers)
        escalas.append(escala)

    return {
        "categorias": dedupe_records(categorias, ("nombre", "rama")),
        "escalas_salariales": dedupe_records(escalas, ("categoria", "rama", "basico_mensual")),
        "ramas_detectadas": sorted(ramas_set),
    }


def extract_smata_aca_salary_annex(text: str) -> dict[str, Any]:
    if not _matches_smata_aca(text):
        return {"categorias": [], "escalas_salariales": [], "ramas_detectadas": []}

    branch_lookup = {normalize_text(branch): branch for branch in SMATA_ACA_BRANCHES}
    categorias: list[dict[str, Any]] = []
    escalas: list[dict[str, Any]] = []
    ramas_detectadas: set[str] = set()
    current_branch: str | None = None
    annex_active = False
    for raw_line in text.splitlines():
        line = compact_text(raw_line, 220)
        if not line:
            continue
        normalized = normalize_text(line)
        if "anexo smata" in normalized or "escalas salariales" in normalized:
            annex_active = True
            continue
        if not annex_active and any(branch_key in normalized for branch_key in branch_lookup):
            annex_active = True
        if not annex_active:
            continue

        matched_branch = next((canonical for branch_key, canonical in branch_lookup.items() if branch_key in normalized), None)
        if matched_branch and not re.search(r"\d", line):
            current_branch = matched_branch
            ramas_detectadas.add(matched_branch)
            continue

        parsed = _parse_salary_line(line, current_branch)
        if len(parsed) == 3:
            rama, _, _ = parsed
            if rama:
                current_branch = rama
                ramas_detectadas.add(rama)
            continue

        categoria_nombre, montos = parsed
        if not categoria_nombre or not montos:
            continue

        montos = montos[:4]
        basico = montos[0]
        categorias.append(
            {
                "id": slugify(f"smata_{current_branch}_{categoria_nombre}" if current_branch else f"smata_{categoria_nombre}"),
                "rama": current_branch,
                "nombre": categoria_nombre,
                "categoria": categoria_nombre,
                "descripcion": None,
                "basico_mensual": basico,
                "sueldo_mensual": basico,
                "valor": basico,
                "valor_hora": None,
                "tipo_valor": "mensual",
                "grupo": current_branch,
                "fuente_textual": line,
                "requiere_revision": False,
                "parser_origen": "smata_aca",
            }
        )

        escala: dict[str, Any] = {
            "id": slugify(f"smata_escala_{current_branch}_{categoria_nombre}_{basico}" if current_branch else f"smata_escala_{categoria_nombre}_{basico}"),
            "rama": current_branch,
            "categoria": categoria_nombre,
            "nombre": categoria_nombre,
            "basico_mensual": basico,
            "sueldo_mensual": basico,
            "valor": basico,
            "valor_hora": None,
            "columnas_detectadas": [],
            "tipo_valor": "mensual",
            "fuente_textual": line,
            "requiere_revision": False,
            "parser_origen": "smata_aca",
        }
        if len(montos) > 1:
            escala["articulo_11"] = montos[1]
            escala["columnas_detectadas"].append("articulo_11")
        if len(montos) > 2:
            escala["multifuncionalidad"] = montos[2]
            escala["columnas_detectadas"].append("multifuncionalidad")
        if len(montos) > 3:
            escala["adicional_3"] = montos[3]
            escala["columnas_detectadas"].append("adicional_3")
        escalas.append(escala)

    return {
        "categorias": dedupe_records(categorias, ("nombre", "rama")),
        "escalas_salariales": dedupe_records(escalas, ("categoria", "rama", "basico_mensual")),
        "ramas_detectadas": sorted(ramas_detectadas),
    }


class SmatAcaParser(SpecializedParser):
    """Specialized parser for CCT 454/2006 SMATA - ACA."""

    def can_handle(self, text: str) -> bool:
        return _matches_smata_aca(text)

    def parse(self, text: str) -> dict[str, Any]:
        annex = extract_smata_aca_salary_annex(text)
        return {
            "categorias": annex.get("categorias") or [],
            "escalas_salariales": annex.get("escalas_salariales") or [],
            "subsidios": extract_subsidios(text),
            "antiguedad": extract_antiguedad_rule(text),
            "zona_desfavorable": extract_zone_rule(text),
        }


SPECIALIZED_PARSERS = [SmatAcaParser()]


def run_specialized_parsers(text: str) -> dict[str, Any]:
    results: dict[str, Any] = {
        "categorias": [],
        "escalas_salariales": [],
        "subsidios": [],
        "adicionales": [],
        "reglas_liquidacion": {},
    }
    for parser in SPECIALIZED_PARSERS:
        if not parser.can_handle(text):
            continue
        try:
            parsed = parser.parse(text)
        except Exception:
            continue
        results["categorias"].extend(parsed.get("categorias") or [])
        results["escalas_salariales"].extend(parsed.get("escalas_salariales") or [])
        results["subsidios"].extend(parsed.get("subsidios") or [])
        if parsed.get("antiguedad"):
            results["reglas_liquidacion"]["antiguedad"] = parsed["antiguedad"]
        if parsed.get("zona_desfavorable"):
            results["reglas_liquidacion"]["zona_desfavorable"] = parsed["zona_desfavorable"]
    results["categorias"] = dedupe_records(results["categorias"], ("nombre", "rama"))
    results["escalas_salariales"] = dedupe_records(results["escalas_salariales"], ("categoria", "rama", "basico_mensual"))
    results["subsidios"] = dedupe_records(results["subsidios"], ("nombre", "fuente_textual"))
    return results


def parse_document(ocr_payload: dict[str, Any], *, kind: str, file_name: str, provider: str = "PDF local + Parser") -> dict[str, Any]:
    markdown = str(ocr_payload.get("markdown") or "")
    plain_text = str(ocr_payload.get("text") or strip_markdown(markdown))
    tables = list(ocr_payload.get("tables") or extract_markdown_tables(markdown))
    lines_text = "\n".join(page.get("markdown", "") for page in ocr_payload.get("pages", []) if isinstance(page, dict)) or markdown
    working_text = lines_text or plain_text or markdown

    generic_parsed = extract_generic_salary_lines(working_text)
    smata_parsed = extract_smata_aca_salary_annex(working_text)
    specialized_parsed = run_specialized_parsers(working_text)

    merged_categories = (smata_parsed.get("categorias") or []) + (specialized_parsed.get("categorias") or []) + (generic_parsed.get("categorias") or [])
    merged_scales = (smata_parsed.get("escalas_salariales") or []) + (specialized_parsed.get("escalas_salariales") or []) + (generic_parsed.get("escalas_salariales") or [])
    merged_subsidios = (specialized_parsed.get("subsidios") or []) + extract_subsidios(working_text)

    if kind == "cct":
        local_categories = extract_cct_categories(working_text, tables)
        jornada = detect_hours(plain_text or working_text)
        zona_rule = (specialized_parsed.get("reglas_liquidacion") or {}).get("zona_desfavorable") or extract_zone_rule(working_text)
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
                "nombre": detect_convenio_name(working_text, file_name),
                "actividad": detect_activity(plain_text or working_text),
                "ambito": detect_ambit(plain_text or working_text),
                "cct_numero": extract_cct_number(plain_text or working_text),
                "vigencia_detectada": detect_vigencia(plain_text or working_text),
            },
            "parametros": jornada,
            "jornada": jornada,
            "vigencia": detect_vigencia(plain_text or working_text),
            "categorias": merged_categories + local_categories,
            "escalas_salariales": merged_scales,
            "adicionales": extract_additionals(working_text),
            "subsidios": merged_subsidios,
            "zonas": [zona_rule] if zona_rule else [],
            "reglas_liquidacion": {
                "antiguedad": (specialized_parsed.get("reglas_liquidacion") or {}).get("antiguedad") or extract_antiguedad_rule(working_text),
                "presentismo": extract_presentismo_rule(working_text),
                "zona_desfavorable": zona_rule,
                "horas_extra": extract_extra_hours_rule(working_text),
                "licencias": extract_licenses(working_text),
                "articulos_relevantes": extract_relevant_articles(working_text),
                "no_remunerativos": [],
            },
            "pendientes_revision": [],
            "alertas": [],
            "nivel_confianza": 0.78 if merged_categories or merged_scales else 0.48,
        }
        if not payload["categorias"]:
            payload["pendientes_revision"].append("No se detectaron categorias claras en el convenio; revisar OCR y estructura.")
        if not payload["convenio"]["cct_numero"]:
            payload["pendientes_revision"].append("Confirmar el numero de CCT del documento.")
        if not jornada.get("horas_semanales") and not jornada.get("horas_mensuales"):
            payload["pendientes_revision"].append("Confirmar jornada legal y divisor mensual.")
        clean_final_payload(payload)
        return payload

    local_categories = extract_scale_categories(working_text, tables)
    no_remunerativos = extract_no_remunerativos(working_text)
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
            "nombre": detect_convenio_name(working_text, file_name),
            "vigencia_detectada": detect_vigencia(plain_text or working_text),
        },
        "vigencia": detect_vigencia(plain_text or working_text),
        "categorias": merged_categories + local_categories,
        "escalas_salariales": merged_scales,
        "adicionales": [],
        "subsidios": merged_subsidios,
        "zonas": [],
        "no_remunerativos": no_remunerativos,
        "acuerdos": [item["fuente_textual"] for item in no_remunerativos],
        "montos": [{"nombre": item["nombre"], "monto": item["monto"], "fuente_textual": item["fuente_textual"]} for item in no_remunerativos],
        "reglas_liquidacion": specialized_parsed.get("reglas_liquidacion") or {},
        "pendientes_revision": [],
        "alertas": [],
        "nivel_confianza": 0.84 if merged_categories or merged_scales else 0.46,
    }
    if not payload["categorias"] and not payload["escalas_salariales"]:
        payload["alertas"].append("La escala OCR no devolviÃ³ categorÃ­as con bÃ¡sicos claros.")
    if not payload["vigencia"]:
        payload["pendientes_revision"].append("Confirmar vigencia exacta de la escala salarial.")
    clean_final_payload(payload)
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
    cloned.setdefault("escalas_salariales", [])
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
    merged["categorias"] = (overlay.get("categorias") or []) + (base.get("categorias") or [])
    merged["escalas_salariales"] = (overlay.get("escalas_salariales") or []) + (base.get("escalas_salariales") or [])
    merged["adicionales"] = (overlay.get("adicionales") or []) + (base.get("adicionales") or [])
    merged["subsidios"] = (overlay.get("subsidios") or []) + (base.get("subsidios") or [])
    merged["zonas"] = [item for item in (overlay.get("zonas") or []) + (base.get("zonas") or []) if has_meaningful_value(item)]
    merged["pendientes_revision"] = dedupe_strings([*(base.get("pendientes_revision") or []), *(overlay.get("pendientes_revision") or [])])
    merged["alertas"] = dedupe_strings([*(base.get("alertas") or []), *(overlay.get("alertas") or [])])
    merged["estado"] = f"gemini_codex_{kind}" if primary else base.get("estado")
    if kind == "scale":
        merged["no_remunerativos"] = (overlay.get("no_remunerativos") or []) + (base.get("no_remunerativos") or [])
        merged["acuerdos"] = dedupe_strings([*(base.get("acuerdos") or []), *(overlay.get("acuerdos") or [])])
        merged["montos"] = (overlay.get("montos") or []) + (base.get("montos") or [])
    clean_final_payload(merged)
    return merged


# ============================================================================
# DEDUPLICACIÓN ROBUSTA
# ============================================================================


def _merge_categoria_pair(cat1: dict[str, Any], cat2: dict[str, Any]) -> dict[str, Any]:
    """Merge two category records, keeping the most complete one."""
    # Prefer the one with more non-null fields
    fields1 = sum(1 for v in cat1.values() if has_meaningful_value(v))
    fields2 = sum(1 for v in cat2.values() if has_meaningful_value(v))
    if fields2 > fields1:
        cat1, cat2 = cat2, cat1
    # Overlay cat2 onto cat1 for missing fields
    merged = dict(cat1)
    for key, value in cat2.items():
        if not has_meaningful_value(merged.get(key)) and has_meaningful_value(value):
            merged[key] = value
    return merged


def _merge_escala_pair(esc1: dict[str, Any], esc2: dict[str, Any]) -> dict[str, Any]:
    """Merge two escala records, preferring the one with more complete column info."""
    # Prefer escala with more columnas_detectadas or more populated fields
    cols1 = len(esc1.get("columnas_detectadas") or [])
    cols2 = len(esc2.get("columnas_detectadas") or [])
    if cols2 > cols1:
        esc1, esc2 = esc2, esc1
    merged = dict(esc1)
    # Copy over column names if not present
    for key in ("articulo_11", "multifuncionalidad", "adicional_1", "adicional_2", "adicional_3"):
        if not has_meaningful_value(merged.get(key)) and has_meaningful_value(esc2.get(key)):
            merged[key] = esc2[key]
    # Merge columnas_detectadas
    cols = list(set((merged.get("columnas_detectadas") or []) + (esc2.get("columnas_detectadas") or [])))
    merged["columnas_detectadas"] = cols
    return merged


def dedupe_robust_categorias(categorias: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Robust deduplication for categories.
    - Merges categories with same (rama, nombre)
    - Keeps the most complete record
    """
    if not categorias:
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for cat in categorias:
        rama = normalize_text(cat.get("rama") or "")
        nombre = normalize_text(cat.get("nombre") or "")
        key = f"{rama}|{nombre}"
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(cat)

    result: list[dict[str, Any]] = []
    for key, group in grouped.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            merged = group[0]
            for item in group[1:]:
                merged = _merge_categoria_pair(merged, item)
            result.append(merged)

    return result


def dedupe_robust_escalas(escalas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Robust deduplication for salary scales.
    - Merges scales with same (rama, categoria, basico_mensual)
    - Keeps the one with better column information
    """
    if not escalas:
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for esc in escalas:
        rama = normalize_text(esc.get("rama") or "")
        categoria = normalize_text(esc.get("categoria") or esc.get("nombre") or "")
        basico = esc.get("basico_mensual")
        key = f"{rama}|{categoria}|{basico}"
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(esc)

    result: list[dict[str, Any]] = []
    for key, group in grouped.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            merged = group[0]
            for item in group[1:]:
                merged = _merge_escala_pair(merged, item)
            result.append(merged)

    return result


def clean_useless_additionals(payload: dict[str, Any]) -> None:
    """
    Remove useless adicionales that are duplicated by structured rules.
    Modifies payload in-place.
    """
    adicionales = payload.get("adicionales") or []
    reglas = payload.get("reglas_liquidacion") or {}
    subsidios = payload.get("subsidios") or []

    # Create a set of nombre normals from reglas
    regla_norms = set()
    if reglas.get("antiguedad"):
        regla_norms.add("antiguedad")
    if reglas.get("presentismo"):
        regla_norms.add("presentismo")
    if reglas.get("zona_desfavorable"):
        regla_norms.add("zona desfavorable")

    # Create a set of subsidios names
    subsidio_norms = set(normalize_text(s.get("nombre") or "") for s in subsidios if s.get("valor"))

    # Filter out bad adicionales
    cleaned: list[dict[str, Any]] = []
    for item in adicionales:
        nombre_norm = normalize_text(item.get("nombre") or "")

        # Remove if it's a rule duplicate with no value
        if nombre_norm in regla_norms and not has_meaningful_value(item.get("valor")):
            continue

        # Remove if it's a subsidio duplicate with no value
        if nombre_norm in subsidio_norms and not has_meaningful_value(item.get("valor")):
            continue

        cleaned.append(item)

    payload["adicionales"] = cleaned


def clean_useless_subsidios(payload: dict[str, Any]) -> None:
    """
    Remove subsidios with null valor if the same concept exists with a value.
    Modifies payload in-place.
    """
    subsidios = payload.get("subsidios") or []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for sub in subsidios:
        nombre_norm = normalize_text(sub.get("nombre") or "")
        if nombre_norm not in grouped:
            grouped[nombre_norm] = []
        grouped[nombre_norm].append(sub)

    cleaned: list[dict[str, Any]] = []
    for nombre_norm, group in grouped.items():
        # Sort by having value first
        group.sort(key=lambda x: not has_meaningful_value(x.get("valor")))
        # Keep only the first (best) one
        if group:
            cleaned.append(group[0])

    payload["subsidios"] = cleaned


def normalize_zona_desfavorable(payload: dict[str, Any]) -> None:
    """
    Fix zone desfavorable: never allow 0% if another source has a real percentage.
    Modifies payload in-place.
    """
    zona_rule = payload.get("reglas_liquidacion", {}).get("zona_desfavorable")
    if not zona_rule:
        return

    # If porcentaje is 0 or missing, look for better info
    porcentaje = zona_rule.get("porcentaje")
    if not porcentaje or porcentaje == 0:
        # Search in the text for explicit percentages
        text_source = zona_rule.get("fuente_textual", "")
        match = re.search(r"(?:treinta|30)\s*(?:%|por\s+ciento)", normalize_text(text_source), re.I)
        if match:
            zona_rule["porcentaje"] = 30

    # Never return 0 if source mentions a percentage
    if zona_rule.get("porcentaje") == 0:
        fuente = normalize_text(zona_rule.get("fuente_textual") or "")
        if re.search(r"\d{1,2}\s*%|por\s+ciento", fuente):
            # Extract percentage
            percent_match = re.search(r"(\d{1,2})\s*(?:%|por\s+ciento)", fuente, re.I)
            if percent_match:
                zona_rule["porcentaje"] = int(percent_match.group(1))


def normalize_antiguedad_rule(payload: dict[str, Any]) -> None:
    """
    Fix antiguedad rule to ensure it has base_monto and escala.
    Modifies payload in-place.
    """
    antig_rule = payload.get("reglas_liquidacion", {}).get("antiguedad")
    if not antig_rule:
        return

    # If no base_monto, try to detect it from text
    if not antig_rule.get("base_monto"):
        texto = antig_rule.get("fuente_textual", "")
        match = re.search(r"\$?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", texto)
        if match:
            monto_text = match.group(1).replace(".", "").replace(",", ".")
            try:
                antig_rule["base_monto"] = float(monto_text)
            except ValueError:
                pass

    # If no escala, generate 1-30 years
    if not antig_rule.get("escala"):
        porcentaje_per_year = antig_rule.get("porcentaje_por_anio") or 1
        antig_rule["escala"] = [{"anio": i, "porcentaje": i * porcentaje_per_year} for i in range(1, 31)]


def normalize_presentismo(payload: dict[str, Any]) -> None:
    """
    Ensure presentismo is not marked as active if it's only a future commitment.
    Modifies payload in-place.
    """
    presentismo = payload.get("reglas_liquidacion", {}).get("presentismo")
    if not presentismo:
        return

    fuente = normalize_text(presentismo.get("fuente_textual") or "")
    # Keywords that indicate it's not yet active
    futura_keywords = ("futura", "comisión", "comision", "se conformar", "sera conformad", "a conformar")

    if any(kw in fuente for kw in futura_keywords):
        # Don't keep as active rule
        payload.setdefault("pendientes_revision", [])
        if "Presentismo mencionado como futura comisión; no es regla liquidable activa." not in payload["pendientes_revision"]:
            payload["pendientes_revision"].append("Presentismo mencionado como futura comisión; no es regla liquidable activa.")
        # Remove from active rules
        del payload["reglas_liquidacion"]["presentismo"]


def apply_payload_normalizations(payload: dict[str, Any]) -> None:
    """
    Apply all normalizations to a payload.
    Modifies payload in-place.
    """
    # Deduplication
    payload["categorias"] = dedupe_robust_categorias(payload.get("categorias") or [])
    payload["escalas_salariales"] = dedupe_robust_escalas(payload.get("escalas_salariales") or [])

    # Clean up useless entries
    clean_useless_additionals(payload)
    clean_useless_subsidios(payload)

    # Fix specific rules
    normalize_zona_desfavorable(payload)
    normalize_antiguedad_rule(payload)
    normalize_presentismo(payload)


def _parser_priority(item: dict[str, Any]) -> int:
    origin = normalize_text(item.get("parser_origen") or item.get("origen_parser") or "")
    if "smata" in origin or "especial" in origin:
        return 3
    if "generico" in origin or "generic" in origin:
        return 2
    return 1


def _merge_categoria_pair(cat1: dict[str, Any], cat2: dict[str, Any]) -> dict[str, Any]:
    priority1 = _parser_priority(cat1)
    priority2 = _parser_priority(cat2)
    fields1 = sum(1 for v in cat1.values() if has_meaningful_value(v))
    fields2 = sum(1 for v in cat2.values() if has_meaningful_value(v))
    if priority2 > priority1 or (priority1 == priority2 and fields2 > fields1):
        cat1, cat2 = cat2, cat1
    merged = dict(cat1)
    for key, value in cat2.items():
        if not has_meaningful_value(merged.get(key)) and has_meaningful_value(value):
            merged[key] = value
    return merged


def _merge_escala_pair(esc1: dict[str, Any], esc2: dict[str, Any]) -> dict[str, Any]:
    priority1 = _parser_priority(esc1)
    priority2 = _parser_priority(esc2)
    score1 = len(esc1.get("columnas_detectadas") or []) + sum(1 for v in esc1.values() if has_meaningful_value(v))
    score2 = len(esc2.get("columnas_detectadas") or []) + sum(1 for v in esc2.values() if has_meaningful_value(v))
    if priority2 > priority1 or (priority1 == priority2 and score2 > score1):
        esc1, esc2 = esc2, esc1
    merged = dict(esc1)
    for key, value in esc2.items():
        if not has_meaningful_value(merged.get(key)) and has_meaningful_value(value):
            merged[key] = value
    merged["columnas_detectadas"] = dedupe_strings((merged.get("columnas_detectadas") or []) + (esc2.get("columnas_detectadas") or []))
    return merged


def dedupe_robust_categorias(categorias: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cat in categorias or []:
        key = f"{normalize_text(cat.get('rama') or '')}|{normalize_text(cat.get('nombre') or cat.get('categoria') or '')}"
        if not key.strip("|"):
            continue
        grouped.setdefault(key, []).append(cat)
    result: list[dict[str, Any]] = []
    for group in grouped.values():
        merged = group[0]
        for item in group[1:]:
            merged = _merge_categoria_pair(merged, item)
        result.append(merged)
    return result


def dedupe_robust_escalas(escalas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for esc in escalas or []:
        basico = to_number(esc.get("basico_mensual") or esc.get("basico") or esc.get("sueldo_mensual") or esc.get("valor"))
        key = f"{normalize_text(esc.get('rama') or '')}|{normalize_text(esc.get('categoria') or esc.get('nombre') or '')}|{basico}"
        if not key.strip("|"):
            continue
        grouped.setdefault(key, []).append(esc)
    result: list[dict[str, Any]] = []
    for group in grouped.values():
        merged = group[0]
        for item in group[1:]:
            merged = _merge_escala_pair(merged, item)
        result.append(merged)
    return result


def clean_useless_additionals(payload: dict[str, Any]) -> None:
    adicionales = payload.get("adicionales") or []
    reglas = payload.get("reglas_liquidacion") or {}
    subsidios = payload.get("subsidios") or []
    regla_norms = set()
    if reglas.get("antiguedad"):
        regla_norms.add("antiguedad")
    if reglas.get("presentismo"):
        regla_norms.add("presentismo")
    if reglas.get("zona_desfavorable"):
        regla_norms.add("zona desfavorable")
    subsidio_norms = set(normalize_text(s.get("nombre") or "") for s in subsidios if has_meaningful_value(s.get("valor")))

    cleaned: list[dict[str, Any]] = []
    for item in adicionales:
        nombre_norm = normalize_text(item.get("nombre") or "")
        tipo_norm = normalize_text(item.get("tipo") or "")
        if nombre_norm in regla_norms and not has_meaningful_value(item.get("valor")):
            continue
        if nombre_norm in subsidio_norms and not has_meaningful_value(item.get("valor")):
            continue
        if tipo_norm == "otro" and not has_meaningful_value(item.get("valor")):
            continue
        cleaned.append(item)
    payload["adicionales"] = cleaned


def clean_useless_subsidios(payload: dict[str, Any]) -> None:
    subsidios = payload.get("subsidios") or []
    fallback_death = any(
        normalize_text(item.get("nombre") or "").startswith("fallecimiento ")
        and has_meaningful_value(item.get("valor"))
        for item in subsidios
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for sub in subsidios:
        nombre_norm = normalize_text(sub.get("nombre") or "")
        if fallback_death and nombre_norm == "fallecimiento" and not has_meaningful_value(sub.get("valor")):
            continue
        grouped.setdefault(nombre_norm, []).append(sub)

    cleaned: list[dict[str, Any]] = []
    for group in grouped.values():
        group.sort(key=lambda x: (not has_meaningful_value(x.get("valor")), -_parser_priority(x)))
        best = group[0]
        if has_meaningful_value(best.get("valor")):
            cleaned.append(best)
    payload["subsidios"] = cleaned


def normalize_zona_desfavorable(payload: dict[str, Any]) -> None:
    reglas = payload.setdefault("reglas_liquidacion", {})
    zonas = [item for item in payload.get("zonas") or [] if isinstance(item, dict)]
    if isinstance(reglas.get("zona_desfavorable"), dict):
        zonas.insert(0, reglas["zona_desfavorable"])
    if not zonas:
        return

    best = zonas[0]
    for zona in zonas[1:]:
        current = to_number(best.get("porcentaje")) or 0
        candidate = to_number(zona.get("porcentaje")) or 0
        if candidate > current:
            best = zona
        elif current == 0 and normalize_text(best.get("fuente_textual") or "").find("treinta por ciento") >= 0:
            best["porcentaje"] = 30

    fuente = " ".join(normalize_text(item.get("fuente_textual") or "") for item in zonas)
    if (to_number(best.get("porcentaje")) or 0) == 0 and re.search(r"\bart\.?\s*56\b", fuente) and re.search(r"\b30\s*%|\btreinta por ciento\b", fuente):
        best["porcentaje"] = 30
    if (to_number(best.get("porcentaje")) or 0) == 0 and re.search(r"\b30\s*%|\btreinta por ciento\b", fuente):
        best["porcentaje"] = 30

    provincias = best.get("provincias") or ["NeuquÃ©n", "RÃ­o Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"]
    best["provincias"] = provincias
    reglas["zona_desfavorable"] = best
    payload["zonas"] = [best]


def normalize_antiguedad_rule(payload: dict[str, Any]) -> None:
    antig_rule = (payload.get("reglas_liquidacion") or {}).get("antiguedad")
    if not antig_rule:
        return
    if not antig_rule.get("base_monto"):
        texto = antig_rule.get("fuente_textual", "")
        match = re.search(r"\$?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", texto)
        if match:
            antig_rule["base_monto"] = to_number(match.group(1))
    porcentaje_per_year = to_number(antig_rule.get("porcentaje_por_anio")) or 1
    if not antig_rule.get("escala"):
        antig_rule["escala"] = [{"anio": i, "porcentaje": i * porcentaje_per_year} for i in range(1, 31)]
    antig_rule["tipo"] = antig_rule.get("tipo") or "porcentaje_por_anio"


def normalize_presentismo(payload: dict[str, Any]) -> None:
    presentismo = payload.get("reglas_liquidacion", {}).get("presentismo")
    if not presentismo:
        return
    fuente = normalize_text(presentismo.get("fuente_textual") or "")
    futura_keywords = ("futura", "comision", "se conformar", "sera conformad", "a conformar")
    if any(kw in fuente for kw in futura_keywords):
        payload.setdefault("pendientes_revision", [])
        mensaje = "Presentismo mencionado como futura comisiÃ³n; no es regla liquidable activa."
        if mensaje not in payload["pendientes_revision"]:
            payload["pendientes_revision"].append(mensaje)
        payload.get("reglas_liquidacion", {}).pop("presentismo", None)


def clean_final_payload(payload: dict[str, Any]) -> None:
    payload.setdefault("categorias", [])
    payload.setdefault("escalas_salariales", [])
    payload.setdefault("adicionales", [])
    payload.setdefault("subsidios", [])
    payload.setdefault("zonas", [])
    payload.setdefault("reglas_liquidacion", {})
    payload.setdefault("pendientes_revision", [])
    payload.setdefault("alertas", [])

    payload["categorias"] = dedupe_robust_categorias(payload.get("categorias") or [])
    payload["escalas_salariales"] = dedupe_robust_escalas(payload.get("escalas_salariales") or [])

    clean_useless_additionals(payload)
    clean_useless_subsidios(payload)
    normalize_zona_desfavorable(payload)
    normalize_antiguedad_rule(payload)
    normalize_presentismo(payload)

    reglas = payload.get("reglas_liquidacion") or {}
    for key, value in list(reglas.items()):
        if isinstance(value, dict):
            meaningful = any(has_meaningful_value(item) for inner_key, item in value.items() if inner_key != "fuente_textual")
            if not meaningful:
                reglas.pop(key, None)
    payload["pendientes_revision"] = dedupe_strings(payload.get("pendientes_revision") or [])
    payload["alertas"] = dedupe_strings(payload.get("alertas") or [])


def apply_payload_normalizations(payload: dict[str, Any]) -> None:
    clean_final_payload(payload)


def extract_antiguedad_rule(text: str) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    if "antig" not in normalized:
        return None

    fuente = pick_match(text, r"(antig[\w\s%$.,/-]{0,420})", 1)
    percentage = to_number(pick_match(text, r"antig[\w\s%$.,/-]{0,220}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%")) or 1
    base_monto_text = pick_match(text, r"(?:salario|sueldo|basico|b[aá]sico)[\w\s%$.,/-]{0,40}?\$?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)")
    if base_monto_text and "." in base_monto_text and "," not in base_monto_text:
        base_monto = to_number(base_monto_text.replace(".", ""))
    else:
        base_monto = to_number(base_monto_text)

    escala_matches = re.findall(r"\b([1-9]|[12]\d|30)\s*(?:anos?|a(?:n|ñ)o?s?)?\s*(\d{1,2})\s*%", normalized, re.I)
    escala: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    for anio_text, porcentaje_text in escala_matches:
        anio = int(anio_text)
        porcentaje_item = int(porcentaje_text)
        if 1 <= anio <= 30 and porcentaje_item > 0 and anio not in seen_years:
            seen_years.add(anio)
            escala.append({"anio": anio, "porcentaje": porcentaje_item})
    if not escala and percentage:
        escala = [{"anio": i, "porcentaje": i * percentage} for i in range(1, 31)]

    return {
        "tipo": "porcentaje_por_anio",
        "base_monto": base_monto,
        "porcentaje_por_anio": percentage,
        "escala": escala or None,
        "fuente_textual": fuente,
    }


def extract_zone_rule(text: str) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    provinces = ["Neuquén", "Río Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"]
    province_tokens = ["neuquen", "rio negro", "chubut", "santa cruz", "tierra del fuego"]
    if not any(token in normalized for token in province_tokens):
        return None

    has_art_56 = bool(re.search(r"\bart\.?\s*56\b", normalized))
    has_thirty = bool(re.search(r"\b30\s*%|\btreinta\s+por\s+ciento\b", normalized, re.I))
    percentage = to_number(pick_match(text, r"(?:zona|patagoni|\bneuquen\b|art\.?\s*56)[\s\S]{0,220}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%"))
    if has_thirty and (has_art_56 or percentage in (None, 0)):
        percentage = 30

    return {
        "porcentaje": percentage or 0,
        "provincias": provinces,
        "fuente_textual": pick_match(text, r"((?:art\.?\s*56|zona|condiciones especiales|patagoni)[\s\S]{0,320})", 1),
    }


def normalize_zona_desfavorable(payload: dict[str, Any]) -> None:
    reglas = payload.setdefault("reglas_liquidacion", {})
    zonas = [item for item in payload.get("zonas") or [] if isinstance(item, dict)]
    if isinstance(reglas.get("zona_desfavorable"), dict):
        zonas.insert(0, reglas["zona_desfavorable"])
    if not zonas:
        return

    best = zonas[0]
    for zona in zonas[1:]:
        current = to_number(best.get("porcentaje")) or 0
        candidate = to_number(zona.get("porcentaje")) or 0
        if candidate > current:
            best = zona

    fuente = " ".join(normalize_text(item.get("fuente_textual") or "") for item in zonas)
    if (to_number(best.get("porcentaje")) or 0) == 0 and re.search(r"\bart\.?\s*56\b", fuente) and re.search(r"\b30\s*%|\btreinta por ciento\b", fuente):
        best["porcentaje"] = 30
    if (to_number(best.get("porcentaje")) or 0) == 0 and re.search(r"\b30\s*%|\btreinta por ciento\b", fuente):
        best["porcentaje"] = 30

    best["provincias"] = best.get("provincias") or ["Neuquén", "Río Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"]
    reglas["zona_desfavorable"] = best
    payload["zonas"] = [best]


def normalize_antiguedad_rule(payload: dict[str, Any]) -> None:
    antig_rule = (payload.get("reglas_liquidacion") or {}).get("antiguedad")
    if not antig_rule:
        return
    if not antig_rule.get("base_monto"):
        texto = antig_rule.get("fuente_textual", "")
        match = re.search(r"\$?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", texto)
        if match:
            monto_text = match.group(1)
            antig_rule["base_monto"] = to_number(monto_text.replace(".", "")) if "." in monto_text and "," not in monto_text else to_number(monto_text)
    porcentaje_per_year = to_number(antig_rule.get("porcentaje_por_anio")) or 1
    current_scale = {
        int(item.get("anio")): int(item.get("porcentaje"))
        for item in antig_rule.get("escala") or []
        if isinstance(item, dict) and item.get("anio") and item.get("porcentaje")
    }
    if not current_scale:
        current_scale = {i: i * porcentaje_per_year for i in range(1, 31)}
    else:
        for year in range(1, 31):
            current_scale.setdefault(year, year * porcentaje_per_year)
    antig_rule["escala"] = [{"anio": year, "porcentaje": current_scale[year]} for year in range(1, 31)]
    antig_rule["tipo"] = antig_rule.get("tipo") or "porcentaje_por_anio"
