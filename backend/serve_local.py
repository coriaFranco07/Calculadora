from __future__ import annotations

import argparse
import json
import os
import posixpath
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from backend.gemini_proxy import DEFAULT_MODEL, FALLBACK_MODELS, GeminiClientError, call_gemini, gemini_enabled


ROOT_DIR = Path(__file__).resolve().parents[1]


def build_audit_prompt(data: dict) -> str:
    return (
        "Revisá preventivamente esta liquidación laboral argentina. "
        "Devolvé observaciones accionables, riesgos AFIP/LSD, inconsistencias y próximos pasos. "
        "No inventes normativa.\n\nDatos:\n"
        + json.dumps(data, ensure_ascii=False, indent=2)
    )


class LocalHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0].split("#", 1)[0]
        path = posixpath.normpath(unquote(path))
        parts = [part for part in path.split("/") if part and part not in {".", ".."}]
        resolved = ROOT_DIR
        for part in parts:
            resolved = resolved / part
        return str(resolved)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(
                {
                    "status": "ok",
                    "ai_enabled": gemini_enabled(),
                    "model": DEFAULT_MODEL,
                    "fallback_models": FALLBACK_MODELS,
                    "gemini_enabled": gemini_enabled(),
                }
            )
            return

        if self.path in {"/", ""}:
            self.path = "/Calculadora_CCT_244_94_Alimentacion.html"

        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/audit":
            self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"

        try:
            payload = json.loads(raw_body or "{}")
        except json.JSONDecodeError as exc:
            self._json({"detail": f"JSON invalido: {exc.msg}"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            prompt = build_audit_prompt(payload)
            result = call_gemini(
                system_prompt=(
                    "Sos un auditor preventivo senior de payroll argentino, AFIP y Libro de Sueldos Digital. "
                    "Responde breve, claro y accionable."
                ),
                user_prompt=prompt,
                model=DEFAULT_MODEL,
                temperature=0.1,
                max_output_tokens=4096,
                stage="audit",
                response_mime_type="text/plain",
            )
            text = result.text
        except GeminiClientError as exc:
            status = HTTPStatus.SERVICE_UNAVAILABLE if "API_KEY" in str(exc) else HTTPStatus.BAD_GATEWAY
            self._json({"detail": str(exc)}, status=status)
            return

        self._json(
            {
                "mode": "gemini",
                "model": result.model,
                "text": text,
                "usage": result.usage,
                "response_ms": result.response_ms,
                "fallback_used": result.fallback_used,
                "attempts": result.attempts,
            }
        )

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor local sin dependencias para la suite de auditoria.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), LocalHandler)
    print(f"Sirviendo {ROOT_DIR} en http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
