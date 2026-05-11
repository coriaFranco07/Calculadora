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
    title = convenio.get("nombre") or convenio.get("cct_numero") or payload.get("archivo_fuente") or "Calculadora CCT"
    cct = convenio.get("cct_numero") or "CCT generado"
    activity = convenio.get("actividad") or "Calculadora generada automaticamente desde PDF"
    safe_payload = json.dumps(payload, ensure_ascii=False).replace("</script", "<\\/script")

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>e-Sueldos · {text(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--azul:#00796B;--azul-dk:#005B4C;--azul-xdk:#00392F;--azul-lt:#E0F2F1;--ok:#388E3C;--ok-bg:#E8F5E9;--warn:#F4511E;--warn-bg:#FFEDE6;--err:#D32F2F;--bg:#F9FAFC;--surface:#FFFFFF;--border:#E3E8EF;--text:#23313F;--text-2:#5F6B7C;--text-3:#8896A7;--radius:12px;--shadow:0 2px 5px rgba(0,0,0,.05),0 4px 15px rgba(0,0,0,.06);--shadow-md:0 6px 20px rgba(0,0,0,.1);--font:"Plus Jakarta Sans",sans-serif;--mono:"JetBrains Mono",monospace;--max-w:960px}}
*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:var(--font);background:var(--bg);color:var(--text);font-size:14px;min-height:100vh}}.hdr{{background:linear-gradient(135deg,var(--azul-xdk),var(--azul));height:60px;display:flex;align-items:center;padding:0 28px;gap:20px;position:sticky;top:0;z-index:100;box-shadow:0 2px 12px rgba(0,0,0,.2)}}.hdr-logo{{display:flex;align-items:center;text-decoration:none;color:#fff;font-weight:800;font-size:20px}}.hdr-divider{{width:1px;height:28px;background:rgba(255,255,255,.25);margin:0 4px}}.hdr-title{{color:#fff;font-size:14px;font-weight:700;opacity:.9;white-space:nowrap}}.hdr-badge{{margin-left:6px;background:rgba(255,255,255,.18);color:#fff;font-size:10px;font-weight:700;padding:3px 10px;border-radius:20px;white-space:nowrap}}.hdr-spacer{{flex:1}}.hdr-actions{{display:flex;align-items:center;gap:6px}}.hbtn{{height:34px;border-radius:7px;background:rgba(255,255,255,.12);border:none;color:#fff;font-size:13px;font-weight:600;cursor:pointer;padding:0 14px;display:flex;align-items:center;gap:6px;font-family:var(--font);transition:.15s;white-space:nowrap;text-decoration:none}}.hbtn:hover{{background:rgba(255,255,255,.22)}}.page{{max-width:var(--max-w);margin:0 auto;padding:28px 16px 48px}}.pg-head{{margin-bottom:22px}}.pg-title{{font-size:22px;font-weight:800;color:var(--text);letter-spacing:-.4px;display:flex;align-items:center;gap:10px}}.pg-sub{{font-size:13px;color:var(--text-3);margin-top:5px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}.dot{{width:4px;height:4px;border-radius:50%;background:var(--text-3)}}.main-nav{{display:flex;gap:4px;margin-bottom:20px;background:var(--surface);padding:5px;border-radius:var(--radius);width:fit-content;border:1px solid var(--border);box-shadow:var(--shadow);flex-wrap:wrap}}.mn-tab{{padding:7px 20px;border-radius:7px;font-size:13px;font-weight:700;cursor:pointer;color:var(--text-3);transition:.15s;font-family:var(--font);border:none;background:transparent}}.mn-tab.active{{background:var(--azul);color:#fff}}.mn-tab:hover:not(.active){{background:var(--bg);color:var(--text)}}.main-section{{display:none}}.main-section.active{{display:block}}.stepper{{display:flex;align-items:center;background:var(--surface);border-radius:var(--radius);padding:14px 20px;box-shadow:var(--shadow);margin-bottom:20px;border:1px solid var(--border);overflow-x:auto;gap:0}}.step{{display:flex;align-items:center;gap:8px}}.step-line{{flex:1;height:2px;background:var(--border);min-width:12px;transition:.3s}}.step-num{{width:30px;height:30px;border-radius:50%;background:var(--bg);color:var(--text-3);font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;border:2px solid var(--border);transition:.3s}}.step.active .step-num{{background:var(--azul);color:#fff;border-color:var(--azul);box-shadow:0 0 0 3px rgba(0,121,107,.18)}}.step.done .step-num{{background:var(--azul-dk);color:#fff;border-color:var(--azul-dk)}}.step-line.done{{background:#26A69A}}.step-lbl{{font-size:11px;font-weight:600;color:var(--text-3);white-space:nowrap}}.step.active .step-lbl{{color:var(--azul);font-weight:700}}.card{{background:var(--surface);border-radius:var(--radius);padding:22px 24px;box-shadow:var(--shadow);margin-bottom:16px;border:1px solid var(--border)}}.card-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;padding-bottom:14px;border-bottom:1.5px solid var(--border);gap:12px}}.card-title{{font-size:15px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:9px}}.c-ic{{width:28px;height:28px;border-radius:7px;background:var(--azul-lt);display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}}.fg{{display:grid;gap:14px;grid-template-columns:1fr 1fr;margin-bottom:4px}}.field{{display:flex;flex-direction:column;gap:5px}}.field label{{font-size:11px;font-weight:700;color:var(--text-2);text-transform:uppercase;letter-spacing:.5px}}.field input,.field select{{border:1.5px solid var(--border);border-radius:7px;padding:9px 12px;font-size:13px;font-family:var(--font);color:var(--text);background:var(--surface);transition:.2s;width:100%}}.field input:focus,.field select:focus{{outline:none;border-color:var(--azul);box-shadow:0 0 0 3px rgba(0,121,107,.1)}}.hint{{font-size:11px;color:var(--text-3)}}.badge{{display:inline-flex;align-items:center;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700}}.b-blue{{background:var(--azul-lt);color:var(--azul)}}.b-green{{background:var(--ok-bg);color:var(--ok)}}.callout{{display:flex;gap:10px;padding:11px 15px;border-radius:8px;font-size:12px;margin-bottom:14px;line-height:1.6}}.callout.info{{background:#E1F5FE;border-left:3px solid #0288D1;color:#0288D1}}.callout.warn{{background:var(--warn-bg);border-left:3px solid var(--warn);color:var(--warn)}}.btn{{padding:9px 20px;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:7px;font-family:var(--font);transition:.15s;white-space:nowrap;text-decoration:none}}.btn-primary{{background:var(--azul);color:#fff}}.btn-primary:hover{{background:var(--azul-dk)}}.btn-secondary{{background:var(--surface);color:var(--text);border:1.5px solid var(--border)}}.btn-success{{background:var(--ok);color:#fff}}.btn-ghost{{background:transparent;border:none;color:var(--text-2);padding:7px 12px;border-radius:7px;font-family:var(--font);font-size:13px;font-weight:700;cursor:pointer}}.btn-ghost:hover{{background:var(--bg)}}.nav-row{{display:flex;justify-content:space-between;align-items:center;margin-top:8px;gap:12px;flex-wrap:wrap}}.paso{{display:none}}.paso.active{{display:block}}.stat-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}}.sc{{background:var(--surface);border-radius:var(--radius);padding:15px 16px;box-shadow:var(--shadow);border:1px solid var(--border)}}.sc .sl{{font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px}}.sc .sv{{font-size:18px;font-weight:800;font-family:var(--mono);letter-spacing:-.4px}}.sc .ss{{font-size:11px;color:var(--text-3);margin-top:3px}}.res-tabs{{display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap}}.rt{{padding:7px 16px;border:1.5px solid var(--border);background:var(--surface);border-radius:20px;font-size:12px;font-weight:700;cursor:pointer;color:var(--text-2);transition:.15s;font-family:var(--font)}}.rt.active{{background:var(--azul);color:#fff;border-color:var(--azul)}}.rec-hdr-box{{background:linear-gradient(135deg,var(--azul-xdk),var(--azul));color:#fff;padding:18px 22px;border-radius:var(--radius);margin-bottom:16px}}.rec-emp{{font-size:18px;font-weight:800;letter-spacing:-.3px}}.rec-meta{{font-size:12px;opacity:.8;margin-top:5px;display:flex;flex-wrap:wrap;gap:14px}}.rec-cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:14px}}.rec-block h4{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;padding-bottom:8px;border-bottom:1.5px solid var(--border);margin-bottom:8px;color:var(--text-3)}}.rec-row{{display:flex;justify-content:space-between;align-items:baseline;padding:4px 0;border-bottom:1px solid #F5F7FA}}.rc{{color:var(--text-2);flex:1;padding-right:8px;line-height:1.4}}.rm{{font-family:var(--mono);font-size:13px;font-weight:700;min-width:110px;text-align:right}}.rm.pos{{color:var(--ok)}}.rm.neg{{color:var(--err)}}.tot-card{{background:linear-gradient(135deg,var(--azul-dk),var(--azul-xdk));border-radius:var(--radius);padding:18px 22px;color:#fff}}.tot-row{{display:flex;justify-content:space-between;padding:5px 0;font-size:13px}}.tot-row.main{{font-size:20px;font-weight:800;border-top:1.5px solid rgba(255,255,255,.25);margin-top:10px;padding-top:12px;letter-spacing:-.3px}}.tv{{font-family:var(--mono)}}.dt{{width:100%;border-collapse:collapse;font-size:13px}}.dt th{{background:var(--bg);color:var(--text-2);padding:8px 11px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;white-space:nowrap;border-bottom:1.5px solid var(--border)}}.dt td{{padding:8px 11px;border-bottom:1px solid var(--border);vertical-align:middle}}.dt .num{{text-align:right;font-family:var(--mono);font-weight:600}}.escala-box{{overflow-x:auto;border:1px solid var(--border);border-radius:8px}}.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.footer{{text-align:center;font-size:11px;color:var(--text-3);padding:20px 16px;border-top:1px solid var(--border);margin-top:8px}}.mono{{white-space:pre-wrap;background:#101916;color:#e6f3ed;border-radius:8px;padding:12px;overflow:auto;max-height:420px;font-family:var(--mono);font-size:12px}}.tc{{position:fixed;top:72px;right:18px;z-index:999;display:flex;flex-direction:column;gap:8px;pointer-events:none}}.toast{{background:var(--surface);border-radius:10px;padding:11px 15px;box-shadow:var(--shadow-md);display:flex;align-items:center;gap:10px;font-size:13px;font-weight:600;min-width:260px;pointer-events:all;border:1px solid var(--border);border-left:4px solid var(--ok);animation:tIn .25s ease}}@keyframes tIn{{from{{transform:translateX(110%);opacity:0}}to{{transform:translateX(0);opacity:1}}}}@media print{{.hdr .hdr-actions,.nav-row,.main-nav,.stepper,.res-tabs{{display:none!important}}.page{{padding:0}}.card{{box-shadow:none}}}}@media(max-width:700px){{.stat-grid{{grid-template-columns:1fr 1fr!important}}.fg{{grid-template-columns:1fr!important}}.rec-cols,.two-col{{grid-template-columns:1fr!important}}.hdr{{padding:0 12px}}.hdr-title{{font-size:12px}}.hdr-badge{{display:none}}}}
</style>
</head>
<body>
<div class="tc" id="tc"></div>
<header class="hdr"><a class="hdr-logo" href="/portal-cct.html">e-Sueldos</a><div class="hdr-divider"></div><span class="hdr-title">Liquidador CCT</span><span class="hdr-badge">{text(cct)}</span><div class="hdr-spacer"></div><div class="hdr-actions"><button class="hbtn" onclick="window.print()">🖨 Imprimir</button><a class="hbtn" href="/portal-cct.html">Portal</a></div></header>
<div class="page">
  <div class="pg-head"><div class="pg-title">🧮 {text(title)}</div><div class="pg-sub"><span>{text(cct)}</span><span class="dot"></span><span>{text(activity)}</span><span class="dot"></span><span id="sourceState">JSON generado</span></div></div>
  <div class="main-nav"><button class="mn-tab active" onclick="swMain('calc',this)">🧮 Calculadora</button><button class="mn-tab" onclick="swMain('guia',this)">📋 Guía / Escalas</button><button class="mn-tab" onclick="swMain('json',this)">JSON</button></div>

  <div id="sec-calc" class="main-section active">
    <div class="stepper" id="stepper"></div>
    <div class="paso active" id="paso1"><div class="card"><div class="card-hdr"><div class="card-title"><div class="c-ic">👤</div><span>Datos del trabajador</span></div><span class="badge b-blue">Paso 1 de 4</span></div><div class="fg"><div class="field"><label>Nombre y apellido</label><input type="text" id="p1n" placeholder="Apellido, Nombre"></div><div class="field"><label>CUIL</label><input type="text" id="p1c" placeholder="20-12345678-0"></div></div><div class="fg"><div class="field"><label>Categoría</label><select id="p1cat" onchange="prevCat()"></select><span class="hint" id="catHint"></span></div><div class="field"><label>Modalidad</label><select id="p1mod"><option value="mensual">Mensual</option><option value="hora">Por hora</option></select></div></div></div><div class="nav-row"><div></div><button class="btn btn-primary" onclick="ip(2)">Continuar →</button></div></div>
    <div class="paso" id="paso2"><div class="card"><div class="card-hdr"><div class="card-title"><div class="c-ic">📅</div><span>Período y jornada</span></div><span class="badge b-blue">Paso 2 de 4</span></div><div class="callout info"><span>ℹ️</span><span>La base se toma de la categoría seleccionada. Si no hay sueldo mensual, se usa valor hora.</span></div><div class="fg"><div class="field"><label>Días trabajados</label><input type="number" id="p2d" value="30" min="0" max="31" step="1"></div><div class="field"><label>Horas trabajadas</label><input type="number" id="p2h" value="0" min="0" step="0.5"></div></div><div class="fg"><div class="field"><label>Horas extra 50%</label><input type="number" id="p2h50" value="0" min="0" step="0.5"></div><div class="field"><label>Horas extra 100%</label><input type="number" id="p2h100" value="0" min="0" step="0.5"></div></div></div><div class="nav-row"><button class="btn btn-ghost" onclick="ip(1)">← Anterior</button><button class="btn btn-primary" onclick="ip(3)">Continuar →</button></div></div>
    <div class="paso" id="paso3"><div class="card"><div class="card-hdr"><div class="card-title"><div class="c-ic">➕</div><span>Adicionales y descuentos</span></div><span class="badge b-blue">Paso 3 de 4</span></div><div class="fg"><div class="field"><label>Antigüedad (%)</label><input type="number" id="p3ant" value="0" min="0" step="0.1"></div><div class="field"><label>Adicional manual ($)</label><input type="number" id="p3add" value="0" min="0" step="0.01"></div></div><div class="fg"><div class="field"><label>Descuentos manuales ($)</label><input type="number" id="p3desc" value="0" min="0" step="0.01"></div><div class="field"><label>Descuento sindicato (%)</label><input type="number" id="p3sind" value="2" min="0" step="0.1"></div></div><div class="callout warn"><span>⚠️</span><span>Validá importes y reglas contra el convenio/escala oficial antes de usar en producción.</span></div></div><div class="nav-row"><button class="btn btn-ghost" onclick="ip(2)">← Anterior</button><button class="btn btn-success" onclick="calcular()">✓ Calcular liquidación</button></div></div>
    <div class="paso" id="paso4"><div id="statWrap"></div><div class="res-tabs"><button class="rt active" onclick="swRes('recibo',this)">📄 Recibo</button><button class="rt" onclick="swRes('calc',this)">🧮 Cómo se calculó</button><button class="rt" onclick="swRes('audit',this)">🔍 Auditoría</button></div><div id="res-recibo" class="card"></div><div id="res-calc" class="card" style="display:none"></div><div id="res-audit" class="card" style="display:none"></div><div class="nav-row"><button class="btn btn-ghost" onclick="ip(3)">← Modificar</button><button class="btn btn-secondary" onclick="window.print()">🖨 Imprimir</button></div></div>
  </div>

  <div id="sec-guia" class="main-section"><div class="card"><div class="card-hdr"><div class="card-title"><div class="c-ic">📊</div><span>Escalas salariales detectadas</span></div><span class="badge b-green" id="confidenceBadge">JSON</span></div><div class="escala-box"><table class="dt"><thead><tr><th>Categoría</th><th>Tipo</th><th class="num">Sueldo mensual</th><th class="num">Valor hora</th><th>Fuente</th></tr></thead><tbody id="scaleRows"></tbody></table></div></div><div class="two-col"><div class="card"><div class="card-hdr"><div class="card-title"><div class="c-ic">➕</div><span>Adicionales</span></div></div><div class="escala-box"><table class="dt"><thead><tr><th>Nombre</th><th>Tipo</th><th>Valor</th></tr></thead><tbody id="additionalRows"></tbody></table></div></div><div class="card"><div class="card-hdr"><div class="card-title"><div class="c-ic">⚖️</div><span>Convenio</span></div></div><p class="hint" id="agreementBox"></p></div></div></div>
  <div id="sec-json" class="main-section"><div class="card"><div class="card-hdr"><div class="card-title"><div class="c-ic">&#123; &#125;</div><span>JSON técnico</span></div></div><pre class="mono" id="jsonBox"></pre></div></div>
  <footer class="footer">e-Sueldos · Calculadora generada automáticamente desde CCT y escala salarial</footer>
</div>
<script>
const DATA = {safe_payload};
let paso = 1;
const fmt = n => new Intl.NumberFormat('es-AR', {{style:'currency', currency:'ARS'}}).format(Number(n || 0));
const num = v => {{
  if (v === null || v === undefined || v === '') return 0;
  if (typeof v === 'number') return v;
  let s = String(v).replace(/\$/g,'').replace(/\s/g,'');
  if (/^\d{{1,3}}(\.\d{{3}})+(,\d+)?$/.test(s)) s = s.replace(/\./g,'').replace(',', '.');
  else s = s.replace(',', '.');
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}};
const get = id => document.getElementById(id);
function categoryAmount(cat) {{
  const monthly = num(cat.sueldo_mensual ?? cat.basico ?? cat.importe ?? cat.salario ?? cat.monto);
  const hourly = num(cat.valor_hora ?? cat.hora ?? cat.valor);
  return {{monthly, hourly}};
}}
function toast(msg) {{ const n=document.createElement('div'); n.className='toast'; n.textContent=msg; get('tc').appendChild(n); setTimeout(()=>n.remove(),2600); }}
function swMain(id, btn) {{ document.querySelectorAll('.main-section').forEach(s=>s.classList.remove('active')); get('sec-'+id).classList.add('active'); document.querySelectorAll('.mn-tab').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); }}
function swRes(id, btn) {{ ['recibo','calc','audit'].forEach(x=>get('res-'+x).style.display=x===id?'block':'none'); document.querySelectorAll('.rt').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); }}
function renderStepper() {{ const labels=['Datos','Jornada','Conceptos','Resultado']; get('stepper').innerHTML=labels.map((l,i)=>`<div class="step ${{i+1===paso?'active':i+1<paso?'done':''}}"><div class="step-num">${{i+1}}</div><div class="step-lbl">${{l}}</div></div>${{i<labels.length-1?`<div class="step-line ${{i+1<paso?'done':''}}"></div>`:''}}`).join(''); }}
function ip(n) {{ paso=n; document.querySelectorAll('.paso').forEach(p=>p.classList.remove('active')); get('paso'+n).classList.add('active'); renderStepper(); window.scrollTo({{top:0, behavior:'smooth'}}); }}
function init() {{
  const cats = DATA.categorias || [];
  get('p1cat').innerHTML = cats.length ? cats.map((c,i)=>`<option value="${{i}}">${{c.nombre || 'Categoría '+(i+1)}}</option>`).join('') : '<option value="0">Sin categorías detectadas</option>';
  get('scaleRows').innerHTML = cats.length ? cats.map(c=>{{ const a=categoryAmount(c); return `<tr><td>${{c.nombre||'-'}}</td><td>${{c.tipo||'-'}}</td><td class="num">${{a.monthly?fmt(a.monthly):'-'}}</td><td class="num">${{a.hourly?fmt(a.hourly):'-'}}</td><td>${{c.fuente_textual||'-'}}</td></tr>`; }}).join('') : '<tr><td colspan="5">No se detectaron categorías.</td></tr>';
  const adds = DATA.adicionales || [];
  get('additionalRows').innerHTML = adds.length ? adds.map(a=>`<tr><td>${{a.nombre||'-'}}</td><td>${{a.tipo||'-'}}</td><td>${{a.valor ?? '-'}}</td></tr>`).join('') : '<tr><td colspan="3">No se detectaron adicionales.</td></tr>';
  get('agreementBox').textContent = `${{DATA.convenio?.nombre || 'Convenio generado'}} · ${{DATA.convenio?.actividad || ''}} · Estado: ${{DATA.estado || '-'}}`;
  get('confidenceBadge').textContent = 'Confianza ' + (DATA.nivel_confianza ?? '-');
  get('sourceState').textContent = DATA.estado || 'JSON generado';
  get('jsonBox').textContent = JSON.stringify(DATA, null, 2);
  prevCat(); renderStepper();
}}
function prevCat() {{ const cat=(DATA.categorias||[])[Number(get('p1cat').value||0)]||{{}}; const a=categoryAmount(cat); get('catHint').textContent = a.monthly ? 'Sueldo mensual: '+fmt(a.monthly) : a.hourly ? 'Valor hora: '+fmt(a.hourly) : 'Sin importe salarial detectado'; get('p1mod').value = a.monthly ? 'mensual' : 'hora'; }}
function calcular() {{
  const cat=(DATA.categorias||[])[Number(get('p1cat').value||0)]||{{}}; const a=categoryAmount(cat);
  const dias=num(get('p2d').value), horas=num(get('p2h').value), h50=num(get('p2h50').value), h100=num(get('p2h100').value);
  const antPct=num(get('p3ant').value), add=num(get('p3add').value), manualDesc=num(get('p3desc').value), sindPct=num(get('p3sind').value);
  const divisor=num(DATA.parametros?.divisor_mensual)||30; const base = a.monthly ? a.monthly * dias / divisor : a.hourly * horas;
  const hour = a.hourly || (a.monthly && DATA.parametros?.horas_mensuales ? a.monthly / num(DATA.parametros.horas_mensuales) : 0);
  const antig = base * antPct / 100; const extras = hour*h50*1.5 + hour*h100*2; const bruto = base + antig + extras + add;
  const jubilacion = bruto * 0.11; const obra = bruto * 0.03; const ley = bruto * 0.03; const sindicato = bruto * sindPct / 100; const descuentos = jubilacion + obra + ley + sindicato + manualDesc; const neto = bruto - descuentos;
  get('statWrap').innerHTML = `<div class="stat-grid"><div class="sc"><div class="sl">Bruto</div><div class="sv">${{fmt(bruto)}}</div><div class="ss">Remunerativo estimado</div></div><div class="sc"><div class="sl">Descuentos</div><div class="sv">${{fmt(descuentos)}}</div><div class="ss">Incluye cargas configuradas</div></div><div class="sc"><div class="sl">Valor hora</div><div class="sv">${{fmt(hour)}}</div><div class="ss">Referencia</div></div><div class="sc"><div class="sl">Neto</div><div class="sv">${{fmt(neto)}}</div><div class="ss">Bolsillo</div></div></div>`;
  get('res-recibo').innerHTML = `<div class="rec-hdr-box"><div class="rec-emp">Recibo estimado</div><div class="rec-meta"><span>${{get('p1n').value || 'Trabajador'}}</span><span>${{get('p1c').value || 'CUIL no informado'}}</span><span>${{cat.nombre || 'Categoría'}}</span></div></div><div class="rec-cols"><div class="rec-block"><h4>Haberes</h4><div class="rec-row"><span class="rc">Básico proporcional</span><span class="rm pos">${{fmt(base)}}</span></div><div class="rec-row"><span class="rc">Antigüedad</span><span class="rm pos">${{fmt(antig)}}</span></div><div class="rec-row"><span class="rc">Horas extra</span><span class="rm pos">${{fmt(extras)}}</span></div><div class="rec-row"><span class="rc">Adicional manual</span><span class="rm pos">${{fmt(add)}}</span></div></div><div class="rec-block"><h4>Descuentos</h4><div class="rec-row"><span class="rc">Jubilación 11%</span><span class="rm neg">${{fmt(jubilacion)}}</span></div><div class="rec-row"><span class="rc">Obra social 3%</span><span class="rm neg">${{fmt(obra)}}</span></div><div class="rec-row"><span class="rc">Ley 19.032 3%</span><span class="rm neg">${{fmt(ley)}}</span></div><div class="rec-row"><span class="rc">Sindicato</span><span class="rm neg">${{fmt(sindicato)}}</span></div></div></div><div class="tot-card"><div class="tot-row"><span>Total haberes</span><span class="tv">${{fmt(bruto)}}</span></div><div class="tot-row"><span>Total descuentos</span><span class="tv">${{fmt(descuentos)}}</span></div><div class="tot-row main"><span>Total bolsillo</span><span class="tv">${{fmt(neto)}}</span></div></div>`;
  get('res-calc').innerHTML = `<p class="hint">Base: ${{fmt(base)}}. Antigüedad: ${{fmt(antig)}}. Extras: ${{fmt(extras)}}. Descuentos: ${{fmt(descuentos)}}.</p>`;
  const alerts = [...(DATA.alertas||[]), ...(DATA.pendientes_revision||[])];
  get('res-audit').innerHTML = alerts.length ? alerts.map(x=>`<div class="callout warn"><span>⚠️</span><span>${{x}}</span></div>`).join('') : '<div class="callout info"><span>ℹ️</span><span>Sin alertas informadas.</span></div>';
  ip(4); toast('Liquidación calculada');
}}
init();
</script>
</body>
</html>'''


def write_generated_calculator(payload: dict[str, Any], templates_dir: Path) -> dict[str, str]:
    slug = slugify(pick_base_name(payload))
    generated_dir = templates_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{slug}.html"
    output_path = generated_dir / file_name
    output_path.write_text(build_generated_calculator_html(payload), encoding="utf-8")
    return {"html_file": str(output_path), "html_url": f"/generated/{file_name}"}
