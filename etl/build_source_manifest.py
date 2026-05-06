from __future__ import annotations

import hashlib
import json
from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "source_manifest.json"

DEFAULT_SOURCES = [
    r"C:\Users\Lenovo Ideapad\Downloads\Alimentación, CCT 244_1994. Convenio colectivo. Texto ordenado.pdf",
    r"C:\Users\Lenovo Ideapad\Downloads\Alimentación. Obreros y empleados, CCT 244_1994. Incremento salarial no remunerativo a partir de marzo. Nuevas escalas salariales a partir de abril de 2026.pdf",
    r"C:\Users\Lenovo Ideapad\Downloads\Alimentación. Obreros y empleados, CCT 244_1994. Tope indemnizatorio desde 1_5_2024, 1_6_2024, 1_7_2024 y 1_8_2024.pdf",
    r"C:\Users\Lenovo Ideapad\Downloads\Copia de LEY 20744 - LEY DE CONTRATO DE TRABAJO _ Argentina.gob.ar.pdf",
]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_pages(path: Path) -> int | None:
    if PdfReader is None or path.suffix.lower() != ".pdf":
        return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def build_manifest(paths: list[str]) -> dict:
    records = []
    for raw in paths:
        path = Path(raw)
        records.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else None,
                "sha256": file_hash(path) if path.exists() else None,
                "pdf_pages": pdf_pages(path) if path.exists() else None,
            }
        )
    return {
        "version": "2026.05.06",
        "records": records,
    }


if __name__ == "__main__":
    manifest = build_manifest(DEFAULT_SOURCES)
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest generado en {OUTPUT}")
