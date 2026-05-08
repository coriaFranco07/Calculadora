"""PDF text extraction and chunking helpers for CCT/salary-scale documents."""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfReader

logger = logging.getLogger(__name__)


MAX_CHUNK_CHARS = 42_000
CHUNK_OVERLAP_CHARS = 1_200
REPEATED_LINE_LIMIT = 4


@dataclass(slots=True)
class PdfPageText:
    page_number: int
    text: str
    text_length: int


@dataclass(slots=True)
class PdfExtractionResult:
    file_name: str
    text: str
    pages: list[PdfPageText]
    chunks: list[str]
    text_length: int
    page_count: int
    alerts: list[str] = field(default_factory=list)

    def to_ocr_payload(self, provider: str = "PDF local + Gemini") -> dict[str, Any]:
        return {
            "provider": provider,
            "file_name": self.file_name,
            "markdown": self.text,
            "text": self.text,
            "pages": [
                {
                    "page_number": page.page_number,
                    "markdown": page.text,
                    "text": page.text,
                    "text_length": page.text_length,
                }
                for page in self.pages
            ],
            "tables": [],
            "chunks": self.chunks,
            "text_length": self.text_length,
            "page_count": self.page_count,
            "alerts": list(self.alerts),
        }


def normalize_pdf_text(text: str, *, deduplicate: bool = True) -> str:
    """Normalize extracted PDF/OCR text without losing legal wording."""

    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\u00a0", " ").replace("\ufeff", "")
    normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", normalized)
    normalized = re.sub(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ])-+\s*\n\s*([a-záéíóúüñ])", r"\1\2", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    lines = [line.strip() for line in normalized.splitlines()]
    if not deduplicate:
        return "\n".join(line for line in lines if line).strip()

    seen_counts: dict[str, int] = {}
    cleaned: list[str] = []
    for line in lines:
        if not line:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        fingerprint = re.sub(r"\d+", "#", line.lower())
        fingerprint = re.sub(r"\s+", " ", fingerprint).strip()
        seen_counts[fingerprint] = seen_counts.get(fingerprint, 0) + 1

        # Keep repeated legal clauses, but trim likely page headers/footers.
        if len(line) < 90 and seen_counts[fingerprint] > REPEATED_LINE_LIMIT:
            continue
        cleaned.append(line)

    return "\n".join(cleaned).strip()


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"(\n\s*\n|(?=\n(?:ART[ÍI]CULO|CL[ÁA]USULA|ANEXO|ESCALA|CATEGOR[ÍI]A)\b))", text, flags=re.IGNORECASE)
    paragraphs: list[str] = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        buffer += part
        if part.strip() == "" or re.match(r"\n\s*\n", part):
            if buffer.strip():
                paragraphs.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        paragraphs.append(buffer.strip())
    return paragraphs or [text]


def smart_chunking(
    text: str,
    *,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """Split long legal/scale text into model-safe chunks with overlap."""

    clean_text = normalize_pdf_text(text)
    if len(clean_text) <= max_chars:
        return [clean_text] if clean_text else []

    chunks: list[str] = []
    current = ""
    for paragraph in _split_paragraphs(clean_text):
        if len(paragraph) > max_chars:
            for idx in range(0, len(paragraph), max_chars - overlap_chars):
                piece = paragraph[idx : idx + max_chars]
                if piece.strip():
                    chunks.append(piece.strip())
            current = ""
            continue

        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current.strip())
            overlap = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = f"{overlap}\n\n{paragraph}".strip()
        else:
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph

    if current.strip():
        chunks.append(current.strip())

    return chunks


def extract_text_from_pdf_bytes(pdf_bytes: bytes, file_name: str = "documento.pdf") -> PdfExtractionResult:
    """Extract, normalize and chunk text from a PDF byte stream."""

    if not pdf_bytes:
        raise ValueError("El PDF está vacío.")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[PdfPageText] = []
    raw_pages: list[str] = []

    for page_index, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:  # pragma: no cover - depends on malformed PDFs
            logger.warning("No se pudo extraer texto de página %s en %s: %s", page_index, file_name, exc)
            raw_text = ""
        page_text = normalize_pdf_text(raw_text, deduplicate=False)
        pages.append(PdfPageText(page_number=page_index, text=page_text, text_length=len(page_text)))
        raw_pages.append(page_text)

    normalized = normalize_pdf_text("\n\n".join(raw_pages))
    alerts: list[str] = []
    if not normalized.strip():
        alerts.append("No se detectó texto seleccionable en el PDF. Puede ser un escaneo sin OCR.")
    elif len(normalized) < 600:
        alerts.append("El texto extraído es muy corto; revisar si el PDF requiere OCR o si está incompleto.")

    chunks = smart_chunking(normalized)
    logger.info(
        "PDF extraído: file=%s pages=%s chars=%s chunks=%s",
        file_name,
        len(pages),
        len(normalized),
        len(chunks),
    )

    return PdfExtractionResult(
        file_name=file_name,
        text=normalized,
        pages=pages,
        chunks=chunks,
        text_length=len(normalized),
        page_count=len(pages),
        alerts=alerts,
    )
