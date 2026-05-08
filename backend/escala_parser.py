"""Salary-scale helpers layered on top of the local CCT parser."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.cct_parser import parse_document


def _parse_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value)
    cleaned = re.sub(r"[^\d,.-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def build_local_escala_payload(ocr_payload: dict[str, Any], file_name: str) -> dict[str, Any]:
    return parse_document(ocr_payload, kind="scale", file_name=file_name, provider="PDF local + Parser")


def normalize_salary_scales(payload: dict[str, Any], *, file_name: str = "") -> list[dict[str, Any]]:
    """Build the canonical salary-scale array requested by the generator."""

    scales: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for category in payload.get("categorias", []) or []:
        if not isinstance(category, dict):
            continue
        name = str(category.get("nombre") or category.get("categoria") or "").strip()
        if not name:
            continue

        basico = _parse_money(category.get("basico"))
        valor_hora = _parse_money(category.get("valor_hora"))
        jornada = str(category.get("jornada") or category.get("modalidad") or "").strip()
        vigencia_desde = str(category.get("vigencia_desde") or payload.get("vigencia_desde") or "").strip()
        vigencia_hasta = str(category.get("vigencia_hasta") or payload.get("vigencia_hasta") or "").strip()
        tipo = str(category.get("tipo") or ("hora" if valor_hora and not basico else "mensual")).strip()
        fuente = str(category.get("fuente_textual") or category.get("fuente") or file_name).strip()
        key = (name.lower(), vigencia_desde, jornada.lower(), tipo.lower())
        if key in seen:
            continue
        seen.add(key)
        scales.append(
            {
                "categoria": name,
                "basico": basico,
                "valor_hora": valor_hora,
                "vigencia_desde": vigencia_desde or None,
                "vigencia_hasta": vigencia_hasta or None,
                "jornada": jornada or None,
                "tipo": tipo or None,
                "fuente_textual": fuente or None,
            }
        )

    for scale in payload.get("escalas_salariales", []) or []:
        if not isinstance(scale, dict):
            continue
        name = str(scale.get("categoria") or scale.get("nombre") or "").strip()
        if not name:
            continue
        key = (
            name.lower(),
            str(scale.get("vigencia_desde") or "").strip(),
            str(scale.get("jornada") or "").strip().lower(),
            str(scale.get("tipo") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        scales.append(
            {
                "categoria": name,
                "basico": _parse_money(scale.get("basico")),
                "valor_hora": _parse_money(scale.get("valor_hora")),
                "vigencia_desde": scale.get("vigencia_desde") or None,
                "vigencia_hasta": scale.get("vigencia_hasta") or None,
                "jornada": scale.get("jornada") or None,
                "tipo": scale.get("tipo") or None,
                "fuente_textual": scale.get("fuente_textual") or file_name or None,
            }
        )

    return scales
