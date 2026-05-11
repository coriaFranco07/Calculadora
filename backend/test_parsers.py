"""
Test suite for CCT/Salary scale parsers.

Run with: python -m pytest backend/test_parsers.py -v
Or directly: python backend/test_parsers.py
"""

from backend.cct_parser import (
    extract_generic_salary_lines,
    SmatAcaParser,
    extract_smata_aca_salary_annex,
    parse_document,
    run_specialized_parsers,
)


def test_generic_parser_simple_line():
    """Test: extract_generic_salary_lines extracts a simple salary line."""
    text = "Oficial superior 1.395,35 1.789,00"
    result = extract_generic_salary_lines(text)

    assert len(result["escalas_salariales"]) > 0, "No salary scales detected"
    escala = result["escalas_salariales"][0]
    assert escala["basico_mensual"] == 1395.35, f"Expected 1395.35, got {escala['basico_mensual']}"
    assert escala["adicional_1"] == 1789.00, f"Expected 1789.00, got {escala['adicional_1']}"
    print("✓ Test: generic parser simple line PASSED")


def test_generic_parser_multiple_montos():
    """Test: extract_generic_salary_lines with 3 montos."""
    text = "Oficial Superior 946,84 1.122,00 210,00"
    result = extract_generic_salary_lines(text)

    assert len(result["escalas_salariales"]) > 0
    escala = result["escalas_salariales"][0]
    assert escala["basico_mensual"] == 946.84
    assert escala["adicional_1"] == 1122.00
    assert escala["adicional_2"] == 210.00
    print("✓ Test: generic parser multiple montos PASSED")


def test_generic_parser_rama_detection():
    """Test: extract_generic_salary_lines detects branches."""
    text = """
Auxilio Mecánico
Oficial superior 1.395,35 1.789,00
Playeros y expendedores de combustibles
Oficial Superior 946,84 1.122,00
"""
    result = extract_generic_salary_lines(text)

    assert len(result["escalas_salariales"]) >= 2
    # Check that ramas are assigned
    ramas = [esc.get("rama") for esc in result["escalas_salariales"]]
    assert any(rama for rama in ramas), "No ramas detected"
    print("✓ Test: generic parser rama detection PASSED")


def test_smata_aca_can_handle():
    """Test: SmatAcaParser.can_handle detects SMATA ACA CCT."""
    parser = SmatAcaParser()

    # Should detect SMATA ACA
    assert parser.can_handle("CCT 454/2006 SMATA - ACA")
    assert parser.can_handle("ANEXO SMATA - ACA Escalas salariales")
    assert parser.can_handle("Convenio Colectivo 454/2006")

    # Should not detect other convenios
    assert not parser.can_handle("CCT 123/2020 Other Convenio")
    print("✓ Test: SMATA ACA parser can_handle PASSED")


def test_smata_aca_parse_simple():
    """Test: SmatAcaParser parses a simple SMATA line."""
    parser = SmatAcaParser()
    text = """
ANEXO SMATA - ACA
Escalas salariales

Auxilio Mecánico
Oficial superior 1.395,35 1.789,00
"""
    result = parser.parse(text)

    assert len(result["escalas_salariales"]) > 0
    escala = result["escalas_salariales"][0]
    assert escala.get("articulo_11") == 1789.00 or escala.get("adicional_1") == 1789.00
    print("✓ Test: SMATA ACA parser simple PASSED")


def test_smata_aca_subsidios():
    """Test: SmatAcaParser extracts subsidios."""
    parser = SmatAcaParser()
    text = """
ANEXO SMATA - ACA
Subsidios por Casamiento 280,00
Subsidios por Nacimiento 280,00
Subsidios por Fallecimiento hijos/cónyuge 560,00
"""
    result = parser.parse(text)

    subsidios = result.get("subsidios", [])
    # Should have at least casamiento
    nombres = [s.get("nombre", "").lower() for s in subsidios]
    assert any("casamiento" in n for n in nombres), f"Casamiento not found in {nombres}"
    print("✓ Test: SMATA ACA subsidios PASSED")


def test_smata_aca_antiguedad():
    """Test: SmatAcaParser extracts antiguedad rule."""
    parser = SmatAcaParser()
    text = """
ADICIONAL POR ANTIGÜEDAD SOBRE SALARIO DE CONVENIO DE $ 1.100
AÑO % 
1 1%
2 2%
...
30 30%
"""
    result = parser.parse(text)

    antiguedad = result.get("antiguedad")
    assert antiguedad is not None, "Antiguedad rule not found"
    assert antiguedad.get("base_monto") == 1100, f"Expected base 1100, got {antiguedad.get('base_monto')}"
    assert antiguedad.get("tipo") == "porcentaje_por_anio"
    print("✓ Test: SMATA ACA antiguedad PASSED")


def test_smata_aca_zona():
    """Test: SmatAcaParser extracts zona desfavorable rule."""
    parser = SmatAcaParser()
    text = """
Art. 56 - CONDICIONES ESPECIALES PARA PROVINCIAS NEUQUÉN, RÍO NEGRO, 
CHUBUT, SANTA CRUZ Y TIERRA DEL FUEGO TREINTA POR CIENTO SOBRE LA REMUNERACIÓN
"""
    result = parser.parse(text)

    zona = result.get("zona_desfavorable")
    assert zona is not None, "Zona desfavorable not found"
    assert zona.get("porcentaje") == 30, f"Expected 30%, got {zona.get('porcentaje')}"
    assert "Neuquén" in zona.get("provincias", [])
    print("✓ Test: SMATA ACA zona desfavorable PASSED")


def test_specialized_parsers_registry():
    """Test: run_specialized_parsers uses registered parsers."""
    text = """
CCT 454/2006 SMATA - ACA
ANEXO SMATA - ACA
Oficial superior 1.395,35 1.789,00
"""
    result = run_specialized_parsers(text)

    # Should have detected something via SMATA parser
    assert len(result.get("escalas_salariales", [])) > 0
    print("✓ Test: specialized parsers registry PASSED")


def test_smata_aca_annex_text_lineal():
    """Test: extract_smata_aca_salary_annex parses lineal annex text."""
    text = """
ANEXO SMATA - ACA
Escalas salariales
Auxilio MecÃ¡nico
Oficial superior 1.395,35 1.789,00
Oficial de Primera 1.297,62 1.656,00
Playeros y expendedores de combustibles
Oficial Superior 946,84 1.122,00 210,00
Administrativos - ExpoACA
Administrativo A 1.100,00
"""
    result = extract_smata_aca_salary_annex(text)

    assert len(result["categorias"]) >= 4
    assert len(result["escalas_salariales"]) >= 4

    from backend.cct_parser import normalize_text

    oficial_superior = next(
        esc for esc in result["escalas_salariales"]
        if normalize_text(esc.get("rama")) == normalize_text("Auxilio Mecánico") and esc.get("categoria") == "Oficial superior"
    )
    assert oficial_superior["basico_mensual"] == 1395.35
    assert oficial_superior["articulo_11"] == 1789.00

    playeros = next(
        esc for esc in result["escalas_salariales"]
        if normalize_text(esc.get("rama")) == normalize_text("Playeros y expendedores de combustibles") and esc.get("categoria") == "Oficial Superior"
    )
    assert playeros["multifuncionalidad"] == 210.00

    administrativo = next(
        esc for esc in result["escalas_salariales"]
        if normalize_text(esc.get("rama")) == normalize_text("Administrativos - ExpoACA") and esc.get("categoria") == "Administrativo A"
    )
    assert administrativo["basico_mensual"] == 1100.00
    print("âœ“ Test: SMATA ACA lineal annex PASSED")


def test_parse_document_merges_local_scales_for_cct():
    """Test: parse_document(kind='cct') keeps local scales and categories."""
    text = """
ANEXO SMATA - ACA
Escalas salariales
Auxilio MecÃ¡nico
Oficial superior 1.395,35 1.789,00
Oficial de Primera 1.297,62 1.656,00
Playeros y expendedores de combustibles
Oficial Superior 946,84 1.122,00 210,00
Administrativos - ExpoACA
Administrativo A 1.100,00
"""
    payload = parse_document(
        {"markdown": text, "text": text, "pages": [], "tables": []},
        kind="cct",
        file_name="smata_aca.pdf",
    )

    assert len(payload.get("categorias") or []) >= 4
    assert len(payload.get("escalas_salariales") or []) >= 4
    assert any(esc.get("articulo_11") == 1789.00 for esc in payload["escalas_salariales"])
    assert any(esc.get("multifuncionalidad") == 210.00 for esc in payload["escalas_salariales"])
    print("âœ“ Test: parse_document merges local scales PASSED")


def test_generic_no_null_subsidios():
    """Test: extract_generic_salary_lines doesn't return subsidios with null values."""
    text = "Subsidios por Casamiento"  # No monto
    result = extract_generic_salary_lines(text)

    # Shouldn't create scales for text with no numbers
    escalas = result.get("escalas_salariales", [])
    for escala in escalas:
        assert escala.get("basico_mensual") is not None or escala.get("adicional_1") is not None


def test_generic_ignores_long_text():
    """Test: extract_generic_salary_lines ignores legal text."""
    text = """
Acuerdo marco entre el sindicato y la empresa para la aplicación de nuevas
disposiciones sobre liquidación de haberes y cálculo de la antigüedad.
Resolución MTESS 123/2024 Boletín Oficial República Argentina
"""
    result = extract_generic_salary_lines(text)

    # Should not create categories from legal text
    assert len(result["categorias"]) == 0, "Legal text should not create categories"
    print("✓ Test: generic parser ignores legal text PASSED")


def test_zone_desfavorable_never_zero():
    """Test: zona_desfavorable is never 0 if source mentions a percentage."""
    from backend.cct_parser import normalize_zona_desfavorable

    payload = {
        "reglas_liquidacion": {
            "zona_desfavorable": {
                "porcentaje": 0,
                "fuente_textual": "Art. 56 30% for patagonia",
            }
        }
    }
    normalize_zona_desfavorable(payload)
    zona = payload["reglas_liquidacion"]["zona_desfavorable"]
    assert zona["porcentaje"] != 0, "Zona should not be 0 if source mentions percentage"
    print("✓ Test: zona_desfavorable never zero PASSED")


def test_antiguedad_escala_complete():
    """Test: antiguedad rule has complete 1-30 year escala."""
    from backend.cct_parser import normalize_antiguedad_rule

    payload = {
        "reglas_liquidacion": {
            "antiguedad": {
                "tipo": "porcentaje_por_anio",
                "porcentaje_por_anio": 1,
                "base_monto": 1100,
                "fuente_textual": "text",
            }
        }
    }
    normalize_antiguedad_rule(payload)
    escala = payload["reglas_liquidacion"]["antiguedad"].get("escala", [])
    assert len(escala) == 30, f"Expected 30-year escala, got {len(escala)}"
    assert escala[0]["anio"] == 1 and escala[0]["porcentaje"] == 1
    assert escala[29]["anio"] == 30 and escala[29]["porcentaje"] == 30
    print("✓ Test: antiguedad escala complete PASSED")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("RUNNING CCT/SALARY SCALE PARSER TESTS")
    print("=" * 70 + "\n")

    tests = [
        test_generic_parser_simple_line,
        test_generic_parser_multiple_montos,
        test_generic_parser_rama_detection,
        test_smata_aca_can_handle,
        test_smata_aca_parse_simple,
        test_smata_aca_subsidios,
        test_smata_aca_antiguedad,
        test_smata_aca_zona,
        test_specialized_parsers_registry,
        test_smata_aca_annex_text_lineal,
        test_parse_document_merges_local_scales_for_cct,
        test_generic_ignores_long_text,
        test_zone_desfavorable_never_zero,
        test_antiguedad_escala_complete,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"✗ Test: {test_func.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ Test: {test_func.__name__} ERROR: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70 + "\n")

    if failed > 0:
        exit(1)
