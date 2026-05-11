from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib import error, parse, request


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

GENERATION_MODEL_CASCADE = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3-flash",
    "gemini-2.5-flash",
]

NON_GENERATIVE_MODELS = [
    "text-embedding-004",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
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
    """
    Limpia respuestas tipo ```json ... ``` por si el modelo no respeta el pedido.
    """
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
    No se usa para estructurar CCT; se conserva para compatibilidad con tu backend.
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
    """
    Elimina encabezados/pies repetidos y basura típica de PDFs legales/OCR.
    """
    normalized = normalize_text(line)
    compact = re.sub(r"\s+", " ", line).strip()

    if not compact:
        return True

    if len(compact) < 4:
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

        # Evita repetir encabezados largos de la misma fuente.
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


def build_focus_cct_text(text: Any, limit: int = 20000) -> str:
    raw = clean_extracted_pdf_text(text)

    if len(raw) <= limit:
        return raw

    headline = raw[:6000]

    keywords = (
        "categoria",
        "categorias",
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
        "$",
        "%",
    )

    selected_lines: list[str] = []
    seen: set[str] = set()
    total_len = len(headline)

    for raw_line in raw.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()

        if len(line) < 8 or len(line) > 360:
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


def build_cct_text_extraction_prompt(payload: Mapping[str, Any]) -> str:
    cct_text = build_focus_cct_text(payload.get("text", ""), limit=20000)
    file_name = payload.get("file_name", "CCT.pdf")

    return f"""
Sos un extractor tecnico de convenios colectivos argentinos para un sistema de liquidacion de sueldos.

Objetivo: transcribir y normalizar SOLO datos salariales verificables del archivo. No liquides sueldos, no inventes importes, no completes valores faltantes.

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
- En ESCALA_SALARIAL_CATEGORIAS, copia literalmente el nombre completo del puesto/rol/categoria de la celda original. No lo abrevies, no lo partas por palabras, no lo conviertas en tags.
- Cada puesto de la escala debe ser una fila independiente. Si la tabla tiene 30 puestos, devuelve 30 filas.
- No uses nombres genericos como "categoria", "puesto", "operario" o "administrativo" si la tabla trae un nombre mas especifico.
- Si el codigo/categoria de origen es una letra o numero A, B, 1, 2, etc., ponelo en category_id y conserva el nombre completo en puesto_rol_categoria.
- Si la tabla contiene jornada completa, jornada reducida, media jornada, supervisor, coordinador, oficial, auxiliar, peon, conductor, chofer, administrativo u otros modificadores, mantenelos dentro de puesto_rol_categoria.
- Mantene importes tal como aparecen, con pesos, puntos y comas.
- Si un valor aplica por categoria, agrega una fila por categoria.
- Si un valor no esta indicado, escribi NO_INDICADO.
- En retenciones/deducciones, cada fila debe ser una retencion separada. No agrupes jubilacion, obra social, ley 19032, sindicato, seguro, contribucion solidaria ni aportes en una sola fila.
- Extrae retenciones legales argentinas solamente si aparecen en el documento o en la tabla: Jubilacion 11%, Ley 19.032 / INSSJP / PAMI 3%, Obra Social 3%. Deben ser filas separadas.
- No reemplaces Jubilacion + Ley 19.032 + Obra Social por una fila generica llamada "Aportes" salvo que el documento solo lo muestre agregado y no permita separarlo.
- Si aparece "Aportes de ley" junto con el detalle de sus componentes, desagregalo en JUBILACION, LEY_19032 y OBRA_SOCIAL.
- Si el documento no trae codigo para una retencion, crea un code corto desde el concepto: JUBILACION, OBRA_SOCIAL, LEY_19032, SINDICATO, SEGURO_SEPELIO, CONTRIBUCION_SOLIDARIA, etc.
- Si hay varias vigencias o meses, conserva la columna/periodo original.
- Si un concepto depende de una carga mensual del usuario, por ejemplo kilometros, km, viajes, dias, comidas por dia, pernoctadas, comisiones o productividad variable, en observaciones escribi "CARGA_MANUAL" y conserva la unidad en base u observaciones.
- No conviertas viaticos por kilometro, viajes, pernoctadas o comisiones en importes automaticos mensuales.
- No expliques nada fuera de las secciones pedidas.
- Ignora encabezados, pies de pagina, URLs, fechas de impresion, numeros de pagina y basura OCR.
- No inventes articulos, porcentajes, fechas, categorias ni importes.

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


def build_codex_json_structuring_prompt(payload: Mapping[str, Any]) -> str:
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

Vas a recibir texto tecnico ya limpiado por una etapa anterior.
Tu tarea es devolver SOLO JSON valido usando EXACTAMENTE el schema productivo indicado.

Reglas obligatorias:
- Devolve SOLO JSON valido.
- Sin markdown.
- Sin comentarios.
- Sin ```json.
- No inventes datos.
- Si falta un dato string, usa "".
- Si falta un dato numérico, usa 0 solamente cuando el campo del schema sea numérico obligatorio; si el campo admite null, usa null.
- Si un dato es dudoso, agregalo en metadata.ai_processing.warnings o data.review_flags.
- No crees categorias a partir de encabezados, fechas, URLs, boletines, nombres de archivo ni basura OCR.
- No mezcles categorias del convenio con conceptos adicionales.
- No mezcles escalas historicas con escalas vigentes.
- Si hay basicos por fecha, cargalos en data.categories[].salary_scales.
- data.categories[].base_salary debe ser el basico vigente mas reciente detectado.
- Si una categoria no tiene basico, dejá base_salary en 0 y agregá review_flag.
- Si una categoria tiene varias vigencias, mantenerlas todas en salary_scales.
- monthly_hours debe cargarse por categoria si se detecta; si no, usar data.agreement_rules.monthly_hours cuando exista.
- No remunerativos van en salary_model.non_remunerative_items.
- Horas extra van en salary_model.overtime_rules.
- Contribuciones patronales van en salary_model.employer_contributions solo si aparecen expresamente.
- Deducciones van en salary_model.deductions solo si aparecen expresamente.
- Fiscal shields solo si aparecen expresamente.
- compliance_rules debe incluir reglas preventivas útiles para auditoría cuando surjan del documento.
- formulas debe incluir expresiones liquidables útiles, por ejemplo antiguedad, valor hora u horas extra.
- Cada item relevante debe traer source_reference o source cuando corresponda.
- confidence_score de 0 a 1.
- production_ready solo true si hay categorías, escalas y reglas mínimas sin dudas relevantes.

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

Texto tecnico normalizado:
{extracted_text}
""".strip()


def build_cct_extraction_prompt(payload: Mapping[str, Any]) -> str:
    """
    Compatibilidad con flujo viejo de una sola llamada.

    Recomendado para producción:
    usar extract_agreement_json_text_validated(payload), que ejecuta las dos etapas reales.
    """
    focused_text = build_focus_cct_text(payload.get("text", ""), limit=20000)
    return build_codex_json_structuring_prompt(
        {
            "file_name": payload.get("file_name", "CCT.pdf"),
            "raw_text": payload.get("text", ""),
            "extracted_text": focused_text,
            "document_type": payload.get("document_type", ""),
            "total_pages": payload.get("total_pages", 0),
            "uploaded_by": payload.get("uploaded_by", ""),
            "uploaded_at": payload.get("uploaded_at", ""),
        }
    )


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
    PDF/OCR -> texto técnico limpio semiestructurado.
    """
    prompt = build_cct_text_extraction_prompt(payload)
    return call_gemini(prompt, model=model)


def structure_agreement_json_text(
    payload: Mapping[str, Any],
    extracted_text: str,
    model: str | None = None,
) -> str:
    """
    Etapa 2:
    texto técnico limpio -> JSON productivo.
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


def ensure_path(root: dict[str, Any], path: list[str], default: Any) -> Any:
    current: Any = root
    for part in path[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]

    leaf = path[-1]
    if leaf not in current:
        current[leaf] = default

    return current[leaf]


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
    if not raw:
        return 0

    raw = raw.replace("$", "").replace("ARS", "").strip()
    raw = raw.replace(".", "").replace(",", ".")
    raw = re.sub(r"[^0-9.\-]", "", raw)

    if not raw:
        return 0

    number = float(raw)
    if number.is_integer():
        return int(number)
    return number


def postprocess_agreement_json(
    data: dict[str, Any],
    payload: Mapping[str, Any] | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """
    Limpieza defensiva posterior.
    No inventa datos; normaliza estructura, ids, features y ruido OCR evidente.
    """
    payload = payload or {}
    base = empty_agreement_schema(payload)

    data.setdefault("metadata", {})
    data.setdefault("data", {})

    # Completa ramas principales sin pisar lo que devolvió el modelo.
    for section, default_value in base["metadata"].items():
        data["metadata"].setdefault(section, default_value)

    for section, default_value in base["data"].items():
        data["data"].setdefault(section, default_value)

    metadata = data["metadata"]
    data_node = data["data"]

    # Completa subestructuras metadata.
    for section, default_value in base["metadata"].items():
        if not isinstance(metadata.get(section), dict):
            metadata[section] = default_value
            continue
        for key, value in default_value.items():
            metadata[section].setdefault(key, value)

    # Completa subestructuras data.
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
    )

    clean_categories: list[dict[str, Any]] = []

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

        item["category_id"] = slugify(category_id or name)
        item["name"] = name
        item["group"] = str(item.get("group") or item.get("rama") or "")
        item["monthly_hours"] = int(item.get("monthly_hours") or data_node["agreement_rules"].get("monthly_hours") or 0)
        item["base_salary"] = parse_money_to_number(item.get("base_salary", 0))
        item["currency"] = str(item.get("currency") or "ARS")

        salary_scales = item.get("salary_scales")
        if not isinstance(salary_scales, list):
            salary_scales = []

        normalized_scales: list[dict[str, Any]] = []
        for scale in salary_scales:
            if not isinstance(scale, dict):
                continue

            normalized_scales.append(
                {
                    "valid_from": str(scale.get("valid_from") or ""),
                    "valid_to": str(scale.get("valid_to") or ""),
                    "base_salary": parse_money_to_number(scale.get("base_salary", 0)),
                    "currency": str(scale.get("currency") or item["currency"] or "ARS"),
                    "salary_type": str(scale.get("salary_type") or "unknown"),
                    "source_reference": normalize_source_reference(scale.get("source_reference") or scale.get("source")),
                }
            )

        item["salary_scales"] = normalized_scales
        item["source_reference"] = normalize_source_reference(item.get("source_reference") or item.get("source"))

        if item["base_salary"] == 0 and normalized_scales:
            # Usa el último básico no cero detectado como base actual.
            for scale in reversed(normalized_scales):
                if scale["base_salary"]:
                    item["base_salary"] = scale["base_salary"]
                    break

        if item["base_salary"] == 0:
            review_flags.append(f"Categoria sin basico detectado: {name}")

        clean_categories.append(item)

    data_node["categories"] = clean_categories[:80]

    # Normaliza listas de salary_model.
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
            if "code" in item:
                item["code"] = slugify(item.get("code") or item.get("name") or key)
            elif "name" in item:
                item["code"] = slugify(item.get("name") or key)

            if "amount" in item:
                item["amount"] = parse_money_to_number(item.get("amount"))

            if "rate" in item and item.get("rate") not in (None, ""):
                try:
                    item["rate"] = float(str(item.get("rate")).replace("%", "").replace(",", "."))
                except ValueError:
                    item["rate"] = 0

            if "source_reference" in item:
                item["source_reference"] = normalize_source_reference(item.get("source_reference"))

            clean_items.append(item)
        data_node["salary_model"][key] = clean_items

    # Features automáticos.
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

    # Attendance rules: presentismo, ausentismo, puntualidad, asistencia.
    all_items_text = normalize_text(
        json.dumps(data_node["salary_model"], ensure_ascii=False)
        + " "
        + json.dumps(data_node["event_rules"], ensure_ascii=False)
    )
    features["has_attendance_rules"] = any(
        token in all_items_text
        for token in ("presentismo", "asistencia", "ausentismo", "puntualidad")
    )

    # Governance.
    has_minimum = features["has_categories"] and features["has_salary_scales"]
    has_warnings = bool(warnings or review_flags)

    metadata["governance"]["review_required"] = has_warnings or not has_minimum
    metadata["governance"]["production_ready"] = bool(has_minimum and not has_warnings)

    if metadata["governance"]["review_required"] and not metadata["governance"].get("review_reason"):
        metadata["governance"]["review_reason"] = "Hay warnings, review_flags o faltan datos mínimos para producción."

    # Confidence defensivo.
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

    Ejecuta:
    1. Gemini: limpia y ordena texto laboral.
    2. Gemini/Codex-compatible prompt: estructura JSON productivo.
    3. Valida JSON.
    4. Postprocesa ruido OCR evidente, features y governance.

    Nota:
    Si más adelante conectás OpenAI/Codex como segunda etapa real,
    reemplazá structure_agreement_json_text() por la llamada a ese servicio.
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
    """
    Variante útil para endpoints que esperan texto JSON.
    """
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
    """
    Wrapper recomendado para usar desde API/backend.
    """
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
