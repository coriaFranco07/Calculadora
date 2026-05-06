from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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


def parse_gemini_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"estado": "respuesta_no_json", "raw": text}


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
    prompt = build_cct_extraction_prompt({"file_name": file_name, "text": text})
    try:
        gemini_text = call_gemini(prompt, os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    except GeminiProxyError as exc:
        status_code = 503 if "API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return {
        "mode": "gemini-cct",
        "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        "text_length": len(text),
        "result": parse_gemini_json(gemini_text),
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


@app.post("/extract-cct-pdf")
async def extract_cct_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF.")
    content = await file.read()
    text = extract_text_from_pdf_bytes(content)
    return extract_cct_from_text(file.filename, text)


app.mount("/", StaticFiles(directory=str(ROOT_DIR), html=True), name="static")
