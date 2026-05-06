from __future__ import annotations

import argparse
import json
import os
import posixpath
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from backend.gemini_proxy import DEFAULT_MODEL, GeminiProxyError, build_prompt, call_gemini


ROOT_DIR = Path(__file__).resolve().parents[1]


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
                    "ai_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
                    "model": DEFAULT_MODEL,
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
            prompt = build_prompt(payload)
            text = call_gemini(prompt, DEFAULT_MODEL)
        except GeminiProxyError as exc:
            status = HTTPStatus.SERVICE_UNAVAILABLE if "API_KEY" in str(exc) else HTTPStatus.BAD_GATEWAY
            self._json({"detail": str(exc)}, status=status)
            return

        self._json({"mode": "gemini", "model": DEFAULT_MODEL, "text": text})

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
