from __future__ import annotations

import io
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader


class MistralOCRError(RuntimeError):
    pass


def _import_client():
    try:
        from mistralai import Mistral
    except ImportError as exc:
        raise MistralOCRError(
            "Falta instalar mistralai en el backend. Ejecuta pip install mistralai."
        ) from exc
    return Mistral


def _extract_tables_from_markdown(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if len(current) < 2:
            current = []
            return
        if not any(re.search(r"\|\s*:?-{2,}", line) for line in current):
            current = []
            return
        lines = [line.strip() for line in current if line.strip()]
        header = [cell.strip() for cell in lines[0].strip("|").split("|")]
        rows: list[list[str]] = []
        for line in lines[2:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == len(header):
                rows.append(cells)
        blocks.append({"header": header, "rows": rows, "markdown": "\n".join(lines)})
        current = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if "|" in line:
            current.append(line)
        else:
            flush()
    flush()
    return blocks


def _strip_markdown(markdown: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_`>#-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _local_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages).strip()


def _response_to_pages(response: Any) -> list[dict[str, Any]]:
    raw_pages = getattr(response, "pages", None)
    if raw_pages is None and isinstance(response, dict):
        raw_pages = response.get("pages")

    pages: list[dict[str, Any]] = []
    for index, page in enumerate(raw_pages or []):
        if hasattr(page, "model_dump"):
            page_data = page.model_dump()
        elif isinstance(page, dict):
            page_data = page
        else:
            page_data = {
                "markdown": getattr(page, "markdown", ""),
                "text": getattr(page, "text", ""),
                "page_number": getattr(page, "page_number", index + 1),
            }

        markdown = str(page_data.get("markdown") or "")
        text = str(page_data.get("text") or _strip_markdown(markdown))
        pages.append(
            {
                "page_number": page_data.get("page_number") or index + 1,
                "markdown": markdown,
                "text": text,
                "tables": _extract_tables_from_markdown(markdown),
            }
        )
    return pages


def _upload_and_process(document_bytes: bytes, file_name: str) -> dict[str, Any]:
    api_key = (os.getenv("MISTRAL_API_KEY") or "").strip()
    if not api_key:
        raise MistralOCRError("Falta configurar MISTRAL_API_KEY en el backend.")

    Mistral = _import_client()
    client = Mistral(api_key=api_key)

    suffix = Path(file_name).suffix or ".pdf"
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(document_bytes)
            temp_file.flush()
            temp_path = temp_file.name

        upload_payload = {"file_name": file_name, "content": document_bytes}
        try:
            uploaded = client.files.upload(file=upload_payload, purpose="ocr")
        except TypeError:
            with open(temp_path, "rb") as handle:
                uploaded = client.files.upload(file={"file_name": file_name, "content": handle}, purpose="ocr")

        signed_url = client.files.get_signed_url(file_id=getattr(uploaded, "id", None))
        document_url = getattr(signed_url, "url", None)
        if not document_url:
            raise MistralOCRError("Mistral no devolvio una signed URL util para OCR.")

        response = client.ocr.process(
            model="mistral-ocr-latest",
            document={"type": "document_url", "document_url": document_url},
        )
    except MistralOCRError:
        raise
    except Exception as exc:  # pragma: no cover - defensive for SDK shape changes
        raise MistralOCRError(f"Mistral OCR no pudo procesar el PDF: {exc}") from exc
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass

    pages = _response_to_pages(response)
    markdown = "\n\n".join(page["markdown"] for page in pages if page.get("markdown")).strip()
    text = "\n\n".join(page["text"] for page in pages if page.get("text")).strip() or _strip_markdown(markdown)
    tables: list[dict[str, Any]] = []
    for page in pages:
        tables.extend(page.get("tables") or [])

    return {
        "provider": "mistral",
        "model": "mistral-ocr-latest",
        "file_name": file_name,
        "markdown": markdown,
        "text": text,
        "tables": tables,
        "pages": pages,
        "fallback_local": False,
    }


def _extract_local_fallback(document_bytes: bytes, file_name: str, reason: str) -> dict[str, Any]:
    import io

    reader = PdfReader(io.BytesIO(document_bytes))
    pages: list[dict[str, Any]] = []
    markdown_parts: list[str] = []
    for index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        pages.append({"page_number": index + 1, "markdown": text, "text": text, "tables": []})
        if text:
            markdown_parts.append(text)

    markdown = "\n\n".join(markdown_parts).strip()
    return {
        "provider": "local-pdf",
        "model": "pypdf-fallback",
        "file_name": file_name,
        "markdown": markdown,
        "text": markdown,
        "tables": [],
        "pages": pages,
        "fallback_local": True,
        "fallback_reason": reason,
    }


def extract_pdf_bytes(pdf_bytes: bytes, *, file_name: str = "document.pdf") -> dict[str, Any]:
    try:
        return _upload_and_process(pdf_bytes, file_name)
    except MistralOCRError as exc:
        fallback = _extract_local_fallback(pdf_bytes, file_name, str(exc))
        if fallback.get("text"):
            return fallback
        raise


def extract_pdf_markdown(pdf_path: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(pdf_path)
    return extract_pdf_bytes(path.read_bytes(), file_name=path.name)
