from __future__ import annotations

import html
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

from backend.gemini_proxy import (
    DEFAULT_MODEL,
    GeminiProxyError,
    build_cct_extraction_prompt,
    build_prompt,
    call_gemini,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"
CALCULATORS_DIR = ROOT_DIR / "calculadoras"
DATA_DIR = ROOT_DIR / "data" / "calculadoras"


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


class CalculatorPageRequest(BaseModel):
    payload: dict[str, Any]


app = FastAPI(title="Motor IA para Convenios y Calculadoras")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_gemini_json(text: str) -> Any:
    raw = text.strip()
    candidates: list[str] = []
    fenced = re.findall(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", raw)
    candidates.extend(item.strip() for item in fenced if item.strip())
    candidates.append(raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start:end + 1])
    for candidate in candidates:
        cleaned = candidate.strip().removeprefix("json").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            continue
    return {"estado": "respuesta_no_json", "raw": text}


def normalize_calculator_payload(payload: Any, file_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"estado": "payload_invalido", "archivo_fuente": file_name, "convenio": {"nombre": "CCT cargado"}, "categorias": [], "adicionales": [], "pendientes_revision": ["La IA no devolvio un objeto JSON util"], "raw": payload}
    payload.setdefault("archivo_fuente", file_name)
    payload.setdefault("estado", "json_calculadora_generado")
    payload.setdefault("convenio", {})
    payload.setdefault("categorias", [])
    payload.setdefault("adicionales", [])
    payload.setdefault("reglas_liquidacion", {})
    payload.setdefault("pendientes_revision", [])
    payload.setdefault("alertas", [])
    payload.setdefault("nivel_confianza", 0)
    if not isinstance(payload["convenio"], dict):
        payload["convenio"] = {"nombre": str(payload["convenio"])}
    if not isinstance(payload["categorias"], list):
        payload["categorias"] = []
    if not isinstance(payload["adicionales"], list):
        payload["adicionales"] = []
    if not isinstance(payload["pendientes_revision"], list):
        payload["pendientes_revision"] = [str(payload["pendientes_revision"])]
    if not isinstance(payload["alertas"], list):
        payload["alertas"] = [str(payload["alertas"])]
    return payload


def extract_text_from_pdf_bytes(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n\n".join(pages).strip()
    if len(text) < 80:
        raise HTTPException(status_code=422, detail="El PDF se pudo abrir, pero no contiene suficiente texto seleccionable. Probablemente es escaneado/imagen y requiere OCR.")
    return text


def extract_cct_from_text(file_name: str, text: str) -> dict[str, Any]:
    prompt = build_cct_extraction_prompt({"file_name": file_name, "text": text})
    try:
        gemini_text = call_gemini(prompt, os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    except GeminiProxyError as exc:
        status_code = 503 if "API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    parsed = normalize_calculator_payload(parse_gemini_json(gemini_text), file_name)
    return {"mode": "gemini-cct", "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL), "text_length": len(text), "result": parsed}


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9áéíóúñü]+", "-", value, flags=re.IGNORECASE)
    value = value.strip("-")
    return value[:70] or "calculadora"


def calculator_slug(payload: dict[str, Any]) -> str:
    convenio = payload.get("convenio") if isinstance(payload.get("convenio"), dict) else {}
    raw = convenio.get("numero") or convenio.get("nombre") or payload.get("archivo_fuente") or "calculadora"
    base = slugify(str(raw))
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
<html lang=\"es\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{title}</title>
  <style>
    body{{margin:0;font-family:Inter,system-ui,Arial,sans-serif;background:#fff8ef;color:#1b2321}}
    header{{padding:28px;max-width:1180px;margin:auto}}
    a{{color:#1f6a52;font-weight:800}}
    .status{{max-width:1180px;margin:0 auto 16px;padding:12px 16px;border-radius:16px;background:#eef7f3;color:#1f6a52;font-weight:800}}
    main{{max-width:1180px;margin:auto;padding:0 20px 40px}}
  </style>
</head>
<body>
  <header>
    <a href=\"/\">← Volver al panel</a>
    <h1>{title}</h1>
    <p>Calculadora generada automáticamente desde JSON de CCT.</p>
  </header>
  <div class=\"status\" data-generated-calculator-status>Cargando calculadora...</div>
  <main data-generated-calculator-root></main>
  <script type=\"application/json\" id=\"calculator-payload\">{payload_json}</script>
  <script type=\"module\" src=\"/js/generated-calculator-page.js\"></script>
</body>
</html>
"""


def load_calculators() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        convenio = payload.get("convenio") if isinstance(payload.get("convenio"), dict) else {}
        slug = path.stem
        items.append({"slug": slug, "url": f"/calculadoras/{slug}.html", "nombre": convenio.get("nombre") or slug, "actividad": convenio.get("actividad"), "categorias": len(payload.get("categorias") or []), "adicionales": len(payload.get("adicionales") or []), "creado_en": payload.get("creado_en")})
    return items


def dashboard_html() -> str:
    calculators = load_calculators()
    cards = "".join(f"""
      <article class=\"card\">
        <h3>{html.escape(str(item['nombre']))}</h3>
        <p>{html.escape(str(item.get('actividad') or 'Sin actividad cargada'))}</p>
        <small>{item['categorias']} categorías · {item['adicionales']} adicionales</small>
        <a href=\"{item['url']}\">Abrir calculadora</a>
      </article>
    """ for item in calculators) or "<p>No hay calculadoras creadas todavía. Creá una desde el importador de FormX.ai.</p>"
    return f"""<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Calculadoras CCT</title><style>
      body{{margin:0;font-family:Inter,system-ui,Arial,sans-serif;background:#fff8ef;color:#1b2321}}
      .hero{{padding:36px;max-width:1180px;margin:auto}}
      .grid{{max-width:1180px;margin:auto;padding:0 24px 40px;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}
      .card{{background:white;border:1px solid rgba(0,0,0,.08);border-radius:22px;padding:18px;box-shadow:0 16px 45px rgba(0,0,0,.08)}}
      .card a,.hero a{{display:inline-block;margin-top:12px;border-radius:14px;background:#1f6a52;color:white;text-decoration:none;padding:11px 14px;font-weight:800}}
      .card p{{color:#53615d}} .card small{{color:#53615d;font-weight:800}}
    </style></head><body><section class=\"hero\"><h1>Panel de calculadoras CCT</h1><p>Acá aparecen las calculadoras HTML generadas automáticamente.</p><a href=\"/constructor.html\">Crear nueva calculadora</a></section><section class=\"grid\">{cards}</section></body></html>"""


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "ai_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()), "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL), "env_file_loaded": ENV_FILE.exists()}


@app.get("/")
def dashboard() -> Any:
    return FileResponse(write_dashboard())


def write_dashboard() -> Path:
    path = ROOT_DIR / "index.html"
    path.write_text(dashboard_html(), encoding="utf-8")
    return path


@app.post("/audit")
def audit(payload: AuditRequest) -> dict[str, Any]:
    prompt = build_prompt(payload.model_dump())
    try:
        text = call_gemini(prompt, os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    except GeminiProxyError as exc:
        status_code = 503 if "API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"mode": "gemini", "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL), "text": text}


@app.post("/extract-cct")
def extract_cct(payload: CctExtractionRequest) -> dict[str, Any]:
    return extract_cct_from_text(payload.file_name, payload.text)


@app.post("/extract-cct-pdf")
async def extract_cct_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF.")
    content = await file.read()
    text = extract_text_from_pdf_bytes(content)
    return extract_cct_from_text(file.filename, text)


@app.get("/calculadoras-list")
def calculators_list() -> dict[str, Any]:
    return {"items": load_calculators()}


@app.post("/create-calculator-page")
def create_calculator_page(request: CalculatorPageRequest) -> dict[str, Any]:
    CALCULATORS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = normalize_calculator_payload(request.payload, str(request.payload.get("archivo_fuente") or "formx.json"))
    slug = calculator_slug(payload)
    payload["slug"] = slug
    payload["creado_en"] = datetime.now().isoformat(timespec="seconds")
    json_path = DATA_DIR / f"{slug}.json"
    html_path = CALCULATORS_DIR / f"{slug}.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(calculator_html(payload, slug), encoding="utf-8")
    write_dashboard()
    return {"ok": True, "slug": slug, "url": f"/calculadoras/{slug}.html", "dashboard_url": "/"}


app.mount("/", StaticFiles(directory=str(ROOT_DIR), html=True), name="static")
