#!/usr/bin/env python
"""
Demo script showing the new parser architecture for SMATA ACA CCT 454/2006.

This demonstrates the two-layer parsing: generic + specialized.
"""

from backend.cct_parser import (
    extract_generic_salary_lines,
    SmatAcaParser,
    run_specialized_parsers,
)
import json


def demo_generic_parser():
    """Demonstrate the generic parser."""
    print("\n" + "=" * 70)
    print("DEMO 1: Generic Salary Line Parser")
    print("=" * 70)

    # Example text from real PDF
    text = """
Auxilio Mecánico
Oficial superior 1.395,35 1.789,00
Oficial de Primera 1.297,62 1.656,00
Oficial Superior 946,84 1.122,00 210,00

Playeros y expendedores de combustibles
Oficial Superior 946,84 1.122,00 210,00
Administrativo A 1.100,00

Maestranza
Maestranza 963,00
"""

    result = extract_generic_salary_lines(text)

    print(f"\n✓ Branches detected: {result['ramas_detectadas']}")
    print(f"✓ Categories found: {len(result['categorias'])}")
    print(f"✓ Salary scales found: {len(result['escalas_salariales'])}\n")

    # Show first few scales
    for i, escala in enumerate(result["escalas_salariales"][:3]):
        print(f"  Scale {i+1}:")
        print(f"    Branch: {escala.get('rama')}")
        print(f"    Category: {escala.get('categoria')}")
        print(f"    Basic: ${escala.get('basico_mensual'):.2f}")
        if escala.get("adicional_1"):
            print(f"    Additional 1: ${escala.get('adicional_1'):.2f}")
        print()


def demo_smata_parser():
    """Demonstrate the SMATA ACA specialized parser."""
    print("=" * 70)
    print("DEMO 2: SMATA ACA Specialized Parser")
    print("=" * 70)

    parser = SmatAcaParser()

    # Full SMATA text example
    text = """
CONVENIO COLECTIVO DE TRABAJO 454/2006
ANEXO SMATA - ACA
ESCALAS SALARIALES

Auxilio Mecánico
Oficial superior 1.395,35 1.789,00
Oficial de Primera 1.297,62 1.656,00

SUBSIDIOS:
Subsidios por Casamiento 280,00
Subsidios por Nacimiento 280,00
Subsidios por Fallecimiento hijos 560,00

ADICIONAL POR ANTIGÜEDAD SOBRE SALARIO DE CONVENIO DE $ 1.100
- 1 año: 1%
- 2 años: 2%
...
- 30 años: 30%

Art. 56 - CONDICIONES ESPECIALES PARA PROVINCIAS NEUQUÉN, RÍO NEGRO, 
CHUBUT, SANTA CRUZ Y TIERRA DEL FUEGO: TREINTA POR CIENTO SOBRE LA REMUNERACIÓN
"""

    if parser.can_handle(text):
        print("\n✓ SMATA ACA CCT detected!")
        result = parser.parse(text)

        print(f"✓ Scales found: {len(result.get('escalas_salariales', []))}")
        print(f"✓ Subsidios found: {len(result.get('subsidios', []))}")
        print(f"✓ Antiguedad rule: {'Yes' if result.get('antiguedad') else 'No'}")
        print(f"✓ Zone rule: {'Yes' if result.get('zona_desfavorable') else 'No'}")

        # Show subsidios
        print("\n  Subsidios detected:")
        for subsidio in result.get("subsidios", [])[:3]:
            print(f"    - {subsidio.get('nombre')}: ${subsidio.get('valor')}")

        # Show antiguedad
        if result.get("antiguedad"):
            antig = result["antiguedad"]
            print(f"\n  Antiguedad rule:")
            print(f"    Base: ${antig.get('base_monto')}")
            print(f"    Type: {antig.get('tipo')}")
            escala = antig.get("escala", [])
            print(f"    Escala: {len(escala)} years (1% per year)")

        # Show zona
        if result.get("zona_desfavorable"):
            zona = result["zona_desfavorable"]
            print(f"\n  Zone desfavorable:")
            print(f"    Percentage: {zona.get('porcentaje')}%")
            print(f"    Provinces: {', '.join(zona.get('provincias', []))}")
    else:
        print("✗ SMATA ACA not detected")


def demo_specialized_parsers():
    """Demonstrate the specialized parsers registry."""
    print("\n" + "=" * 70)
    print("DEMO 3: Specialized Parsers Registry")
    print("=" * 70)

    text = """
CCT 454/2006 SMATA - ACA
ANEXO SMATA - ACA

Oficial superior 1.395,35 1.789,00
Administrativo A 1.100,00
Subsidios por Casamiento 280,00

ADICIONAL POR ANTIGÜEDAD: base $ 1.100, 1% por año hasta 30%

Art. 56 - Zona patagónica 30%
"""

    result = run_specialized_parsers(text)

    print(f"\n✓ Total scales extracted: {len(result.get('escalas_salariales', []))}")
    print(f"✓ Total categories: {len(result.get('categorias', []))}")
    print(f"✓ Total subsidios: {len(result.get('subsidios', []))}")
    print(f"✓ Reglas found: {list(result.get('reglas_liquidacion', {}).keys())}")

    # Show what was extracted
    print(f"\n  Categories:")
    for cat in result.get("categorias", [])[:2]:
        print(f"    - {cat.get('nombre')}")

    print(f"\n  Scales:")
    for esc in result.get("escalas_salariales", [])[:2]:
        print(f"    - {esc.get('categoria')}: ${esc.get('basico_mensual')}")


if __name__ == "__main__":
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  DEMONSTRACIÓN: Parser de CCT/Escalas Salariales (2 Capas)  ".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "=" * 68 + "╝")

    try:
        demo_generic_parser()
        demo_smata_parser()
        demo_specialized_parsers()

        print("\n" + "=" * 70)
        print("✓ All demos completed successfully!")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
