"""Production PDF extraction helpers for CCT and salary-scale documents.

The extractor intentionally combines several real strategies:
- PyMuPDF/pdfplumber/pypdf text extraction.
- pdfplumber/camelot/tabula table extraction converted to markdown.
- pytesseract OCR fallback for scanned PDFs when selectable text is weak.

All optional extractors are loaded lazily so the backend can start even when a
system dependency is missing. Missing OCR/table tools are reported in metrics
and alerts instead of being silently ignored.
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader

logger = logging.getLogger(__name__)


MAX_CHUNK_CHARS = 42_000
CHUNK_OVERLAP_CHARS = 1_200
REPEATED_LINE_LIMIT = 4
MIN_TEXT_CHARS_BEFORE_OCR = 900
MONEY_PATTERN = re.compile(r"(?:\$|\b)(\d{1,3}(?:\.\d{3})*(?:,\d{2})|\d{4,}(?:[.,]\d{2})?)")


@dataclass(slots=True)
class PdfPageText:
    page_number: int
    text: str
    text_length: int
    extractor: str = "unknown"


@dataclass(slots=True)
class PdfTable:
    page_number: int | None
    header: list[str]
    rows: list[list[str]]
    markdown: str
    extractor: str


@dataclass(slots=True)
class PdfExtractionResult:
    file_name: str
    text: str
    pages: list[PdfPageText]
    chunks: list[str]
    text_length: int
    page_count: int
    tables: list[PdfTable] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_ocr_payload(self, provider: str = "PDF real + Gemini") -> dict[str, Any]:
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
                    "extractor": page.extractor,
                }
                for page in self.pages
            ],
            "tables": [
                {
                    "page_number": table.page_number,
                    "header": table.header,
                    "rows": table.rows,
                    "markdown": table.markdown,
                    "extractor": table.extractor,
                }
                for table in self.tables
            ],
            "chunks": self.chunks,
            "text_length": self.text_length,
            "page_count": self.page_count,
            "alerts": list(self.alerts),
            "metrics": dict(self.metrics),
            "ocr_active": bool(self.metrics.get("ocr_active")),
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
        if len(line) < 90 and seen_counts[fingerprint] > REPEATED_LINE_LIMIT:
            continue
        cleaned.append(line)

    return "\n".join(cleaned).strip()


def _optional_import(module_name: str) -> Any | None:
    try:
        return __import__(module_name)
    except Exception as exc:
        logger.info("Extractor opcional no disponible: %s (%s)", module_name, exc)
        return None


def _clean_cell(value: Any) -> str:
    return normalize_pdf_text(str(value or ""), deduplicate=False).replace("\n", " ").strip()


def _markdown_table(rows: list[list[Any]]) -> tuple[list[str], list[list[str]], str] | None:
    cleaned = [[_clean_cell(cell) for cell in row] for row in rows if any(_clean_cell(cell) for cell in row)]
    if len(cleaned) < 2:
        return None

    width = max(len(row) for row in cleaned)
    normalized_rows = [row + [""] * (width - len(row)) for row in cleaned]
    header = normalized_rows[0]
    body = normalized_rows[1:]
    if not any(cell for cell in header) or not body:
        return None

    markdown_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *["| " + " | ".join(row) + " |" for row in body],
    ]
    markdown = "\n".join(markdown_lines)
    return header, body, markdown


def _dedupe_tables(tables: list[PdfTable]) -> list[PdfTable]:
    result: list[PdfTable] = []
    seen: set[str] = set()
    for table in tables:
        fingerprint = re.sub(r"\s+", " ", table.markdown.lower()).strip()
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(table)
    return result


def _extract_text_pypdf(pdf_bytes: bytes) -> tuple[list[PdfPageText], int]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[PdfPageText] = []
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:
            logger.warning("pypdf no pudo extraer página %s: %s", page_index, exc)
            raw_text = ""
        text = normalize_pdf_text(raw_text, deduplicate=False)
        pages.append(PdfPageText(page_number=page_index, text=text, text_length=len(text), extractor="pypdf"))
    return pages, len(reader.pages)


def _extract_text_pymupdf(pdf_bytes: bytes) -> list[PdfPageText]:
    fitz = _optional_import("fitz")
    if fitz is None:
        return []
    pages: list[PdfPageText] = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            for page_index, page in enumerate(document, start=1):
                text = normalize_pdf_text(page.get_text("text") or "", deduplicate=False)
                pages.append(PdfPageText(page_number=page_index, text=text, text_length=len(text), extractor="pymupdf"))
    except Exception as exc:
        logger.warning("PyMuPDF no pudo extraer texto: %s", exc)
    return pages


def _extract_text_pdfplumber(pdf_bytes: bytes) -> list[PdfPageText]:
    pdfplumber = _optional_import("pdfplumber")
    if pdfplumber is None:
        return []
    pages: list[PdfPageText] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                text = normalize_pdf_text(page.extract_text(x_tolerance=1, y_tolerance=3) or "", deduplicate=False)
                pages.append(PdfPageText(page_number=page_index, text=text, text_length=len(text), extractor="pdfplumber"))
    except Exception as exc:
        logger.warning("pdfplumber no pudo extraer texto: %s", exc)
    return pages


def _extract_tables_pdfplumber(pdf_bytes: bytes) -> list[PdfTable]:
    pdfplumber = _optional_import("pdfplumber")
    if pdfplumber is None:
        return []
    tables: list[PdfTable] = []
    settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "intersection_tolerance": 5,
    }
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                page_tables = page.extract_tables(table_settings=settings) or page.extract_tables() or []
                for rows in page_tables:
                    parsed = _markdown_table(rows)
                    if parsed is None:
                        continue
                    header, body, markdown = parsed
                    tables.append(PdfTable(page_number=page_index, header=header, rows=body, markdown=markdown, extractor="pdfplumber"))
    except Exception as exc:
        logger.warning("pdfplumber no pudo extraer tablas: %s", exc)
    return tables


def _with_temp_pdf(pdf_bytes: bytes) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(pdf_bytes)
        return Path(tmp.name)
    finally:
        tmp.close()


def _extract_tables_camelot(pdf_bytes: bytes) -> list[PdfTable]:
    camelot = _optional_import("camelot")
    if camelot is None:
        return []
    tmp_path = _with_temp_pdf(pdf_bytes)
    tables: list[PdfTable] = []
    try:
        for flavor in ("lattice", "stream"):
            try:
                extracted = camelot.read_pdf(str(tmp_path), pages="all", flavor=flavor)
            except Exception as exc:
                logger.info("camelot %s no pudo extraer tablas: %s", flavor, exc)
                continue
            for table in extracted:
                rows = table.df.values.tolist()
                parsed = _markdown_table(rows)
                if parsed is None:
                    continue
                header, body, markdown = parsed
                page = int(getattr(table, "page", 0) or 0) or None
                tables.append(PdfTable(page_number=page, header=header, rows=body, markdown=markdown, extractor=f"camelot-{flavor}"))
            if tables:
                break
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    return tables


def _extract_tables_tabula(pdf_bytes: bytes) -> list[PdfTable]:
    tabula = _optional_import("tabula")
    if tabula is None:
        return []
    tmp_path = _with_temp_pdf(pdf_bytes)
    tables: list[PdfTable] = []
    try:
        try:
            extracted = tabula.read_pdf(str(tmp_path), pages="all", multiple_tables=True, lattice=True)
        except Exception:
            extracted = tabula.read_pdf(str(tmp_path), pages="all", multiple_tables=True, stream=True)
        for index, dataframe in enumerate(extracted or [], start=1):
            rows = [list(dataframe.columns)] + dataframe.fillna("").astype(str).values.tolist()
            parsed = _markdown_table(rows)
            if parsed is None:
                continue
            header, body, markdown = parsed
            tables.append(PdfTable(page_number=None, header=header, rows=body, markdown=markdown, extractor=f"tabula-{index}"))
    except Exception as exc:
        logger.info("tabula no pudo extraer tablas: %s", exc)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    return tables


def _extract_ocr_pages(pdf_bytes: bytes) -> list[PdfPageText]:
    fitz = _optional_import("fitz")
    pytesseract = _optional_import("pytesseract")
    if fitz is None or pytesseract is None:
        return []
    try:
        from PIL import Image
    except Exception as exc:
        logger.info("Pillow no disponible para OCR: %s", exc)
        return []

    pages: list[PdfPageText] = []
    lang = os.getenv("OCR_LANG", "spa+eng")
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            for page_index, page in enumerate(document, start=1):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                try:
                    raw_text = pytesseract.image_to_string(image, lang=lang)
                except Exception:
                    raw_text = pytesseract.image_to_string(image)
                text = normalize_pdf_text(raw_text, deduplicate=False)
                pages.append(PdfPageText(page_number=page_index, text=text, text_length=len(text), extractor="pytesseract"))
    except Exception as exc:
        logger.warning("OCR fallback no pudo procesar el PDF: %s", exc)
    return pages


def _best_pages(page_sets: list[list[PdfPageText]], page_count: int) -> list[PdfPageText]:
    best: list[PdfPageText] = []
    for page_number in range(1, page_count + 1):
        candidates = [page for pages in page_sets for page in pages if page.page_number == page_number]
        if not candidates:
            best.append(PdfPageText(page_number=page_number, text="", text_length=0, extractor="none"))
            continue
        best.append(max(candidates, key=lambda page: page.text_length))
    return best


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
            step = max_chars - overlap_chars
            for idx in range(0, len(paragraph), step):
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


def _table_section(tables: list[PdfTable]) -> str:
    if not tables:
        return ""
    parts = ["\n\n## TABLAS EXTRAIDAS\n"]
    for index, table in enumerate(tables, start=1):
        page = f"pagina {table.page_number}" if table.page_number else "pagina no informada"
        parts.append(f"\n### Tabla {index} ({page}, {table.extractor})\n{table.markdown}\n")
    return "\n".join(parts)


def _count_money(text: str, tables: list[PdfTable]) -> int:
    table_text = "\n".join(table.markdown for table in tables)
    return len(MONEY_PATTERN.findall(f"{text}\n{table_text}"))


def extract_text_from_pdf_bytes(pdf_bytes: bytes, file_name: str = "documento.pdf") -> PdfExtractionResult:
    """Extract text, tables and OCR fallback from a PDF byte stream."""

    if not pdf_bytes:
        raise ValueError("El PDF está vacío.")

    alerts: list[str] = []
    extractors_used: set[str] = set()

    pypdf_pages, pypdf_page_count = _extract_text_pypdf(pdf_bytes)
    page_sets = [pypdf_pages]
    if any(page.text_length for page in pypdf_pages):
        extractors_used.add("pypdf")

    pymupdf_pages = _extract_text_pymupdf(pdf_bytes)
    if pymupdf_pages:
        page_sets.append(pymupdf_pages)
        extractors_used.add("pymupdf")

    pdfplumber_pages = _extract_text_pdfplumber(pdf_bytes)
    if pdfplumber_pages:
        page_sets.append(pdfplumber_pages)
        extractors_used.add("pdfplumber")

    page_count = max([pypdf_page_count, *[len(pages) for pages in page_sets]], default=0)
    pages = _best_pages(page_sets, page_count)
    base_text = normalize_pdf_text("\n\n".join(page.text for page in pages))

    ocr_active = False
    if len(base_text) < MIN_TEXT_CHARS_BEFORE_OCR:
        ocr_pages = _extract_ocr_pages(pdf_bytes)
        if ocr_pages and sum(page.text_length for page in ocr_pages) > len(base_text):
            pages = _best_pages([pages, ocr_pages], max(page_count, len(ocr_pages)))
            base_text = normalize_pdf_text("\n\n".join(page.text for page in pages))
            ocr_active = True
            extractors_used.add("pytesseract")
        else:
            alerts.append("El PDF tiene poco texto seleccionable y OCR no produjo una mejora útil o no está disponible.")

    tables = _dedupe_tables(
        [
            *_extract_tables_pdfplumber(pdf_bytes),
            *_extract_tables_camelot(pdf_bytes),
            *_extract_tables_tabula(pdf_bytes),
        ]
    )
    if tables:
        extractors_used.update(table.extractor for table in tables)

    combined_text = normalize_pdf_text(f"{base_text}{_table_section(tables)}")
    if not combined_text.strip():
        alerts.append("No se detectó texto ni tablas utilizables en el PDF.")
    elif len(combined_text) < 600:
        alerts.append("El texto extraído es muy corto; revisar si el PDF requiere OCR externo o está incompleto.")

    chunks = smart_chunking(combined_text)
    metrics = {
        "ocr_active": ocr_active,
        "extractors_used": sorted(extractors_used),
        "tables_detected": len(tables),
        "tablas_detectadas": len(tables),
        "montos_detectados": _count_money(combined_text, tables),
        "chunks": len(chunks),
        "text_length": len(combined_text),
        "page_count": len(pages),
    }
    logger.info(
        "PDF extraído: file=%s pages=%s chars=%s chunks=%s tables=%s ocr=%s extractors=%s money=%s",
        file_name,
        len(pages),
        len(combined_text),
        len(chunks),
        len(tables),
        ocr_active,
        ",".join(metrics["extractors_used"]),
        metrics["montos_detectados"],
    )

    return PdfExtractionResult(
        file_name=file_name,
        text=combined_text,
        pages=pages,
        chunks=chunks,
        text_length=len(combined_text),
        page_count=len(pages),
        tables=tables,
        alerts=alerts,
        metrics=metrics,
    )
