from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.gemini_proxy import DEFAULT_MODEL, GeminiProxyError, build_prompt, call_gemini

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


app = FastAPI(title="Motor de Auditoria Preventiva Laboral y AFIP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


app.mount("/", StaticFiles(directory=str(ROOT_DIR), html=True), name="static")
