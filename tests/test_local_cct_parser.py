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


def test_generic_salary_lines_ignores_legal_prose_amounts():
    text = """
Art. 33.6 - Independientemente del adicional por trabajo en zona desfavorable establecido.
2) De 501 a 1.000 km desde el lugar de concertacion de la relacion laboral al nuevo lugar de trabajo.
Art. 38 - En el marco de la ley 23551 y la ley 14250.
cuenta 309178/30 del Banco de la Nacion Argentina y cuenta 4001 - 07500 - 6.
"""

    result = extract_generic_salary_lines(text)

    assert result["categorias"] == []
    assert result["escalas_salariales"] == []


def test_generic_salary_lines_extracts_stacked_daily_monthly_scale():
    text = """
9. SALARIOS BASICOS CORRESPONDIENTES AL MES DE FEBRERO DE 1989
Seccion del personal operativo
Conductores
a) Primera categoria:
Los que conducen camiones semirremolques y/o con acoplados.
Percibiran Por dia Por mes
A 144,59 A 3.470,07
b) Segunda categoria:
Por dia Por mes
A 138,92 A 3.334,02
"""

    result = extract_generic_salary_lines(text)
    scales = result["escalas_salariales"]

    primera = find_scale(scales, "Primera categoria", "Conductores")
    segunda = find_scale(scales, "Segunda categoria", "Conductores")

    assert primera["valor_diario"] == pytest.approx(144.59)
    assert primera["basico_mensual"] == pytest.approx(3470.07)
    assert segunda["basico_mensual"] == pytest.approx(3334.02)


def test_generic_salary_lines_extracts_multiline_table_label():
    text = """
ANEXO 1
Valores vigentes hasta el
Remuneracion basica
Grupo "I" Capataces
1ra. categoria:
capataz de
obra
$ 6.472 $ - $
"""

    result = extract_generic_salary_lines(text)
    scale = find_scale(result["escalas_salariales"], "1ra. categoria capataz de obra", "Grupo")

    assert scale["basico_mensual"] == pytest.approx(6472)


def test_generic_salary_lines_ignores_indemnity_cap_pdf():
    text = """
Alimentacion. Obreros y empleados, CCT 244/1994.
Tope indemnizatorio desde 1/5/2024, 1/6/2024, 1/7/2024 y 1/8/2024.
Promedio remuneraciones y tope indemnizatorio $ 850.000 $ 920.000.
"""

    result = extract_generic_salary_lines(text)

    assert result["categorias"] == []
    assert result["escalas_salariales"] == []
