const MONEY_FORMATTER = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "ARS",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toNumber(value, fallback = 0) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(String(value ?? "").replace(/\./g, "").replace(/,/g, "."));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatMoney(value) {
  return MONEY_FORMATTER.format(toNumber(value));
}

function getCategoriaValue(categoria) {
  return toNumber(
    categoria?.basico_mensual
      ?? categoria?.sueldo_mensual
      ?? categoria?.valor
      ?? categoria?.unit_price
      ?? 0
  );
}

function getCategoriaUnitLabel(categoria) {
  const tipoValor = String(categoria?.tipo_valor || "").toLowerCase();
  if (tipoValor.includes("hora") || categoria?.valor_hora) return "por hora";
  return "mensual";
}

function getAntiguedadRule(payload) {
  return payload?.reglas_liquidacion?.antiguedad || null;
}

function getZonaRule(payload) {
  return payload?.reglas_liquidacion?.zona_desfavorable || null;
}

function getDefaultCategory(categorias) {
  return categorias.find((cat) => getCategoriaValue(cat) > 0) || categorias[0] || null;
}

function renderAdicionalControls(adicionales) {
  const enabled = adicionales
    .filter((item) => item && item.valor !== null && item.valor !== undefined)
    .slice(0, 18);

  if (!enabled.length) {
    return `<p class="dynamic-calculator-muted">No hay adicionales automáticos detectados. Podés cargar un adicional manual.</p>`;
  }

  return enabled.map((item, index) => {
    const tipo = item.tipo || "monto_fijo";
    const valor = toNumber(item.valor);
    const tipoLabel = tipo.includes("porcentaje") ? `${valor}%` : formatMoney(valor);
    return `
      <label class="dynamic-calculator-check">
        <input type="checkbox" data-extra-index="${index}">
        <span>
          <strong>${escapeHtml(item.nombre || `Adicional ${index + 1}`)}</strong>
          <small>${escapeHtml(tipoLabel)} ${item.condicion ? ` · ${escapeHtml(item.condicion)}` : ""}</small>
        </span>
      </label>
    `;
  }).join("");
}

function calculatePayroll(payload, form) {
  const categorias = Array.isArray(payload?.categorias) ? payload.categorias : [];
  const adicionales = Array.isArray(payload?.adicionales) ? payload.adicionales : [];
  const categoria = categorias.find((cat) => cat.id === form.categoryId) || getDefaultCategory(categorias);
  const basico = getCategoriaValue(categoria);
  const antiguedadRule = getAntiguedadRule(payload);
  const zonaRule = getZonaRule(payload);

  const anios = Math.max(0, toNumber(form.antiguedadAnios));
  const cantidad = Math.max(0, toNumber(form.cantidad, 1));
  const basicoCalculado = basico * cantidad;
  const antiguedadPct = toNumber(antiguedadRule?.porcentaje_por_anio, 1);
  const antiguedadBase = toNumber(antiguedadRule?.base_monto, basicoCalculado || 0);
  const antiguedad = form.aplicarAntiguedad ? antiguedadBase * (antiguedadPct / 100) * anios : 0;

  const zonaPct = toNumber(zonaRule?.porcentaje, 0);
  const zona = form.aplicarZona ? (basicoCalculado + antiguedad) * (zonaPct / 100) : 0;

  const extras = form.extraIndexes.map((index) => {
    const item = adicionales[index];
    if (!item) return null;
    const valor = toNumber(item.valor);
    const tipo = item.tipo || "monto_fijo";
    let monto = valor;
    if (tipo.includes("porcentaje")) {
      monto = (basicoCalculado + antiguedad) * (valor / 100);
    }
    return { nombre: item.nombre || `Adicional ${index + 1}`, monto, tipo, valor };
  }).filter(Boolean);

  const manual = Math.max(0, toNumber(form.adicionalManual));
  const descuentos = Math.max(0, toNumber(form.descuentos));
  const bruto = basicoCalculado + antiguedad + zona + manual + extras.reduce((sum, item) => sum + item.monto, 0);
  const netoEstimado = bruto - descuentos;

  return { categoria, basico, cantidad, basicoCalculado, antiguedad, zona, extras, manual, descuentos, bruto, netoEstimado };
}

function readForm(container) {
  return {
    categoryId: container.querySelector("[data-calc-category]")?.value || "",
    cantidad: container.querySelector("[data-calc-cantidad]")?.value || 1,
    antiguedadAnios: container.querySelector("[data-calc-antiguedad]")?.value || 0,
    aplicarAntiguedad: Boolean(container.querySelector("[data-calc-apply-antiguedad]")?.checked),
    aplicarZona: Boolean(container.querySelector("[data-calc-apply-zona]")?.checked),
    adicionalManual: container.querySelector("[data-calc-manual]")?.value || 0,
    descuentos: container.querySelector("[data-calc-descuentos]")?.value || 0,
    extraIndexes: [...container.querySelectorAll("[data-extra-index]:checked")].map((input) => Number(input.dataset.extraIndex)).filter(Number.isFinite),
  };
}

function renderResult(container, result) {
  const resultNode = container.querySelector("[data-calc-result]");
  if (!resultNode) return;

  const unitLabel = getCategoriaUnitLabel(result.categoria);

  resultNode.innerHTML = `
    <div class="dynamic-calculator-summary-grid">
      <article class="summary-card">
        <span>Categoría</span>
        <strong>${escapeHtml(result.categoria?.nombre || "Sin categoría")}</strong>
        <small>${escapeHtml(result.categoria?.grupo || result.categoria?.descripcion || unitLabel)}</small>
      </article>
      <article class="summary-card">
        <span>Valor base</span>
        <strong>${formatMoney(result.basico)}</strong>
        <small>${escapeHtml(unitLabel)}</small>
      </article>
      <article class="summary-card highlight-card">
        <span>Total bruto estimado</span>
        <strong>${formatMoney(result.bruto)}</strong>
        <small>Antes de descuentos finales</small>
      </article>
      <article class="summary-card highlight-card">
        <span>Neto estimado</span>
        <strong>${formatMoney(result.netoEstimado)}</strong>
        <small>Bruto menos descuentos manuales</small>
      </article>
    </div>

    <div class="dynamic-calculator-breakdown-grid">
      <article class="breakdown-card">
        <h3>Composición</h3>
        <div class="rows">
          <div class="row"><span>Base x cantidad</span><strong>${formatMoney(result.basicoCalculado)}</strong></div>
          <div class="row"><span>Antigüedad</span><strong>${formatMoney(result.antiguedad)}</strong></div>
          <div class="row"><span>Zona / región</span><strong>${formatMoney(result.zona)}</strong></div>
          <div class="row"><span>Adicional manual</span><strong>${formatMoney(result.manual)}</strong></div>
          <div class="row"><span>Descuentos</span><strong>-${formatMoney(result.descuentos)}</strong></div>
        </div>
      </article>

      <article class="breakdown-card">
        <h3>Adicionales aplicados</h3>
        ${result.extras.length ? `
          <div class="rows">
            ${result.extras.map((item) => `<div class="row"><span>${escapeHtml(item.nombre)}</span><strong>${formatMoney(item.monto)}</strong></div>`).join("")}
          </div>
        ` : `<p class="dynamic-calculator-muted">No se seleccionaron adicionales automáticos.</p>`}
      </article>
    </div>
  `;
}

function injectCalculatorStyles() {
  if (document.querySelector("#dynamic-calculator-styles")) return;
  const style = document.createElement("style");
  style.id = "dynamic-calculator-styles";
  style.textContent = `
    :root {
      --bg: #f7f2e8;
      --bg-soft: rgba(255, 255, 255, 0.76);
      --surface: rgba(255, 251, 245, 0.9);
      --surface-strong: #fffdf8;
      --text: #1b2321;
      --muted: #53615d;
      --line: rgba(27, 35, 33, 0.08);
      --line-strong: rgba(27, 35, 33, 0.16);
      --accent: #d06224;
      --accent-deep: #a54516;
      --green: #1f6a52;
      --warning-soft: rgba(182, 91, 25, 0.14);
      --green-soft: rgba(31, 106, 82, 0.14);
      --shadow: 0 24px 60px rgba(54, 40, 22, 0.12);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
      --radius-sm: 12px;
      --font-display: "Rockwell", "Georgia", serif;
      --font-body: "Aptos", "Bahnschrift", "Trebuchet MS", sans-serif;
    }

    body {
      background:
        radial-gradient(circle at top left, rgba(214, 131, 73, 0.22), transparent 28%),
        radial-gradient(circle at right 18%, rgba(64, 132, 107, 0.18), transparent 24%),
        linear-gradient(180deg, #f7f0e2 0%, #f4efe7 36%, #eef4f0 100%);
      color: var(--text);
      font-family: var(--font-body);
    }

    .dynamic-calculator-page-shell {
      width: min(1440px, calc(100% - 32px));
      margin: 24px auto 40px;
    }

    .dynamic-calculator {
      display: grid;
      gap: 24px;
    }

    .dynamic-calculator-hero,
    .dynamic-calculator-panel,
    .summary-card,
    .breakdown-card {
      backdrop-filter: blur(14px);
      background: var(--bg-soft);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }

    .dynamic-calculator-hero {
      display: grid;
      grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.9fr);
      gap: 24px;
      padding: 28px;
      border-radius: var(--radius-xl);
    }

    .eyebrow,
    .section-label {
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 0.72rem;
      color: var(--accent-deep);
      font-weight: 800;
    }

    .dynamic-calculator-hero h1,
    .dynamic-calculator-panel h2,
    .breakdown-card h3 {
      margin: 0;
      font-family: var(--font-display);
      letter-spacing: -0.02em;
    }

    .dynamic-calculator-hero h1 {
      font-size: clamp(2.2rem, 4vw, 3.6rem);
      line-height: 0.98;
      max-width: 15ch;
    }

    .hero-text {
      margin: 18px 0 0;
      max-width: 68ch;
      line-height: 1.6;
      color: var(--muted);
      font-size: 1.02rem;
    }

    .hero-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 20px;
    }

    .hero-pills span {
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.92rem;
    }

    .hero-panel {
      padding: 22px;
      border-radius: var(--radius-lg);
      background:
        linear-gradient(160deg, rgba(208, 98, 36, 0.14), transparent 40%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(255, 255, 255, 0.52));
      border: 1px solid var(--line);
    }

    .hero-metrics {
      display: grid;
      gap: 14px;
      margin: 0;
    }

    .hero-metrics div { display: grid; gap: 4px; }
    .hero-metrics dt { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); }
    .hero-metrics dd { margin: 0; font-size: 1rem; font-weight: 800; }

    .dynamic-calculator-workspace {
      display: grid;
      grid-template-columns: minmax(360px, 460px) minmax(0, 1fr);
      gap: 24px;
    }

    .dynamic-calculator-panel {
      padding: 24px;
      border-radius: var(--radius-xl);
    }

    .panel-heading {
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 20px;
    }

    .dynamic-calculator-panel h2 { font-size: 1.6rem; }

    .dynamic-calculator-grid,
    .dynamic-calculator-checks,
    .dynamic-calculator-summary-grid,
    .dynamic-calculator-breakdown-grid {
      display: grid;
      gap: 14px;
    }

    .dynamic-calculator-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .dynamic-calculator-field {
      display: grid;
      gap: 8px;
    }

    .dynamic-calculator-field span,
    .dynamic-calculator-field label {
      font-weight: 800;
      font-size: 0.95rem;
    }

    .dynamic-calculator-field input,
    .dynamic-calculator-field select {
      width: 100%;
      padding: 13px 14px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--line);
      background: var(--surface-strong);
      color: var(--text);
      font: inherit;
    }

    .dynamic-calculator-field input:focus,
    .dynamic-calculator-field select:focus {
      outline: none;
      border-color: rgba(208, 98, 36, 0.45);
      box-shadow: 0 0 0 4px rgba(208, 98, 36, 0.14);
    }

    .dynamic-calculator-checks {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 18px;
    }

    .dynamic-calculator-check {
      position: relative;
      display: grid;
      gap: 6px;
      padding: 16px 16px 16px 48px;
      border-radius: var(--radius-md);
      background: var(--surface);
      border: 1px solid var(--line);
      cursor: pointer;
    }

    .dynamic-calculator-check input {
      position: absolute;
      inset: 18px auto auto 16px;
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
    }

    .dynamic-calculator-check span { display: grid; gap: 4px; }
    .dynamic-calculator-check strong { font-size: 0.95rem; }
    .dynamic-calculator-check small,
    .dynamic-calculator-muted { color: var(--muted); line-height: 1.55; }

    .adicionales-box {
      margin-top: 18px;
      border-radius: var(--radius-md);
      border: 1px solid var(--line);
      background: var(--surface);
      padding: 16px;
    }

    .adicionales-box h4 { margin: 0 0 10px; font-family: var(--font-display); }

    .dynamic-calculator-summary-grid {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }

    .summary-card,
    .breakdown-card {
      padding: 18px;
      border-radius: var(--radius-lg);
      background: var(--surface);
    }

    .summary-card {
      display: grid;
      gap: 8px;
    }

    .summary-card span {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .summary-card strong {
      font-family: var(--font-display);
      font-size: clamp(1.25rem, 2vw, 1.65rem);
      letter-spacing: -0.03em;
    }

    .summary-card small { color: var(--muted); }

    .highlight-card {
      background:
        linear-gradient(160deg, rgba(31, 106, 82, 0.18), transparent 50%),
        var(--surface-strong);
    }

    .dynamic-calculator-breakdown-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 18px;
    }

    .breakdown-card h3 {
      font-size: 1.2rem;
      margin-bottom: 14px;
    }

    .rows { display: grid; gap: 10px; }

    .row {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding: 10px 0;
      border-top: 1px solid var(--line);
    }

    .row:first-child { border-top: 0; padding-top: 0; }
    .row span { color: var(--muted); }
    .row strong { text-align: right; white-space: nowrap; }

    @media (max-width: 1100px) {
      .dynamic-calculator-hero,
      .dynamic-calculator-workspace {
        grid-template-columns: 1fr;
      }
      .dynamic-calculator-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 760px) {
      .dynamic-calculator-page-shell { width: min(100% - 20px, 1440px); margin-top: 14px; }
      .dynamic-calculator-hero,
      .dynamic-calculator-panel { padding: 18px; border-radius: 22px; }
      .dynamic-calculator-grid,
      .dynamic-calculator-checks,
      .dynamic-calculator-summary-grid,
      .dynamic-calculator-breakdown-grid { grid-template-columns: 1fr; }
    }
  `;
  document.head.append(style);
}

function renderCalculator(container, payload) {
  injectCalculatorStyles();
  const categorias = Array.isArray(payload?.categorias) ? payload.categorias : [];
  const adicionales = Array.isArray(payload?.adicionales) ? payload.adicionales : [];
  const convenio = payload?.convenio || {};
  const antiguedadRule = getAntiguedadRule(payload);
  const zonaRule = getZonaRule(payload);
  const defaultCategory = getDefaultCategory(categorias);
  const vigencia = payload?.vigencia || convenio?.vigencia_detectada || "Vigencia a revisar";
  const source = payload?.archivo_fuente || "Documento importado";

  container.innerHTML = `
    <section class="dynamic-calculator-page-shell">
      <div class="dynamic-calculator" data-dynamic-calculator>
        <header class="dynamic-calculator-hero">
          <div>
            <p class="eyebrow">Calculadora laboral automática</p>
            <h1>${escapeHtml(convenio.nombre || "Calculadora CCT")}</h1>
            <p class="hero-text">Calculadora generada desde el CCT y la escala salarial importada. Revisá los conceptos detectados antes de usarla en liquidaciones reales.</p>
            <div class="hero-pills">
              <span>${escapeHtml(vigencia)}</span>
              <span>${categorias.length} categorías</span>
              <span>${adicionales.length} adicionales</span>
            </div>
          </div>
          <aside class="hero-panel">
            <p class="section-label">Resumen técnico</p>
            <dl class="hero-metrics">
              <div><dt>Fuente</dt><dd>${escapeHtml(source)}</dd></div>
              <div><dt>Actividad</dt><dd>${escapeHtml(convenio.actividad || convenio.ambito || "No detectada")}</dd></div>
              <div><dt>Confianza</dt><dd>${escapeHtml(String(payload?.nivel_confianza ?? "pendiente"))}</dd></div>
            </dl>
          </aside>
        </header>

        <div class="dynamic-calculator-workspace">
          <section class="dynamic-calculator-panel">
            <div class="panel-heading">
              <div>
                <p class="section-label">Datos de cálculo</p>
                <h2>Parámetros</h2>
              </div>
            </div>

            <div class="dynamic-calculator-grid">
              <label class="dynamic-calculator-field">
                <span>Categoría</span>
                <select data-calc-category>
                  ${categorias.map((cat) => `<option value="${escapeHtml(cat.id)}" ${cat.id === defaultCategory?.id ? "selected" : ""}>${escapeHtml(cat.nombre)}${cat.grupo ? ` · ${escapeHtml(cat.grupo)}` : ""} · ${formatMoney(getCategoriaValue(cat))}</option>`).join("")}
                </select>
              </label>
              <label class="dynamic-calculator-field">
                <span>Cantidad</span>
                <input type="number" min="0" step="0.01" value="1" data-calc-cantidad>
              </label>
              <label class="dynamic-calculator-field">
                <span>Años de antigüedad</span>
                <input type="number" min="0" step="1" value="0" data-calc-antiguedad>
              </label>
              <label class="dynamic-calculator-field">
                <span>Adicional manual ($)</span>
                <input type="number" min="0" step="0.01" value="0" data-calc-manual>
              </label>
              <label class="dynamic-calculator-field">
                <span>Descuentos ($)</span>
                <input type="number" min="0" step="0.01" value="0" data-calc-descuentos>
              </label>
            </div>

            <div class="dynamic-calculator-checks">
              <label class="dynamic-calculator-check">
                <input type="checkbox" data-calc-apply-antiguedad ${antiguedadRule ? "checked" : ""}>
                <span><strong>Aplicar antigüedad</strong><small>${escapeHtml(antiguedadRule ? `${antiguedadRule.porcentaje_por_anio || 1}% por año` : "Sin regla detectada")}</small></span>
              </label>
              <label class="dynamic-calculator-check">
                <input type="checkbox" data-calc-apply-zona>
                <span><strong>Aplicar zona / región</strong><small>${escapeHtml(zonaRule ? `${zonaRule.porcentaje || 0}% según convenio` : "Sin zona detectada")}</small></span>
              </label>
            </div>

            <div class="adicionales-box">
              <h4>Adicionales y subsidios detectados</h4>
              <div class="dynamic-calculator-checks">${renderAdicionalControls(adicionales)}</div>
            </div>
          </section>

          <section class="dynamic-calculator-panel">
            <div class="panel-heading">
              <div>
                <p class="section-label">Resultado</p>
                <h2>Liquidación estimada</h2>
              </div>
            </div>
            <div data-calc-result></div>
          </section>
        </div>
      </div>
    </section>
  `;

  const calculator = container.querySelector("[data-dynamic-calculator]");
  const update = () => renderResult(calculator, calculatePayroll(payload, readForm(calculator)));
  calculator.querySelectorAll("input, select").forEach((input) => input.addEventListener("input", update));
  calculator.querySelectorAll("input, select").forEach((input) => input.addEventListener("change", update));
  update();
}

export { renderCalculator, calculatePayroll };
