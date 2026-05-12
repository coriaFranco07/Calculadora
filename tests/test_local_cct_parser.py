import pytest

from backend.app import (
    extract_antiguedad_rule,
    extract_generic_salary_lines,
    extract_smata_aca_salary_annex,
    extract_zone_rule,
)


SMATA_SAMPLE = """ANEXO SMATA - ACA
Escalas salariales
Auxilio Mecánico
Oficial superior 1.395,35 1.789,00
Oficial de Primera 1.297,62 1.656,00
Playeros y expendedores de combustibles
Oficial Superior 946,84 1.122,00 210,00
Administrativos - ExpoACA
Administrativo A 1.100,00
"""


def find_scale(scales, category, rama_contains=None):
    for scale in scales:
        same_category = scale.get("categoria", "").lower() == category.lower()
        same_rama = not rama_contains or rama_contains.lower() in (scale.get("rama") or "").lower()
        if same_category and same_rama:
            return scale
    raise AssertionError(f"No se encontro escala para {rama_contains or '*'} / {category}")


def test_generic_salary_lines_extracts_linear_annex():
    result = extract_generic_salary_lines(SMATA_SAMPLE)

    assert len(result["categorias"]) >= 4
    assert len(result["escalas_salariales"]) >= 4


def test_smata_aca_annex_extracts_article_11_and_multifunctionality():
    result = extract_smata_aca_salary_annex(SMATA_SAMPLE)
    scales = result["escalas_salariales"]

    auxilio = find_scale(scales, "Oficial superior", "Auxilio")
    playero = find_scale(scales, "Oficial Superior", "Playeros")
    admin = find_scale(scales, "Administrativo A", "Administrativos")

    assert auxilio["basico_mensual"] == pytest.approx(1395.35)
    assert auxilio["articulo_11"] == pytest.approx(1789)
    assert playero["multifuncionalidad"] == pytest.approx(210)
    assert admin["basico_mensual"] == pytest.approx(1100)


def test_zone_rule_prefers_art_56_thirty_percent():
    rule = extract_zone_rule(
        "Art. 56 - Neuquén, Río Negro, Chubut, Santa Cruz y Tierra del Fuego "
        "percibirán un adicional del 30%."
    )

    assert rule is not None
    assert rule["porcentaje"] == 30


def test_antiguedad_rule_builds_1_to_30_scale():
    text = (
        "ADICIONAL POR ANTIGÜEDAD SOBRE SALARIO DE CONVENIO DE $ 1.100\n"
        "AÑO %\n"
        + "\n".join(f"{year} {year}%" for year in range(1, 31))
    )

    rule = extract_antiguedad_rule(text)

    assert rule is not None
    assert rule["base_monto"] == 1100
    assert len(rule["escala"]) == 30
    assert rule["escala"][0] == {"anio": 1, "porcentaje": 1}
    assert rule["escala"][-1] == {"anio": 30, "porcentaje": 30}
