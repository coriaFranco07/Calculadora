from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


def slugify(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "calculadora-cct"))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"\.pdf\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "calculadora-cct"


def money(value: Any) -> str:
    if value in (None, "", "null"):
        return "-"
    try:
        number = float(str(value).replace(",", "."))
    except ValueError:
        return html.escape(str(value))
    return "$ " + f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def text(value: Any, fallback: str = "-") -> str:
    raw = str(value if value not in (None, "") else fallback)
    return html.escape(raw)


def pick_base_name(payload: dict[str, Any]) -> str:
    convenio = payload.get("convenio") or {}
    cct_number = convenio.get("cct_numero")
    activity = convenio.get("actividad") or convenio.get("nombre")
    if cct_number and activity:
        return f"cct-{cct_number}-{activity}"
    if cct_number:
        return f"cct-{cct_number}"
    if convenio.get("nombre"):
        return str(convenio["nombre"])
    return str(payload.get("archivo_fuente") or "calculadora-cct")


def build_generated_calculator_html(payload: dict[str, Any]) -> str:
    convenio = payload.get("convenio") or {}
    categorias = payload.get("categorias") or []
    adicionales = payload.get("adicionales") or []
    parametros = payload.get("parametros") or {}
    conceptos = payload.get("conceptos") or []
    pendientes = payload.get("pendientes_revision") or []
    alertas = payload.get("alertas") or []

    title = convenio.get("nombre") or convenio.get("cct_numero") or payload.get("archivo_fuente") or "Calculadora CCT"
    safe_payload = json.dumps(payload, ensure_ascii=False).replace("</script", "<\\/script")

    category_options = "\n".join(
        f'<option value="{idx}">{text(item.get("nombre"))}</option>' for idx, item in enumerate(categorias)
    ) or '<option value="">Sin categorías detectadas</option>'

    category_rows = "\n".join(
        f"""
        <tr>
          <td>{text(item.get('nombre'))}</td>
          <td>{text(item.get('tipo'))}</td>
          <td>{money(item.get('sueldo_mensual'))}</td>
          <td>{money(item.get('valor_hora'))}</td>
          <td>{text(item.get('fuente_textual'))}</td>
        </tr>
        """
        for item in categorias
    ) or '<tr><td colspan="5">No se detectaron categorías.</td></tr>'

    additional_rows = "\n".join(
        f"""
        <tr>
          <td>{text(item.get('nombre'))}</td>
          <td>{text(item.get('tipo'))}</td>
          <td>{text(item.get('valor'))}</td>
          <td>{text(item.get('base'))}</td>
          <td>{text(item.get('condicion'))}</td>
        </tr>
        """
        for item in adicionales
    ) or '<tr><td colspan="5">No se detectaron adicionales.</td></tr>'

    concept_rows = "\n".join(
        f"""
        <tr>
          <td>{text(item.get('codigo'))}</td>
          <td>{text(item.get('nombre'))}</td>
          <td>{text(item.get('tipo'))}</td>
          <td>{text(item.get('formula'))}</td>
        </tr>
        """
        for item in conceptos
    ) or '<tr><td colspan="4">No se generaron conceptos técnicos.</td></tr>'

    pending_items = "\n".join(f"<li>{text(item)}</li>" for item in pendientes) or "<li>Sin pendientes informados.</li>"
    alert_items = "\n".join(f"<li>{text(item)}</li>" for item in alertas) or "<li>Sin alertas informadas.</li>"

    return f"""<!DOCTYPE html>
<html lang="es-AR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{text(title)}</title>
  <style>
    :root {{ --bg:#f4f6f3; --surface:#fff; --ink:#17221c; --muted:#66736c; --line:#d9e1db; --brand:#155a43; --ok:#23704e; --warn:#936500; --shadow:0 18px 45px rgba(23,34,28,.12); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Aptos,"Segoe UI",sans-serif; color:var(--ink); background:linear-gradient(135deg,rgba(21,90,67,.1),transparent 35%),var(--bg); }}
    .shell {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:28px 0 48px; }}
    header {{ display:flex; justify-content:space-between; align-items:center; gap:18px; margin-bottom:18px; }}
    h1 {{ margin:0; font-size:clamp(28px,4vw,44px); line-height:1; }}
    h2 {{ margin:0 0 12px; font-size:20px; }}
    p {{ color:var(--muted); line-height:1.55; }}
    .button {{ display:inline-flex; min-height:42px; align-items:center; justify-content:center; border:1px solid var(--line); border-radius:10px; padding:0 14px; background:#fff; color:var(--ink); text-decoration:none; font-weight:850; cursor:pointer; }}
    .button.primary {{ background:var(--brand); color:#fff; border-color:var(--brand); }}
    .grid {{ display:grid; grid-template-columns:1.1fr .9fr; gap:16px; }}
    .card {{ background:rgba(255,255,255,.92); border:1px solid var(--line); border-radius:12px; padding:18px; box-shadow:var(--shadow); margin-bottom:16px; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }}
    .stat {{ border:1px solid var(--line); background:#eef3ee; border-radius:10px; padding:12px; }}
    .stat small {{ display:block; color:var(--muted); font-weight:800; text-transform:uppercase; font-size:11px; }}
    .stat strong {{ display:block; margin-top:4px; font-size:18px; }}
    label {{ display:grid; gap:6px; margin-top:12px; }}
    label span {{ color:var(--muted); font-size:12px; font-weight:850; text-transform:uppercase; letter-spacing:.04em; }}
    input, select {{ width:100%; min-height:42px; border:1px solid var(--line); border-radius:10px; padding:0 12px; font:inherit; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ border-bottom:1px solid var(--line); text-align:left; padding:9px; vertical-align:top; }}
    th {{ background:#eef3ee; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
    .result {{ border-radius:12px; background:linear-gradient(135deg,var(--brand),#00392f); color:#fff; padding:18px; margin-top:14px; }}
    .result p,.result small {{ color:rgba(255,255,255,.8); }}
    .result strong {{ font-size:26px; display:block; }}
    .badge {{ display:inline-flex; border-radius:999px; padding:5px 10px; background:#e6f3ed; color:var(--ok); font-size:12px; font-weight:900; }}
    .mono {{ white-space:pre-wrap; background:#101916; color:#e6f3ed; border-radius:10px; padding:12px; overflow:auto; max-height:360px; font-family:Consolas,monospace; font-size:12px; }}
    @media(max-width:860px) {{ header,.grid,.stats {{ display:block; }} .stat {{ margin-bottom:10px; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <a class="button" href="/portal-cct.html">← Volver al portal</a>
        <h1>{text(title)}</h1>
        <p>{text(convenio.get('actividad') or 'Calculadora generada automáticamente desde PDF.')}</p>
      </div>
      <button class="button primary" onclick="window.print()">Imprimir</button>
    </header>
    <section class="stats">
      <div class="stat"><small>CCT / Norma</small><strong>{text(convenio.get('cct_numero') or convenio.get('nombre'))}</strong></div>
      <div class="stat"><small>Vigencia</small><strong>{text(convenio.get('vigencia_detectada'))}</strong></div>
      <div class="stat"><small>Horas mensuales</small><strong>{text(parametros.get('horas_mensuales'))}</strong></div>
      <div class="stat"><small>Confianza</small><strong>{text(payload.get('nivel_confianza'))}</strong></div>
    </section>
    <div class="grid">
      <section>
        <div class="card">
          <h2>Liquidación rápida</h2>
          <label><span>Categoría</span><select id="categoria">{category_options}</select></label>
          <label><span>Días trabajados</span><input id="dias" type="number" value="30" min="0" max="31" step="1" /></label>
          <label><span>Horas trabajadas</span><input id="horas" type="number" value="0" min="0" step="0.5" /></label>
          <label><span>Antigüedad (%)</span><input id="antiguedad" type="number" value="0" min="0" step="0.1" /></label>
          <label><span>Adicional manual ($)</span><input id="adicional" type="number" value="0" min="0" step="0.01" /></label>
          <label><span>Descuentos ($)</span><input id="descuentos" type="number" value="0" min="0" step="0.01" /></label>
          <button class="button primary" onclick="calcular()" style="margin-top:14px">Calcular</button>
          <div class="result" id="resultado"><small>Neto estimado</small><strong>$ 0,00</strong><p>Completá los datos y presioná Calcular.</p></div>
        </div>
        <div class="card"><h2>Categorías y escalas</h2><table><thead><tr><th>Categoría</th><th>Tipo</th><th>Mensual</th><th>Hora</th><th>Fuente</th></tr></thead><tbody>{category_rows}</tbody></table></div>
      </section>
      <aside>
        <div class="card"><h2>Convenio</h2><p><strong>Ámbito:</strong> {text(convenio.get('ambito'))}</p><p><strong>Archivo:</strong> {text(payload.get('archivo_fuente'))}</p><p><strong>Estado:</strong> <span class="badge">{text(payload.get('estado'))}</span></p></div>
        <div class="card"><h2>Adicionales detectados</h2><table><thead><tr><th>Nombre</th><th>Tipo</th><th>Valor</th><th>Base</th><th>Condición</th></tr></thead><tbody>{additional_rows}</tbody></table></div>
      </aside>
    </div>
    <section class="card"><h2>Conceptos técnicos</h2><table><thead><tr><th>Código</th><th>Concepto</th><th>Tipo</th><th>Fórmula</th></tr></thead><tbody>{concept_rows}</tbody></table></section>
    <section class="grid"><div class="card"><h2>Pendientes de revisión</h2><ul>{pending_items}</ul></div><div class="card"><h2>Alertas</h2><ul>{alert_items}</ul></div></section>
    <section class="card"><h2>JSON técnico</h2><div class="mono" id="jsonbox"></div></section>
  </div>
  <script>
    const DATA = {safe_payload};
    const money = (n) => new Intl.NumberFormat('es-AR', {{ style:'currency', currency:'ARS' }}).format(Number(n || 0));
    function currentCategory() {{ const index = Number(document.querySelector('#categoria').value || 0); return DATA.categorias?.[index] || {{}}; }}
    function calcular() {{
      const cat = currentCategory(); const dias = Number(document.querySelector('#dias').value || 0); const horas = Number(document.querySelector('#horas').value || 0); const antPct = Number(document.querySelector('#antiguedad').value || 0); const adicional = Number(document.querySelector('#adicional').value || 0); const descuentos = Number(document.querySelector('#descuentos').value || 0); const divisor = Number(DATA.parametros?.divisor_mensual || 30); const mensual = Number(cat.sueldo_mensual || 0); const hora = Number(cat.valor_hora || 0); const base = mensual > 0 ? mensual * dias / divisor : hora * horas; const antiguedad = base * antPct / 100; const bruto = base + antiguedad + adicional; const neto = bruto - descuentos;
      document.querySelector('#resultado').innerHTML = `<small>Neto estimado</small><strong>${{money(neto)}}</strong><p>Bruto: ${{money(bruto)}} · Base: ${{money(base)}} · Antigüedad: ${{money(antiguedad)}} · Descuentos: ${{money(descuentos)}}</p>`;
    }}
    document.querySelector('#jsonbox').textContent = JSON.stringify(DATA, null, 2);
  </script>
</body>
</html>"""


def write_generated_calculator(payload: dict[str, Any], templates_dir: Path) -> dict[str, str]:
    slug = slugify(pick_base_name(payload))
    generated_dir = templates_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{slug}.html"
    output_path = generated_dir / file_name
    output_path.write_text(build_generated_calculator_html(payload), encoding="utf-8")
    return {"html_file": str(output_path), "html_url": f"/generated/{file_name}"}
