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
    matriz = payload.get("matriz_tecnica") or []

    title = convenio.get("nombre") or convenio.get("cct_numero") or payload.get("archivo_fuente") or "Calculadora CCT"
    cct = convenio.get("cct_numero") or "CCT generado"
    activity = convenio.get("actividad") or "Calculadora generada automaticamente desde PDF."
    safe_payload = json.dumps(payload, ensure_ascii=False).replace("</script", "<\\/script")

    category_options = "\n".join(
        f'<option value="{idx}">{text(item.get("nombre"))}</option>' for idx, item in enumerate(categorias)
    ) or '<option value="">Sin categorias detectadas</option>'

    scale_cards = "\n".join(
        f"""
        <article class="scale-card">
          <header>
            <div><h3>{text(item.get('nombre'))}</h3><p>{text(item.get('descripcion') or item.get('tipo'))}</p></div>
            <span class="pill pill-info">{text(item.get('tipo') or 'categoria')}</span>
          </header>
          <table class="scale-table"><tbody>
            <tr><th>Sueldo mensual</th><td>{money(item.get('sueldo_mensual'))}</td></tr>
            <tr><th>Valor hora</th><td>{money(item.get('valor_hora'))}</td></tr>
            <tr><th>Fuente</th><td>{text(item.get('fuente_textual'))}</td></tr>
          </tbody></table>
        </article>
        """
        for item in categorias
    ) or '<article class="audit-empty"><strong>Sin categorias detectadas.</strong><p>Revisar el JSON tecnico o regenerar con IA disponible.</p></article>'

    additional_rows = "\n".join(
        f"<tr><td>{text(item.get('nombre'))}</td><td>{text(item.get('tipo'))}</td><td>{text(item.get('valor'))}</td><td>{text(item.get('base'))}</td><td>{text(item.get('condicion'))}</td></tr>"
        for item in adicionales
    ) or '<tr><td colspan="5">No se detectaron adicionales.</td></tr>'

    concept_rows = "\n".join(
        f'<tr><td>{text(item.get("codigo"))}</td><td>{text(item.get("nombre"))}<small>{text(item.get("formula"))}</small></td><td><span class="pill pill-rem">{text(item.get("tipo"))}</span></td><td>{text(item.get("lsd"))}</td></tr>'
        for item in conceptos
    ) or '<tr><td colspan="4">No se generaron conceptos tecnicos.</td></tr>'

    matrix_rows = "\n".join(
        f"<tr><td>{text(item.get('paso'))}</td><td>{text(item.get('concepto'))}</td><td>{text(item.get('formula'))}</td><td>{text(item.get('incidencia'))}</td></tr>"
        for item in matriz
    ) or '<tr><td colspan="4">No hay matriz tecnica disponible.</td></tr>'

    pending_items = "\n".join(f"<article><strong>Pendiente</strong><p>{text(item)}</p></article>" for item in pendientes) or "<article><strong>Sin pendientes.</strong><p>No se informaron pendientes.</p></article>"
    alert_items = "\n".join(f"<article class='audit-finding is-warning'><strong>Alerta</strong><p>{text(item)}</p></article>" for item in alertas) or "<article class='audit-empty'><strong>Sin alertas.</strong><p>No se informaron alertas.</p></article>"

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{text(title)}</title>
  <style>
    :root {{ --bg:#f7f2e8; --bg-soft:rgba(255,255,255,.76); --surface:rgba(255,251,245,.9); --surface-strong:#fffdf8; --text:#1b2321; --muted:#53615d; --line:rgba(27,35,33,.08); --line-strong:rgba(27,35,33,.16); --accent:#d06224; --accent-deep:#a54516; --green:#1f6a52; --warning-soft:rgba(182,91,25,.14); --error-soft:rgba(158,47,47,.12); --green-soft:rgba(31,106,82,.14); --shadow:0 24px 60px rgba(54,40,22,.12); --radius-xl:28px; --radius-lg:22px; --radius-md:16px; --radius-sm:12px; --font-display:"Rockwell","Georgia",serif; --font-body:"Aptos","Bahnschrift","Trebuchet MS",sans-serif; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; font-family:var(--font-body); color:var(--text); background:radial-gradient(circle at top left,rgba(214,131,73,.22),transparent 28%),radial-gradient(circle at right 18%,rgba(64,132,107,.18),transparent 24%),linear-gradient(180deg,#f7f0e2 0%,#f4efe7 36%,#eef4f0 100%); }}
    button,input,select,summary {{ font:inherit; }}
    .page-shell {{ width:min(1440px,calc(100% - 32px)); margin:24px auto 40px; }}
    .hero,.panel {{ backdrop-filter:blur(14px); background:var(--bg-soft); border:1px solid var(--line); box-shadow:var(--shadow); }}
    .hero {{ display:grid; grid-template-columns:minmax(0,1.7fr) minmax(280px,.9fr); gap:24px; padding:28px; border-radius:var(--radius-xl); }}
    .eyebrow,.section-label {{ margin:0 0 8px; text-transform:uppercase; letter-spacing:.18em; font-size:.72rem; color:var(--accent-deep); font-weight:700; }}
    h1,h2,h3 {{ margin:0; font-family:var(--font-display); letter-spacing:-.02em; }}
    .hero h1 {{ font-size:clamp(2.2rem,4vw,3.6rem); line-height:.98; max-width:14ch; }}
    .hero-text,p {{ color:var(--muted); line-height:1.6; }}
    .hero-pills,.app-actions,.quick-nav,.result-tabs,.wizard-actions-right {{ display:flex; flex-wrap:wrap; gap:10px; }}
    .hero-pills span,.app-pill,.pill {{ display:inline-flex; align-items:center; padding:9px 12px; border-radius:999px; border:1px solid var(--line); background:rgba(255,255,255,.82); color:var(--muted); font-size:.84rem; font-weight:700; }}
    .app-bar {{ display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:20px; padding:16px 20px; border-radius:var(--radius-lg); border:1px solid var(--line); background:rgba(255,255,255,.74); box-shadow:0 16px 36px rgba(51,39,24,.08); backdrop-filter:blur(14px); }}
    .app-brand {{ display:grid; gap:4px; }} .app-brand strong {{ font-size:1.08rem; }} .app-brand small {{ color:var(--muted); }}
    .brand-kicker {{ display:inline-flex; width:fit-content; padding:6px 10px; border-radius:999px; background:rgba(208,98,36,.12); color:var(--accent-deep); font-size:.74rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .hero-panel,.summary-card,.indicator-card,.scale-card,.audit-status-card,.audit-finding,.audit-empty,.step-note {{ border:1px solid var(--line); border-radius:var(--radius-lg); background:rgba(255,255,255,.76); }}
    .hero-panel {{ padding:22px; background:linear-gradient(160deg,rgba(208,98,36,.14),transparent 40%),linear-gradient(180deg,rgba(255,255,255,.82),rgba(255,255,255,.52)); }}
    .hero-metrics,.guide-list,.wizard-stack,.scale-deck {{ display:grid; gap:14px; }} .hero-metrics dd {{ margin:0; font-weight:700; }} .hero-metrics dt {{ color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.12em; }}
    .wizard-shell {{ display:grid; gap:18px; margin-top:20px; }} .wizard-progress-card,.panel {{ padding:24px; border-radius:var(--radius-xl); border:1px solid var(--line); background:rgba(255,255,255,.78); box-shadow:var(--shadow); }}
    .wizard-stepper {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; }}
    .wizard-step-button,.nav-chip,.primary-button,.ghost-button,.result-tab {{ border:1px solid var(--line); cursor:pointer; }}
    .wizard-step-button {{ display:grid; gap:8px; align-content:start; padding:16px; text-align:left; border-radius:var(--radius-md); background:rgba(255,255,255,.8); color:var(--text); }}
    .wizard-step-button strong {{ display:inline-flex; align-items:center; justify-content:center; width:36px; height:36px; border-radius:50%; background:rgba(31,106,82,.12); color:var(--green); }}
    .wizard-step-button.is-active {{ border-color:rgba(208,98,36,.34); background:rgba(208,98,36,.12); }}
    .wizard-progress-track {{ width:100%; height:12px; border-radius:999px; background:rgba(27,35,33,.08); overflow:hidden; }} .wizard-progress-fill {{ display:block; height:100%; width:20%; border-radius:inherit; background:linear-gradient(135deg,var(--accent),#e18a41); transition:.22s ease; }}
    .section-pane {{ display:none; margin-top:24px; }} .section-pane.is-active {{ display:block; }}
    .step-intro,.panel-heading,.scale-card header,.wizard-actions {{ display:flex; justify-content:space-between; gap:18px; align-items:start; margin-bottom:18px; }}
    .wizard-grid {{ display:grid; gap:24px; grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr); }}
    .field-grid,.toggle-grid,.summary-grid,.indicator-grid,.matrix-stats {{ display:grid; gap:14px; }} .field-grid,.toggle-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .summary-grid,.indicator-grid,.matrix-stats {{ grid-template-columns:repeat(4,minmax(0,1fr)); }}
    .field {{ display:grid; gap:8px; }} .field span {{ font-weight:700; font-size:.95rem; }} .field input,.field select {{ width:100%; padding:13px 14px; border-radius:var(--radius-sm); border:1px solid var(--line); background:var(--surface-strong); color:var(--text); }} .field-full {{ grid-column:1/-1; }}
    .toggle-card {{ position:relative; display:grid; gap:6px; padding:16px 16px 16px 48px; border-radius:var(--radius-md); background:var(--surface); border:1px solid var(--line); cursor:pointer; }} .toggle-card input {{ position:absolute; inset:18px auto auto 16px; width:18px; height:18px; accent-color:var(--accent); }} .toggle-card small {{ color:var(--muted); }}
    .primary-button,.ghost-button {{ border-radius:999px; padding:13px 20px; font-weight:700; }} .primary-button {{ background:linear-gradient(135deg,var(--accent),#e18a41); color:#fff; border-color:transparent; }} .ghost-button {{ background:rgba(255,255,255,.74); color:var(--text); border-color:var(--line); text-decoration:none; }}
    .summary-card,.indicator-card,.mini-stat {{ padding:18px; border-radius:var(--radius-lg); background:var(--surface); border:1px solid var(--line); display:grid; gap:8px; }} .summary-card span,.indicator-card span,.mini-stat span {{ color:var(--muted); font-size:.9rem; }} .summary-card strong,.indicator-card strong {{ font-family:var(--font-display); font-size:1.65rem; }} .highlight-card {{ background:linear-gradient(160deg,rgba(31,106,82,.18),transparent 50%),var(--surface-strong); }}
    .result-tabs {{ margin:18px 0; }} .result-tab,.nav-chip {{ border-radius:999px; padding:10px 14px; background:rgba(255,255,255,.82); color:var(--muted); font-weight:700; }} .result-tab.is-active,.nav-chip.is-active {{ color:var(--green); border-color:rgba(31,106,82,.28); background:rgba(31,106,82,.12); }}
    .result-pane {{ display:none; }} .result-pane.is-active {{ display:block; }}
    .table-wrap {{ overflow-x:auto; border-radius:var(--radius-md); border:1px solid var(--line); background:rgba(255,255,255,.82); }} .tech-table,.scale-table {{ width:100%; border-collapse:collapse; font-size:.94rem; }} .tech-table th,.tech-table td,.scale-table th,.scale-table td {{ padding:12px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} .tech-table th,.scale-table th {{ background:rgba(31,106,82,.08); font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; }} .tech-table td small {{ display:block; margin-top:4px; color:var(--muted); }}
    .scale-card {{ overflow:hidden; }} .scale-card header {{ padding:18px 20px; border-bottom:1px solid var(--line); background:rgba(255,255,255,.72); margin:0; }} .scale-card p {{ margin:0; }} .scale-table td:last-child,.scale-table th:last-child {{ text-align:right; }}
    .pill-rem {{ background:rgba(31,106,82,.14); color:var(--green); }} .pill-info {{ background:rgba(84,97,93,.12); color:var(--muted); }}
    .receipt-hero {{ display:grid; gap:10px; padding:20px 22px; border-radius:var(--radius-lg); color:#fff; background:linear-gradient(145deg,rgba(16,58,51,.96),rgba(31,106,82,.94)); }} .receipt-columns {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin-top:16px; }} .receipt-column {{ padding:18px; border-radius:var(--radius-md); border:1px solid var(--line); background:rgba(255,255,255,.82); }} .receipt-row,.receipt-total {{ display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-bottom:1px solid var(--line); }} .receipt-total {{ margin-top:16px; padding:16px; border-radius:var(--radius-md); border:1px solid rgba(208,98,36,.16); background:linear-gradient(135deg,rgba(208,98,36,.14),rgba(31,106,82,.12)); }}
    .guide-list article,.audit-finding,.audit-empty,.step-note {{ padding:14px 16px; }} .guide-list p,.audit-finding p,.audit-empty p,.step-note p {{ margin:6px 0 0; color:var(--muted); line-height:1.55; }} .audit-finding.is-warning {{ border-color:rgba(208,98,36,.22); background:var(--warning-soft); }}
    .mono {{ white-space:pre-wrap; background:#101916; color:#e6f3ed; border-radius:10px; padding:12px; overflow:auto; max-height:420px; font-family:Consolas,monospace; font-size:12px; }}
    @media(max-width:1120px) {{ .hero,.wizard-grid {{ grid-template-columns:1fr; }} .wizard-stepper,.summary-grid,.indicator-grid,.matrix-stats {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media(max-width:760px) {{ .page-shell {{ width:min(100%,calc(100% - 20px)); margin:12px auto 28px; }} .hero,.panel,.wizard-progress-card {{ padding:18px; border-radius:20px; }} .app-bar,.step-intro,.panel-heading,.scale-card header,.wizard-actions {{ flex-direction:column; }} .wizard-stepper,.field-grid,.toggle-grid,.summary-grid,.indicator-grid,.matrix-stats,.receipt-columns {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="page-shell">
    <div class="app-bar">
      <div class="app-brand"><span class="brand-kicker">Meta-modelo + {text(cct)}</span><strong>{text(title)}</strong><small>HTML unico, offline y trazable generado desde convenio y escala salarial.</small></div>
      <div class="app-actions"><span class="app-pill">Remunerativos + NR</span><span class="app-pill">Auditoria + recibo</span><button id="print-button" type="button" class="ghost-button">Imprimir</button><a class="ghost-button" href="/portal-cct.html">Portal</a></div>
    </div>

    <header class="hero">
      <div><p class="eyebrow">Liquidacion profesional y trazable</p><h1>{text(title)}</h1><p class="hero-text">{text(activity)}</p><div class="hero-pills"><span>Escalas detectadas</span><span>Recibo dinamico</span><span>Modo auditoria</span><span>JSON tecnico</span></div></div>
      <aside class="hero-panel"><h2>Fuente activa</h2><p>Calculadora generada desde PDF con estructura JSON revisable.</p><dl class="hero-metrics"><div><dt>Convenio</dt><dd>{text(cct)}</dd></div><div><dt>Divisor mensual</dt><dd>{text(parametros.get('divisor_mensual') or 30)} dias</dd></div><div><dt>Horas mensuales</dt><dd>{text(parametros.get('horas_mensuales'))}</dd></div><div><dt>Estado</dt><dd>{text(payload.get('estado'))}</dd></div></dl></aside>
    </header>

    <div class="wizard-shell"><section class="wizard-progress-card"><p class="section-label">Proceso guiado enterprise</p><h2 id="wizard-progress-title">Paso 1 de 5 · Datos generales</h2><p id="wizard-progress-caption" class="wizard-progress-caption">Configura el contexto del legajo antes de revisar escalas, liquidacion y auditoria.</p><div class="wizard-progress-track"><span id="wizard-progress-fill" class="wizard-progress-fill"></span></div></section><nav class="wizard-stepper" aria-label="Pasos"><button type="button" class="wizard-step-button is-active" data-step="general"><strong>1</strong><span>Datos generales</span><small>Categoria, dias y jornada.</small></button><button type="button" class="wizard-step-button" data-step="concepts"><strong>2</strong><span>Conceptos</span><small>Adicionales y descuentos.</small></button><button type="button" class="wizard-step-button" data-step="result"><strong>3</strong><span>Resultado</span><small>Resumen y recibo.</small></button><button type="button" class="wizard-step-button" data-step="audit"><strong>4</strong><span>Auditoria</span><small>Alertas y matriz tecnica.</small></button><button type="button" class="wizard-step-button" data-step="json"><strong>5</strong><span>JSON tecnico</span><small>Datos fuente.</small></button></nav></div>

    <section id="section-general" class="section-pane is-active"><div class="step-intro"><div><p class="section-label">Paso 1</p><h2>Datos generales del legajo</h2></div><p>Elegí la categoria y los tiempos liquidados. El motor usa sueldo mensual si existe; si no, valor hora.</p></div><div class="wizard-grid"><section class="panel"><div class="field-grid"><label class="field field-full"><span>Categoria</span><select id="category-id">{category_options}</select></label><label class="field"><span>Dias trabajados</span><input id="worked-days" type="number" min="0" max="31" step="1" value="30" /></label><label class="field"><span>Horas trabajadas</span><input id="worked-hours" type="number" min="0" step="0.5" value="0" /></label><label class="field"><span>Antiguedad (%)</span><input id="seniority-rate" type="number" min="0" step="0.1" value="0" /></label><label class="field"><span>Coeficiente jornada</span><input id="jornada-coefficient" type="number" min="0.1" max="1" step="0.05" value="1" /></label></div><div class="toggle-grid"><label class="toggle-card"><input id="union-toggle" type="checkbox" checked /><span>Aplicar sindicato</span><small>Descuento configurable 2%.</small></label><label class="toggle-card"><input id="debug-toggle" type="checkbox" /><span>Modo debug</span><small>Muestra JSON y trazas.</small></label></div><div class="wizard-actions"><div class="step-note"><strong>Objetivo</strong><p>Definir la base de calculo antes de cargar conceptos.</p></div><div class="wizard-actions-right"><button type="button" class="primary-button" data-next="concepts">Continuar</button></div></div></section><section class="wizard-stack"><section class="panel"><p class="section-label">Escala activa</p><h2>Referencia detectada</h2><div class="summary-grid" style="margin-top:16px"><article class="summary-card"><span>Categorias</span><strong>{len(categorias)}</strong></article><article class="summary-card"><span>Adicionales</span><strong>{len(adicionales)}</strong></article><article class="summary-card"><span>Confianza</span><strong>{text(payload.get('nivel_confianza'))}</strong></article><article class="summary-card"><span>Horas</span><strong>{text(parametros.get('horas_mensuales'))}</strong></article></div></section></section></div></section>

    <section id="section-concepts" class="section-pane"><div class="step-intro"><div><p class="section-label">Paso 2</p><h2>Conceptos, adicionales y escalas</h2></div><p>Revisá importes detectados y cargá ajustes manuales del periodo.</p></div><div class="wizard-grid"><section class="panel"><div class="field-grid"><label class="field"><span>Adicional manual ($)</span><input id="manual-additional" type="number" min="0" step="0.01" value="0" /></label><label class="field"><span>Descuentos manuales ($)</span><input id="manual-deductions" type="number" min="0" step="0.01" value="0" /></label><label class="field"><span>Horas extra 50%</span><input id="overtime-50" type="number" min="0" step="0.5" value="0" /></label><label class="field"><span>Horas extra 100%</span><input id="overtime-100" type="number" min="0" step="0.5" value="0" /></label></div><div class="wizard-actions"><button type="button" class="ghost-button" data-prev="general">Volver</button><button type="button" class="primary-button" id="calculate-button" data-next="result">Calcular</button></div></section><section class="panel"><p class="section-label">Escalas salariales</p><h2>Categorias detectadas</h2><div class="scale-deck" style="margin-top:16px">{scale_cards}</div></section></div></section>

    <section id="section-result" class="section-pane"><div class="step-intro"><div><p class="section-label">Paso 3</p><h2>Resultado final y salida operativa</h2></div><p>Resumen, vista recibo y explicacion paso a paso.</p></div><section class="panel"><div class="result-tabs"><button type="button" class="result-tab is-active" data-tab="summary">Resumen</button><button type="button" class="result-tab" data-tab="receipt">Vista recibo</button><button type="button" class="result-tab" data-tab="calc">Como se calculo</button></div><div id="pane-summary" class="result-pane is-active"><div class="summary-grid"><article class="summary-card"><span>Bruto remunerativo</span><strong id="gross-rem">$ 0,00</strong></article><article class="summary-card"><span>Descuentos</span><strong id="deductions-total">$ 0,00</strong></article><article class="summary-card"><span>No remunerativos</span><strong id="non-rem-total">$ 0,00</strong></article><article class="summary-card highlight-card"><span>Total bolsillo</span><strong id="take-home-total">$ 0,00</strong></article></div><div class="indicator-grid" style="margin-top:14px"><article class="indicator-card"><span>Valor hora</span><strong id="hour-value">$ 0,00</strong></article><article class="indicator-card"><span>Base social</span><strong id="social-base">$ 0,00</strong></article><article class="indicator-card"><span>Base obra/sindicato</span><strong id="health-base">$ 0,00</strong></article><article class="indicator-card"><span>% descuentos</span><strong id="discount-rate">0,00%</strong></article></div></div><div id="pane-receipt" class="result-pane"><div id="receipt-view"></div></div><div id="pane-calc" class="result-pane"><div class="guide-list" id="step-by-step"></div></div><div class="wizard-actions"><button type="button" class="ghost-button" data-prev="concepts">Volver</button><button type="button" class="primary-button" data-next="audit">Continuar a auditoria</button></div></section></section>

    <section id="section-audit" class="section-pane"><div class="step-intro"><div><p class="section-label">Paso 4</p><h2>Auditoria preventiva laboral</h2></div><p>Alertas, pendientes, adicionales y matriz tecnica separada del resultado final.</p></div><div class="wizard-grid"><section class="panel"><div class="matrix-stats"><article class="mini-stat"><span>Estado</span><strong>{text(payload.get('estado'))}</strong></article><article class="mini-stat"><span>Pendientes</span><strong>{len(pendientes)}</strong></article><article class="mini-stat"><span>Alertas</span><strong>{len(alertas)}</strong></article><article class="mini-stat"><span>Conceptos</span><strong>{len(conceptos)}</strong></article></div><div class="guide-list" style="margin-top:18px">{alert_items}{pending_items}</div></section><section class="panel"><p class="section-label">Adicionales</p><h2>Detectados</h2><div class="table-wrap"><table class="tech-table"><thead><tr><th>Nombre</th><th>Tipo</th><th>Valor</th><th>Base</th><th>Condicion</th></tr></thead><tbody>{additional_rows}</tbody></table></div></section></div><section class="panel" style="margin-top:24px"><p class="section-label">Matriz tecnica</p><h2>Reglas y conceptos</h2><div class="table-wrap"><table class="tech-table"><thead><tr><th>Codigo</th><th>Concepto</th><th>Tipo</th><th>LSD</th></tr></thead><tbody>{concept_rows}</tbody></table></div><div class="table-wrap" style="margin-top:18px"><table class="tech-table"><thead><tr><th>Paso</th><th>Concepto</th><th>Formula</th><th>Incidencia</th></tr></thead><tbody>{matrix_rows}</tbody></table></div><div class="wizard-actions"><button type="button" class="ghost-button" data-prev="result">Volver</button><button type="button" class="primary-button" data-next="json">Ver JSON</button></div></section></section>

    <section id="section-json" class="section-pane"><div class="step-intro"><div><p class="section-label">Paso 5</p><h2>JSON tecnico</h2></div><p>Datos fuente usados para construir esta calculadora.</p></div><section class="panel"><div class="mono" id="jsonbox"></div><div class="wizard-actions"><button type="button" class="ghost-button" data-prev="audit">Volver</button><button type="button" class="primary-button" onclick="window.print()">Imprimir</button></div></section></section>
  </div>

  <script>
    const DATA = {safe_payload};
    const steps = ['general','concepts','result','audit','json'];
    const money = (n) => new Intl.NumberFormat('es-AR', {{ style:'currency', currency:'ARS' }}).format(Number(n || 0));
    let last = {{ gross:0, deductions:0, net:0, base:0, hour:0 }};
    function showStep(id) {{
      document.querySelectorAll('.section-pane').forEach(el => el.classList.toggle('is-active', el.id === 'section-' + id));
      document.querySelectorAll('.wizard-step-button').forEach(btn => btn.classList.toggle('is-active', btn.dataset.step === id));
      const index = steps.indexOf(id); document.querySelector('#wizard-progress-fill').style.width = ((index + 1) / steps.length * 100) + '%';
      document.querySelector('#wizard-progress-title').textContent = `Paso ${{index + 1}} de ${{steps.length}} · ${{document.querySelector(`[data-step="${{id}}"] span`).textContent}}`;
    }}
    function currentCategory() {{ const idx = Number(document.querySelector('#category-id').value || 0); return DATA.categorias?.[idx] || {{}}; }}
    function calc() {{
      const cat = currentCategory(); const dias = Number(document.querySelector('#worked-days').value || 0); const horas = Number(document.querySelector('#worked-hours').value || 0); const coef = Number(document.querySelector('#jornada-coefficient').value || 1); const antPct = Number(document.querySelector('#seniority-rate').value || 0); const add = Number(document.querySelector('#manual-additional').value || 0); const manualDed = Number(document.querySelector('#manual-deductions').value || 0); const h50 = Number(document.querySelector('#overtime-50').value || 0); const h100 = Number(document.querySelector('#overtime-100').value || 0); const divisor = Number(DATA.parametros?.divisor_mensual || 30); const mensual = Number(cat.sueldo_mensual || 0); const hour = Number(cat.valor_hora || (mensual > 0 && DATA.parametros?.horas_mensuales ? mensual / Number(DATA.parametros.horas_mensuales) : 0)); const base = mensual > 0 ? mensual * coef * dias / divisor : hour * horas * coef; const antig = base * antPct / 100; const extras = hour * h50 * 1.5 + hour * h100 * 2; const gross = base + antig + extras + add; const social = gross * 0.17; const union = document.querySelector('#union-toggle').checked ? gross * 0.02 : 0; const deductions = social + union + manualDed; const net = gross - deductions; last = {{ gross, deductions, net, base, hour }};
      document.querySelector('#gross-rem').textContent = money(gross); document.querySelector('#deductions-total').textContent = money(deductions); document.querySelector('#non-rem-total').textContent = money(0); document.querySelector('#take-home-total').textContent = money(net); document.querySelector('#hour-value').textContent = money(hour); document.querySelector('#social-base').textContent = money(gross); document.querySelector('#health-base').textContent = money(gross); document.querySelector('#discount-rate').textContent = gross ? (deductions / gross * 100).toFixed(2).replace('.', ',') + '%' : '0,00%';
      document.querySelector('#receipt-view').innerHTML = `<div class="receipt-hero"><strong>Recibo estimado</strong><span>${{DATA.convenio?.nombre || DATA.convenio?.cct_numero || 'CCT generado'}}</span></div><div class="receipt-columns"><div class="receipt-column"><h4>Haberes</h4><div class="receipt-row"><span>Basico proporcional</span><strong>${{money(base)}}</strong></div><div class="receipt-row"><span>Antiguedad</span><strong>${{money(antig)}}</strong></div><div class="receipt-row"><span>Horas extra</span><strong>${{money(extras)}}</strong></div><div class="receipt-row"><span>Adicional manual</span><strong>${{money(add)}}</strong></div></div><div class="receipt-column"><h4>Descuentos</h4><div class="receipt-row"><span>Seguridad social estimada</span><strong>${{money(social)}}</strong></div><div class="receipt-row"><span>Sindicato</span><strong>${{money(union)}}</strong></div><div class="receipt-row"><span>Manual</span><strong>${{money(manualDed)}}</strong></div></div></div><div class="receipt-total"><strong>Total bolsillo</strong><strong>${{money(net)}}</strong></div>`;
      document.querySelector('#step-by-step').innerHTML = `<article><strong>1. Basico</strong><p>${{money(base)}} calculado segun escala y proporcion de dias/horas.</p></article><article><strong>2. Antiguedad</strong><p>${{money(antig)}} segun porcentaje informado.</p></article><article><strong>3. Extras y adicionales</strong><p>${{money(extras + add)}}.</p></article><article><strong>4. Descuentos</strong><p>${{money(deductions)}}.</p></article>`;
    }}
    document.querySelectorAll('[data-step]').forEach(btn => btn.addEventListener('click', () => showStep(btn.dataset.step)));
    document.querySelectorAll('[data-next]').forEach(btn => btn.addEventListener('click', () => {{ if (btn.id === 'calculate-button') calc(); showStep(btn.dataset.next); }}));
    document.querySelectorAll('[data-prev]').forEach(btn => btn.addEventListener('click', () => showStep(btn.dataset.prev)));
    document.querySelectorAll('[data-tab]').forEach(btn => btn.addEventListener('click', () => {{ document.querySelectorAll('.result-tab').forEach(b => b.classList.toggle('is-active', b === btn)); document.querySelectorAll('.result-pane').forEach(p => p.classList.toggle('is-active', p.id === 'pane-' + btn.dataset.tab)); }}));
    document.querySelector('#print-button').addEventListener('click', () => window.print());
    document.querySelector('#jsonbox').textContent = JSON.stringify(DATA, null, 2); calc();
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
