from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib import error, parse, request


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

GENERATION_MODEL_CASCADE = [
    DEFAULT_MODEL,
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

NON_GENERATIVE_MODELS = [
    "text-embedding-004",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro-latest",
    "gemini-2.0-pro-exp",
    "gemini-2.0-flash-thinking-exp",
    "learnlm-1.5-pro-experimental",
]

FALLBACK_MODELS = [
    item.strip()
    for item in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        ",".join(GENERATION_MODEL_CASCADE),
    ).split(",")
    if item.strip() and item.strip() not in NON_GENERATIVE_MODELS
]


class GeminiProxyError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: Any) -> str:
    return (
        unicodedata.normalize("NFD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def slugify(value: Any, max_len: int = 72) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    return normalized[:max_len].strip("_") or "sin_id"


def sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def strip_json_fence(text: str) -> str:
    raw = str(text or "").strip()

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()

    start = raw.find("{")
    end = raw.rfind("}")

    if start >= 0 and end > start:
        return raw[start : end + 1].strip()

    return raw


def safe_json_loads(text: str) -> dict[str, Any]:
    cleaned = strip_json_fence(text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiProxyError(f"El modelo no devolvió JSON válido: {exc}") from exc

    if not isinstance(parsed, dict):
        raise GeminiProxyError("El modelo devolvió JSON, pero no es un objeto raíz.")

    return parsed


def build_prompt(payload: Mapping[str, Any]) -> str:
    """
    Prompt de auditoría conversacional general.
    No se usa para estructurar CCT; se conserva para compatibilidad.
    """
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


def is_noise_line(line: str) -> bool:
    normalized = normalize_text(line)
    compact = re.sub(r"\s+", " ", line).strip()

    if not compact or len(compact) < 4:
        return True

    if "https://" in normalized or "http://" in normalized:
        return True

    if "documento.errepar.com" in normalized:
        return True

    if re.search(r"^\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}", compact):
        return True

    if re.search(r"^\d+\s*/\s*\d+$", compact):
        return True

    if normalized in {
        "es util",
        "homologacion",
        "smata",
        "aca",
        "jurisdiccion",
        "organismo",
    }:
        return True

    if "pagina" in normalized and re.search(r"\d+\s+de\s+\d+", normalized):
        return True

    return False


def clean_extracted_pdf_text(text: Any) -> str:
    raw = str(text or "").replace("\x00", " ").strip()

    cleaned_lines: list[str] = []
    seen_repeated_headers: set[str] = set()

    for raw_line in raw.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()

        if is_noise_line(line):
            continue

        normalized = normalize_text(line)

        if len(line) > 40 and (
            "convenio colectivo" in normalized
            or "obreros y administrativos" in normalized
            or "automovil club argentino" in normalized
        ):
            if normalized in seen_repeated_headers:
                continue
            seen_repeated_headers.add(normalized)

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def build_focus_cct_text(text: Any, limit: int = 26000) -> str:
    """
    Recorta el OCR, pero intenta no perder tablas salariales.
    El problema anterior era que el modelo recibía mucho convenio y poca escala.
    """
    raw = clean_extracted_pdf_text(text)

    if len(raw) <= limit:
        return raw

    headline = raw[:5000]

    keywords = (
        "categoria",
        "categorias",
        "puesto",
        "rol",
        "rama",
        "operario",
        "oficial",
        "administr",
        "maestranza",
        "chofer",
        "sereno",
        "playero",
        "expendedor",
        "auxilio",
        "mecanico",
        "gomer",
        "lavador",
        "engrasador",
        "jornada",
        "hora",
        "horas extra",
        "feriado",
        "antiguedad",
        "presentismo",
        "zona",
        "adicional",
        "gratificacion",
        "no remunerativ",
        "remunerativ",
        "licencia",
        "viatico",
        "escala",
        "sueldo",
        "salario",
        "basico",
        "aporte",
        "contribucion",
        "vacacional",
        "subsidio",
        "sac",
        "deduccion",
        "retencion",
        "empleador",
        "ene",
        "abr",
        "2026",
        "$",
        "%",
    )

    selected_lines: list[str] = []
    seen: set[str] = set()
    total_len = len(headline)

    for raw_line in raw.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()

        if len(line) < 4 or len(line) > 420:
            continue

        normalized = normalize_text(line)

        if not any(keyword in normalized for keyword in keywords):
            continue

        if line in seen:
            continue

        seen.add(line)
        selected_lines.append(line)
        total_len += len(line) + 1

        if total_len >= limit - 120:
            break

    focused = f"{headline}\n\nLINEAS RELEVANTES:\n" + "\n".join(selected_lines)
    return focused[:limit]


def empty_agreement_schema(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    now = utc_now_iso()
    file_name = str(payload.get("file_name") or "CCT.pdf")
    text = str(payload.get("text") or "")

    return {
        "metadata": {
            "identity": {
                "agreement_id": "",
                "code": "",
                "name": "",
                "short_name": "",
                "sector": "",
                "subsector": "",
                "union_name": "",
                "country": "Argentina",
                "jurisdiction": "",
            },
            "versioning": {
                "version": "",
                "status": "DRAFT",
                "previous_version": None,
                "next_version": None,
                "is_current": True,
            },
            "validity": {
                "valid_from": "",
                "valid_to": "",
            },
            "source": {
                "original_file_name": file_name,
                "document_type": str(payload.get("document_type") or ""),
                "checksum": sha256_text(text) if text else "",
                "total_pages": int(payload.get("total_pages") or 0),
                "uploaded_by": str(payload.get("uploaded_by") or ""),
                "uploaded_at": str(payload.get("uploaded_at") or ""),
            },
            "extraction": {
                "provider": "gemini",
                "fallback_used": False,
                "fallback_provider": None,
                "extracted_at": now,
                "raw_text_checksum": sha256_text(text) if text else "",
            },
            "ai_processing": {
                "structured_by": "codex",
                "model": "",
                "processed_at": now,
                "confidence_score": 0,
                "warnings": [],
                "ambiguous_articles": [],
            },
            "features": {
                "has_categories": False,
                "has_salary_scales": False,
                "has_overtime_rules": False,
                "has_non_remunerative_items": False,
                "has_attendance_rules": False,
                "has_event_rules": False,
                "has_compliance_rules": False,
                "has_fiscal_shields": False,
                "has_employer_contributions": False,
            },
            "governance": {
                "review_required": True,
                "review_reason": "Pendiente de revisión humana.",
                "approved_by": None,
                "approved_at": None,
                "production_ready": False,
            },
        },
        "data": {
            "agreement_rules": {
                "weekly_hours": None,
                "monthly_hours": None,
                "monthly_divisor": 30,
                "overtime_base": None,
                "seniority_base": None,
                "source_references": [],
            },
            "categories": [],
            "salary_model": {
                "remunerative_items": [],
                "non_remunerative_items": [],
                "deductions": [],
                "employer_contributions": [],
                "overtime_rules": [],
                "fiscal_shields": [],
            },
            "event_rules": [],
            "compliance_rules": [],
            "formulas": [],
            "review_flags": [],
        },
    }


def build_salary_table_extraction_prompt(payload: Mapping[str, Any]) -> str:
    """
    ETAPA 1 REAL.
    Esta función reemplaza la idea de pedir JSON directo a Gemini.
    Primero se le pide texto plano tabular, para que no invente JSON ni mezcle OCR.
    """
    cct_text = build_focus_cct_text(payload.get("text", ""), limit=26000)
    file_name = payload.get("file_name", "CCT.pdf")

    return f"""
Sos un extractor tecnico de convenios colectivos argentinos para un sistema de liquidacion de sueldos.

Objetivo: transcribir y normalizar SOLO datos salariales verificables del archivo.
No liquides sueldos, no inventes importes, no completes valores faltantes.

Archivo: {file_name}

Extrae especialmente:
1. Escala salarial con cada puesto/rol/categoria y su basico asociado.
2. Haberes remunerativos con importe, porcentaje, formula o base.
3. Haberes no remunerativos con importe, porcentaje, formula o base.
4. Retenciones/deducciones con alicuota, importe y base.
5. Horas extra y otros conceptos si aparecen.
6. Reglas generales liquidables del convenio: jornada, horas mensuales, divisor, antiguedad, zona, feriados, vacaciones y licencias si aparecen.

Reglas criticas:
- Si hay tablas, preserva la relacion fila-columna. Una fila de escala debe mantener puesto/rol/categoria + basico en la misma linea.
- No separes importes de sus categorias.
- No resumas tablas salariales.
- En ESCALA_SALARIAL_CATEGORIAS, copia literalmente el nombre completo del puesto/rol/categoria de la celda original.
- No abrevies, no partas por palabras y no conviertas categorias en tags.
- Cada puesto de la escala debe ser una fila independiente. Si la tabla tiene 30 puestos, devuelve 30 filas.
- No uses nombres genericos como "categoria", "puesto", "operario" o "administrativo" si la tabla trae un nombre mas especifico.
- Si el codigo/categoria de origen es una letra o numero A, B, 1, 2, etc., ponelo en category_id y conserva el nombre completo en puesto_rol_categoria.
- Si la tabla contiene jornada completa, jornada reducida, media jornada, supervisor, coordinador, oficial, auxiliar, peon, conductor, chofer, administrativo u otros modificadores, mantenelos dentro de puesto_rol_categoria.
- Mantene importes tal como aparecen, con pesos, puntos y comas.
- Si hay varias vigencias o meses, conserva la columna/periodo original.
- Si un valor aplica por categoria, agrega una fila por categoria.
- Si un valor no esta indicado, escribi NO_INDICADO.
- No conviertas requisitos de antiguedad de una categoria en adicional por antiguedad.
  Ejemplo: "Oficial de Primera: mas de 2 años de antiguedad" describe una categoria, NO es un adicional salarial.
- No conviertas "Zona de aplicacion: todo el territorio..." en adicional por zona desfavorable.
- No conviertas porcentajes de limites, cupos, exclusiones o cantidad de personal en adicionales salariales.
  Ejemplo: "no podran superar el 15% del personal" NO es adicional.
- Extrae adicionales SOLO si aparecen como rubro salarial, beneficio, suplemento, asignacion, adicional o concepto remunerativo/no remunerativo.
- En retenciones/deducciones, cada fila debe ser una retencion separada.
- Extrae retenciones legales argentinas solamente si aparecen en el documento o en la tabla.
- No reemplaces Jubilacion + Ley 19.032 + Obra Social por una fila generica llamada "Aportes" salvo que el documento solo lo muestre agregado y no permita separarlo.
- Si aparece "Aportes de ley" junto con el detalle de sus componentes, desagregalo en JUBILACION, LEY_19032 y OBRA_SOCIAL.
- Si el documento no trae codigo para una retencion, crea un code corto desde el concepto.
- Si un concepto depende de carga mensual del usuario, por ejemplo kilometros, viajes, dias, comidas por dia, pernoctadas, comisiones o productividad variable, en observaciones escribi "CARGA_MANUAL".
- No conviertas viaticos por kilometro, viajes, pernoctadas o comisiones en importes automaticos mensuales.
- Ignora encabezados, pies de pagina, URLs, fechas de impresion, numeros de pagina y basura OCR.
- No inventes articulos, porcentajes, fechas, categorias ni importes.
- No expliques nada fuera de las secciones pedidas.

Devuelve texto plano en este formato exacto:

## METADATA
convenio:
actividad:
sindicato:
jurisdiccion:
vigencia_desde:
vigencia_hasta:
fuente:

## PARAMETROS_LIQUIDACION
| parametro | valor | unidad | fuente | observaciones |

## ESCALA_SALARIAL_CATEGORIAS
| category_id | puesto_rol_categoria | periodo | basico | total_remunerativo | observaciones |

## HABERES_REMUNERATIVOS
| code | concepto | calculation_type | importe | porcentaje | base | aplica_a_categoria | periodo | observaciones |

## HABERES_NO_REMUNERATIVOS
| code | concepto | calculation_type | importe | porcentaje | base | aplica_a_categoria | periodo | observaciones |

## RETENCIONES_DEDUCCIONES
| code | concepto | porcentaje | importe | base | observaciones |

## CONTRIBUCIONES_EMPLEADOR
| code | concepto | porcentaje | importe | base | observaciones |

## HORAS_EXTRA
| code | concepto | multiplicador | porcentaje | base | observaciones |

## EVENTOS_Y_LICENCIAS
| event_type | subtype | efecto | condiciones | observaciones |

## FORMULAS
| formula_id | nombre | expression | variables | observaciones |

## AMBIGUEDADES
-

TEXTO EXTRAIDO DEL PDF:
{cct_text}
""".strip()


def build_cct_text_extraction_prompt(payload: Mapping[str, Any]) -> str:
    """
    Alias para no romper imports anteriores.
    """
    return build_salary_table_extraction_prompt(payload)


def build_codex_json_structuring_prompt(payload: Mapping[str, Any]) -> str:
    """
    ETAPA 2 REAL.
    Recibe la salida tabular de la etapa 1 y recién ahí arma JSON.
    """
    file_name = payload.get("file_name", "CCT.pdf")
    extracted_text = str(payload.get("extracted_text", "")).strip()
    now = utc_now_iso()

    schema = empty_agreement_schema(
        {
            "file_name": file_name,
            "text": payload.get("raw_text", ""),
            "document_type": payload.get("document_type", ""),
            "total_pages": payload.get("total_pages", 0),
            "uploaded_by": payload.get("uploaded_by", ""),
            "uploaded_at": payload.get("uploaded_at", ""),
        }
    )

    schema["metadata"]["extraction"]["extracted_at"] = now
    schema["metadata"]["ai_processing"]["processed_at"] = now

    return f"""
Sos un estructurador de datos laborales argentinos para una calculadora de liquidacion CCT.

Vas a recibir TEXTO PLANO TABULAR generado por una etapa anterior.
Tu tarea es convertir SOLO esas tablas al JSON productivo indicado.

Reglas obligatorias:
- Devolve SOLO JSON valido.
- Sin markdown.
- Sin comentarios.
- Sin ```json.
- No inventes datos.
- No uses datos que no estén en el texto tabular.
- No crees categorias desde METADATA, PARAMETROS_LIQUIDACION, AMBIGUEDADES, encabezados o texto fuente.
- Las categorias SOLO salen de la tabla ## ESCALA_SALARIAL_CATEGORIAS.
- Si ## ESCALA_SALARIAL_CATEGORIAS no trae filas reales con categoria + basico, data.categories debe quedar [] y agregá review_flag.
- No crees categorias desde frases como "Personal Administrativo", "Personal de produccion", "CATEGORIAS", "Bol.Oficial", fechas, URLs o nombres de archivo.
- Cada fila de ## ESCALA_SALARIAL_CATEGORIAS debe convertirse en una categoria o en una vigencia dentro de una categoria existente.
- Si una misma categoria aparece en varios periodos, debe ser UNA sola data.categories[] con varias salary_scales[].
- data.categories[].name debe conservar el texto completo de puesto_rol_categoria.
- data.categories[].category_id debe venir de category_id si existe; si es NO_INDICADO, generá slug desde puesto_rol_categoria.
- data.categories[].base_salary debe ser el basico del periodo más reciente detectado.
- data.categories[].salary_scales[] debe conservar todos los periodos detectados.
- No mezcles escalas historicas con escalas vigentes: preservá valid_from/periodo.
- Si falta un dato string, usa "".
- Si falta un dato numérico obligatorio, usa 0.
- Si un dato admite null, usa null.
- Si un dato es dudoso, agregalo en metadata.ai_processing.warnings o data.review_flags.
- No remunerativos van en data.salary_model.non_remunerative_items.
- Remunerativos adicionales van en data.salary_model.remunerative_items.
- Deducciones van en data.salary_model.deductions solo si aparecen en RETENCIONES_DEDUCCIONES.
- Contribuciones patronales van en data.salary_model.employer_contributions solo si aparecen en CONTRIBUCIONES_EMPLEADOR.
- Horas extra van en data.salary_model.overtime_rules solo si aparecen en HORAS_EXTRA.
- Fiscal shields solo si aparecen expresamente.
- formulas debe incluir expresiones liquidables útiles solo si aparecen en FORMULAS o PARAMETROS_LIQUIDACION.
- confidence_score de 0 a 1.
- production_ready solo true si hay categorias con salary_scales y no hay dudas relevantes.

Mapeo:
- METADATA -> metadata.identity, metadata.validity, metadata.source.
- PARAMETROS_LIQUIDACION -> data.agreement_rules.
- ESCALA_SALARIAL_CATEGORIAS -> data.categories[].salary_scales[].
- HABERES_REMUNERATIVOS -> data.salary_model.remunerative_items.
- HABERES_NO_REMUNERATIVOS -> data.salary_model.non_remunerative_items.
- RETENCIONES_DEDUCCIONES -> data.salary_model.deductions.
- CONTRIBUCIONES_EMPLEADOR -> data.salary_model.employer_contributions.
- HORAS_EXTRA -> data.salary_model.overtime_rules.
- EVENTOS_Y_LICENCIAS -> data.event_rules.
- FORMULAS -> data.formulas.
- AMBIGUEDADES -> data.review_flags y metadata.ai_processing.warnings.

Schema requerido:
{json.dumps(schema, ensure_ascii=False, indent=2)}

Estructura ampliada permitida:
- En data.categories[] podes agregar:
  "salary_scales": [
    {{
      "valid_from": "",
      "valid_to": "",
      "base_salary": 0,
      "currency": "ARS",
      "salary_type": "remunerative|non_remunerative|mixed|unknown",
      "source_reference": {{"article": "", "page": null, "text": ""}}
    }}
  ],
  "source_reference": {{"article": "", "page": null, "text": ""}}
- En items de salary_model podes agregar "source_reference" y "remunerative" si ayuda.
- En event_rules, compliance_rules y formulas podes agregar "source_reference".

TEXTO TABULAR NORMALIZADO:
{extracted_text}
""".strip()


def build_cct_extraction_prompt(payload: Mapping[str, Any]) -> str:
    """
    Compatibilidad con código viejo.

    IMPORTANTE:
    Esta función ahora devuelve el prompt de ETAPA 1, no el JSON final.
    Si tu backend hacía:
        json_text = extract_cct_json_text_validated(payload)
    """
    return build_salary_table_extraction_prompt(payload)


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
            "temperature": 0.05,
            "topP": 0.8,
            "maxOutputTokens": 8192,
        },
    }

    data = json.dumps(body).encode("utf-8")

    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))

    parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])

    text = "\n".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    )

    if not text.strip():
        raise GeminiProxyError("Gemini no devolvio texto util.")

    return text.strip()


def call_gemini(prompt: str, model: str | None = None) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        raise GeminiProxyError("GEMINI_API_KEY no configurada.")

    models_to_try: list[str] = []
    requested = model or DEFAULT_MODEL

    for candidate in [requested, *FALLBACK_MODELS]:
        if (
            candidate
            and candidate not in NON_GENERATIVE_MODELS
            and candidate not in models_to_try
        ):
            models_to_try.append(candidate)

    errors: list[str] = []
    quota_exhausted = False

    for active_model in models_to_try:
        try:
            print(f"[Gemini] intentando modelo: {active_model}")
            return _call_gemini_once(prompt, active_model, api_key)

        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(
                f"[Gemini] fallo modelo {active_model}: "
                f"HTTP {exc.code} {detail[:600]}"
            )
            errors.append(f"{active_model}: HTTP {exc.code} {detail}")

            if exc.code == 429:
                quota_exhausted = True
                continue

            if exc.code in {400, 401, 403, 404, 500, 502, 503, 504}:
                continue

        except error.URLError as exc:
            print(f"[Gemini] fallo red modelo {active_model}: {exc.reason}")
            errors.append(f"{active_model}: {exc.reason}")
            continue

        except GeminiProxyError as exc:
            errors.append(f"{active_model}: {exc}")
            continue

    reason = (
        "Gemini sin cuota disponible para los modelos configurados. "
        if quota_exhausted
        else "Gemini no pudo responder con ningun modelo generativo. "
    )

    raise GeminiProxyError(reason + "Ultimos errores: " + " | ".join(errors[-4:]))


def extract_agreement_text(payload: Mapping[str, Any], model: str | None = None) -> str:
    """
    Etapa 1:
    PDF/OCR -> texto plano tabular.
    """
    prompt = build_salary_table_extraction_prompt(payload)
    return call_gemini(prompt, model=model)


def structure_agreement_json_text(
    payload: Mapping[str, Any],
    extracted_text: str,
    model: str | None = None,
) -> str:
    """
    Etapa 2:
    texto plano tabular -> JSON productivo.
    """
    prompt = build_codex_json_structuring_prompt(
        {
            "file_name": payload.get("file_name", "CCT.pdf"),
            "raw_text": payload.get("text", ""),
            "extracted_text": extracted_text,
            "document_type": payload.get("document_type", ""),
            "total_pages": payload.get("total_pages", 0),
            "uploaded_by": payload.get("uploaded_by", ""),
            "uploaded_at": payload.get("uploaded_at", ""),
        }
    )
    return call_gemini(prompt, model=model)


def normalize_source_reference(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "article": str(value.get("article") or ""),
            "page": value.get("page") if value.get("page") is not None else None,
            "text": str(value.get("text") or "")[:500],
        }

    text = str(value or "")
    return {"article": "", "page": None, "text": text[:500]}


def parse_money_to_number(value: Any) -> float | int:
    if isinstance(value, (int, float)):
        return value

    raw = str(value or "").strip()

    if not raw or normalize_text(raw) == "no_indicado":
        return 0

    raw = raw.replace("$", "").replace("ARS", "").strip()

    if "," in raw and "." in raw:
        # Formato AR: 1.234.567,89
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw and "." not in raw:
        # Puede ser decimal AR.
        raw = raw.replace(",", ".")
    else:
        # Formato 1,234,567 o 1.234.567 ya limpiado por OCR.
        raw = raw.replace(",", "")

    raw = re.sub(r"[^0-9.\-]", "", raw)

    if not raw:
        return 0

    try:
        number = float(raw)
    except ValueError:
        return 0

    if number.is_integer():
        return int(number)
    return number


def parse_rate_to_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    raw = str(value or "").strip()

    if not raw or normalize_text(raw) == "no_indicado":
        return 0

    raw = raw.replace("%", "").replace(",", ".")
    raw = re.sub(r"[^0-9.\-]", "", raw)

    if not raw:
        return 0

    try:
        return float(raw)
    except ValueError:
        return 0


def postprocess_agreement_json(
    data: dict[str, Any],
    payload: Mapping[str, Any] | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """
    Limpieza defensiva posterior.
    No inventa datos; normaliza estructura, ids, features, escalas y governance.
    """
    payload = payload or {}
    base = empty_agreement_schema(payload)

    data.setdefault("metadata", {})
    data.setdefault("data", {})

    for section, default_value in base["metadata"].items():
        data["metadata"].setdefault(section, default_value)

    for section, default_value in base["data"].items():
        data["data"].setdefault(section, default_value)

    metadata = data["metadata"]
    data_node = data["data"]

    for section, default_value in base["metadata"].items():
        if not isinstance(metadata.get(section), dict):
            metadata[section] = default_value
            continue
        for key, value in default_value.items():
            metadata[section].setdefault(key, value)

    if not isinstance(data_node.get("agreement_rules"), dict):
        data_node["agreement_rules"] = base["data"]["agreement_rules"]

    if not isinstance(data_node.get("salary_model"), dict):
        data_node["salary_model"] = base["data"]["salary_model"]

    for key, value in base["data"]["salary_model"].items():
        if not isinstance(data_node["salary_model"].get(key), list):
            data_node["salary_model"][key] = value

    for key in ("categories", "event_rules", "compliance_rules", "formulas", "review_flags"):
        if not isinstance(data_node.get(key), list):
            data_node[key] = []

    metadata["source"]["original_file_name"] = (
        metadata["source"].get("original_file_name")
        or str(payload.get("file_name") or "CCT.pdf")
    )
    metadata["source"]["checksum"] = metadata["source"].get("checksum") or sha256_text(payload.get("text", ""))
    metadata["extraction"]["raw_text_checksum"] = (
        metadata["extraction"].get("raw_text_checksum") or sha256_text(payload.get("text", ""))
    )
    metadata["extraction"]["provider"] = metadata["extraction"].get("provider") or "gemini"
    metadata["ai_processing"]["structured_by"] = metadata["ai_processing"].get("structured_by") or "codex"

    if model_name:
        metadata["ai_processing"]["model"] = model_name

    warnings = metadata["ai_processing"].setdefault("warnings", [])
    review_flags = data_node.setdefault("review_flags", [])

    noise_patterns = (
        "archivo del convenio",
        "bol.oficial",
        "boletin oficial",
        "https",
        "documento.errepar",
        "23/4/26",
        "11:28",
        "jurisdiccion",
        "organismo",
        "categorias",
        "personal administrativo",
        "personal de produccion",
        "actividad y categoria",
    )

    clean_categories: list[dict[str, Any]] = []
    categories_by_id: dict[str, dict[str, Any]] = {}

    for item in data_node.get("categories", []):
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or item.get("nombre") or "").strip()
        category_id = str(item.get("category_id") or item.get("id") or "").strip()

        normalized_name = normalize_text(name)
        normalized_id = normalize_text(category_id)

        if not name:
            continue

        if any(pattern in normalized_name for pattern in noise_patterns):
            warnings.append(f"Categoria descartada por ruido OCR/header: {name}")
            continue

        if any(pattern in normalized_id for pattern in noise_patterns):
            warnings.append(f"Categoria descartada por id contaminado: {category_id}")
            continue

        if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}", name):
            warnings.append(f"Categoria descartada por fecha detectada como nombre: {name}")
            continue

        normalized_category_id = slugify(category_id or name)

        item["category_id"] = normalized_category_id
        item["name"] = name
        item["group"] = str(item.get("group") or item.get("rama") or "")
        item["monthly_hours"] = int(
            item.get("monthly_hours")
            or data_node["agreement_rules"].get("monthly_hours")
            or 0
        )
        item["base_salary"] = parse_money_to_number(item.get("base_salary", 0))
        item["currency"] = str(item.get("currency") or "ARS")

        salary_scales = item.get("salary_scales")
        if not isinstance(salary_scales, list):
            salary_scales = []

        normalized_scales: list[dict[str, Any]] = []
        for scale in salary_scales:
            if not isinstance(scale, dict):
                continue

            base_salary = parse_money_to_number(scale.get("base_salary", 0))

            if base_salary == 0:
                continue

            normalized_scales.append(
                {
                    "valid_from": str(scale.get("valid_from") or scale.get("period") or ""),
                    "valid_to": str(scale.get("valid_to") or ""),
                    "base_salary": base_salary,
                    "currency": str(scale.get("currency") or item["currency"] or "ARS"),
                    "salary_type": str(scale.get("salary_type") or "remunerative"),
                    "source_reference": normalize_source_reference(
                        scale.get("source_reference")
                        or scale.get("source")
                        or scale.get("observaciones")
                    ),
                }
            )

        item["salary_scales"] = normalized_scales
        item["source_reference"] = normalize_source_reference(
            item.get("source_reference") or item.get("source") or item.get("observaciones")
        )

        if item["base_salary"] == 0 and normalized_scales:
            item["base_salary"] = normalized_scales[-1]["base_salary"]

        if item["base_salary"] == 0:
            review_flags.append(f"Categoria sin basico detectado: {name}")

        if normalized_category_id in categories_by_id:
            existing = categories_by_id[normalized_category_id]
            existing_scales = existing.setdefault("salary_scales", [])
            known = {
                (str(s.get("valid_from")), int(s.get("base_salary") or 0))
                for s in existing_scales
                if isinstance(s, dict)
            }

            for scale in normalized_scales:
                key = (str(scale.get("valid_from")), int(scale.get("base_salary") or 0))
                if key not in known:
                    existing_scales.append(scale)

            if item["base_salary"]:
                existing["base_salary"] = item["base_salary"]

            continue

        categories_by_id[normalized_category_id] = item
        clean_categories.append(item)

    data_node["categories"] = clean_categories[:120]

    for key in (
        "remunerative_items",
        "non_remunerative_items",
        "deductions",
        "employer_contributions",
        "overtime_rules",
        "fiscal_shields",
    ):
        clean_items: list[dict[str, Any]] = []

        for item in data_node["salary_model"].get(key, []):
            if not isinstance(item, dict):
                continue

            item["code"] = slugify(item.get("code") or item.get("name") or item.get("concepto") or key)

            if "name" not in item and "concepto" in item:
                item["name"] = item.get("concepto")

            if "amount" in item:
                item["amount"] = parse_money_to_number(item.get("amount"))

            if "importe" in item and "amount" not in item:
                item["amount"] = parse_money_to_number(item.get("importe"))

            if "rate" in item:
                item["rate"] = parse_rate_to_number(item.get("rate"))

            if "porcentaje" in item and "rate" not in item:
                item["rate"] = parse_rate_to_number(item.get("porcentaje"))

            if "source_reference" in item:
                item["source_reference"] = normalize_source_reference(item.get("source_reference"))

            clean_items.append(item)

        data_node["salary_model"][key] = clean_items

    features = metadata["features"]
    features["has_categories"] = bool(data_node["categories"])
    features["has_salary_scales"] = any(
        bool(cat.get("salary_scales")) or bool(cat.get("base_salary"))
        for cat in data_node["categories"]
    )
    features["has_overtime_rules"] = bool(data_node["salary_model"]["overtime_rules"])
    features["has_non_remunerative_items"] = bool(data_node["salary_model"]["non_remunerative_items"])
    features["has_event_rules"] = bool(data_node["event_rules"])
    features["has_compliance_rules"] = bool(data_node["compliance_rules"])
    features["has_fiscal_shields"] = bool(data_node["salary_model"]["fiscal_shields"])
    features["has_employer_contributions"] = bool(data_node["salary_model"]["employer_contributions"])

    all_items_text = normalize_text(
        json.dumps(data_node["salary_model"], ensure_ascii=False)
        + " "
        + json.dumps(data_node["event_rules"], ensure_ascii=False)
    )
    features["has_attendance_rules"] = any(
        token in all_items_text
        for token in ("presentismo", "asistencia", "ausentismo", "puntualidad")
    )

    has_minimum = features["has_categories"] and features["has_salary_scales"]
    has_warnings = bool(warnings or review_flags)

    metadata["governance"]["review_required"] = has_warnings or not has_minimum
    metadata["governance"]["production_ready"] = bool(has_minimum and not has_warnings)

    if metadata["governance"]["review_required"]:
        metadata["governance"]["review_reason"] = "Hay warnings, review_flags o faltan datos mínimos para producción."
    else:
        metadata["governance"]["review_reason"] = None

    try:
        confidence = float(metadata["ai_processing"].get("confidence_score") or 0)
    except ValueError:
        confidence = 0

    metadata["ai_processing"]["confidence_score"] = max(0, min(1, confidence))

    return data


def validate_agreement_payload(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise GeminiProxyError("Payload invalido: se esperaba un objeto.")

    text = str(payload.get("text", "") or "").strip()

    if not text:
        raise GeminiProxyError("Payload invalido: falta text con contenido del PDF.")

    if len(text) < 50:
        raise GeminiProxyError("Payload invalido: text es demasiado corto.")


def extract_agreement_json(
    payload: Mapping[str, Any],
    extraction_model: str | None = None,
    structuring_model: str | None = None,
    postprocess: bool = True,
) -> dict[str, Any]:
    """
    Pipeline recomendado para producción.

    1. Gemini devuelve texto plano tabular.
    2. Gemini/Codex-compatible prompt convierte ese texto en JSON productivo.
    3. Postprocess normaliza, deduplica, calcula features y marca governance.
    """
    extracted_text = extract_agreement_text(payload, model=extraction_model)

    json_text = structure_agreement_json_text(
        payload,
        extracted_text=extracted_text,
        model=structuring_model,
    )

    parsed = safe_json_loads(json_text)

    if postprocess:
        parsed = postprocess_agreement_json(
            parsed,
            payload=payload,
            model_name=structuring_model or DEFAULT_MODEL,
        )

    return parsed


def extract_agreement_json_text(
    payload: Mapping[str, Any],
    extraction_model: str | None = None,
    structuring_model: str | None = None,
    postprocess: bool = True,
) -> str:
    parsed = extract_agreement_json(
        payload,
        extraction_model=extraction_model,
        structuring_model=structuring_model,
        postprocess=postprocess,
    )

    return json.dumps(parsed, ensure_ascii=False, indent=2)


def extract_agreement_json_text_validated(
    payload: Mapping[str, Any],
    extraction_model: str | None = None,
    structuring_model: str | None = None,
) -> str:
    validate_agreement_payload(payload)

    return extract_agreement_json_text(
        payload,
        extraction_model=extraction_model,
        structuring_model=structuring_model,
        postprocess=True,
    )


# Aliases de compatibilidad con nombres anteriores.
def extract_cct_text(payload: Mapping[str, Any], model: str | None = None) -> str:
    return extract_agreement_text(payload, model=model)


def structure_cct_json_text(
    payload: Mapping[str, Any],
    extracted_text: str,
    model: str | None = None,
) -> str:
    return structure_agreement_json_text(payload, extracted_text, model=model)


def postprocess_cct_json(
    data: dict[str, Any],
    payload: Mapping[str, Any] | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    return postprocess_agreement_json(data, payload=payload, model_name=model_name)


def validate_cct_payload(payload: Mapping[str, Any]) -> None:
    validate_agreement_payload(payload)


def extract_cct_json(
    payload: Mapping[str, Any],
    extraction_model: str | None = None,
    structuring_model: str | None = None,
    postprocess: bool = True,
) -> dict[str, Any]:
    return extract_agreement_json(
        payload,
        extraction_model=extraction_model,
        structuring_model=structuring_model,
        postprocess=postprocess,
    )


def extract_cct_json_text(
    payload: Mapping[str, Any],
    extraction_model: str | None = None,
    structuring_model: str | None = None,
    postprocess: bool = True,
) -> str:
    return extract_agreement_json_text(
        payload,
        extraction_model=extraction_model,
        structuring_model=structuring_model,
        postprocess=postprocess,
    )


def extract_cct_json_text_validated(
    payload: Mapping[str, Any],
    extraction_model: str | None = None,
    structuring_model: str | None = None,
) -> str:
    return extract_agreement_json_text_validated(
        payload,
        extraction_model=extraction_model,
        structuring_model=structuring_model,
    )
