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
    const id = `calc-extra-${index}`;
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
  const antiguedadPct = toNumber(antiguedadRule?.porcentaje_por_anio, 1);
  const antiguedadBase = toNumber(antiguedadRule?.base_monto, basico || 0);
  const antiguedad = form.aplicarAntiguedad ? antiguedadBase * (antiguedadPct / 100) * anios : 0;

  const zonaPct = toNumber(zonaRule?.porcentaje, 0);
  const zona = form.aplicarZona ? (basico + antiguedad) * (zonaPct / 100) : 0;

  const extras = form.extraIndexes.map((index) => {
    const item = adicionales[index];
    if (!item) return null;
    const valor = toNumber(item.valor);
    const tipo = item.tipo || "monto_fijo";
    let monto = valor;
    if (tipo.includes("porcentaje")) {
      monto = (basico + antiguedad) * (valor / 100);
    }
    return { nombre: item.nombre || `Adicional ${index + 1}`, monto, tipo, valor };
  }).filter(Boolean);

  const manual = Math.max(0, toNumber(form.adicionalManual));
  const descuentos = Math.max(0, toNumber(form.descuentos));
  const bruto = basico + antiguedad + zona + manual + extras.reduce((sum, item) => sum + item.monto, 0);
  const netoEstimado = bruto - descuentos;

  return { categoria, basico, antiguedad, zona, extras, manual, descuentos, bruto, netoEstimado };
}

function readForm(container) {
  return {
    categoryId: container.querySelector("[data-calc-category]")?.value || "",
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

  resultNode.innerHTML = `
    <div class="dynamic-calculator-result-grid">
      <div><span>Categoría</span><strong>${escapeHtml(result.categoria?.nombre || "Sin categoría")}</strong></div>
      <div><span>Básico</span><strong>${formatMoney(result.basico)}</strong></div>
      <div><span>Antigüedad</span><strong>${formatMoney(result.antiguedad)}</strong></div>
      <div><span>Zona</span><strong>${formatMoney(result.zona)}</strong></div>
      <div><span>Adicional manual</span><strong>${formatMoney(result.manual)}</strong></div>
      <div><span>Descuentos</span><strong>-${formatMoney(result.descuentos)}</strong></div>
      <div class="dynamic-calculator-total"><span>Total bruto estimado</span><strong>${formatMoney(result.bruto)}</strong></div>
      <div class="dynamic-calculator-total"><span>Neto estimado</span><strong>${formatMoney(result.netoEstimado)}</strong></div>
    </div>
    ${result.extras.length ? `
      <div class="dynamic-calculator-breakdown">
        <h5>Adicionales aplicados</h5>
        <ul>${result.extras.map((item) => `<li>${escapeHtml(item.nombre)}: ${formatMoney(item.monto)}</li>`).join("")}</ul>
      </div>
    ` : ""}
  `;
}

function injectCalculatorStyles() {
  if (document.querySelector("#dynamic-calculator-styles")) return;
  const style = document.createElement("style");
  style.id = "dynamic-calculator-styles";
  style.textContent = `
    .dynamic-calculator { margin-top: 18px; border: 1px solid rgba(31,106,82,.18); border-radius: 24px; overflow: hidden; background: rgba(255,255,255,.86); }
    .dynamic-calculator-header { padding: 18px; background: linear-gradient(135deg, rgba(31,106,82,.13), rgba(208,98,36,.10)); }
    .dynamic-calculator-header h3 { margin: 0 0 6px; color: #1b2321; }
    .dynamic-calculator-header p { margin: 0; color: #53615d; }
    .dynamic-calculator-body { padding: 18px; display: grid; gap: 16px; }
    .dynamic-calculator-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .dynamic-calculator-field { display: grid; gap: 6px; color: #53615d; font-weight: 800; }
    .dynamic-calculator-field input, .dynamic-calculator-field select { border: 1px solid rgba(31,106,82,.18); border-radius: 14px; padding: 11px 12px; background: white; color: #1b2321; font: inherit; }
    .dynamic-calculator-checks { display: grid; gap: 8px; }
    .dynamic-calculator-check { display: flex; gap: 10px; align-items: flex-start; padding: 11px; border: 1px solid rgba(31,106,82,.12); border-radius: 15px; background: rgba(31,106,82,.045); }
    .dynamic-calculator-check span { display: grid; gap: 3px; }
    .dynamic-calculator-check small, .dynamic-calculator-muted { color: #53615d; }
    .dynamic-calculator-result { padding: 15px; border-radius: 18px; background: #1b2321; color: #f7efe2; }
    .dynamic-calculator-result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .dynamic-calculator-result-grid div { padding: 10px; border-radius: 13px; background: rgba(255,255,255,.08); display: grid; gap: 4px; }
    .dynamic-calculator-result-grid span { color: rgba(247,239,226,.74); font-size: .84rem; }
    .dynamic-calculator-result-grid strong { font-size: 1rem; }
    .dynamic-calculator-total strong { font-size: 1.22rem; color: #fff; }
    .dynamic-calculator-breakdown h5 { margin: 14px 0 6px; }
    .dynamic-calculator-breakdown ul { margin: 0; padding-left: 20px; }
    @media (max-width: 760px) { .dynamic-calculator-grid, .dynamic-calculator-result-grid { grid-template-columns: 1fr; } }
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

  container.innerHTML = `
    <section class="dynamic-calculator" data-dynamic-calculator>
      <div class="dynamic-calculator-header">
        <h3>Calculadora ${escapeHtml(convenio.nombre || "CCT")}</h3>
        <p>${escapeHtml(convenio.actividad || convenio.ambito || "Calculadora generada desde el CCT importado")}</p>
      </div>
      <div class="dynamic-calculator-body">
        <div class="dynamic-calculator-grid">
          <label class="dynamic-calculator-field">
            Categoría
            <select data-calc-category>
              ${categorias.map((cat) => `<option value="${escapeHtml(cat.id)}" ${cat.id === defaultCategory?.id ? "selected" : ""}>${escapeHtml(cat.nombre)} · ${formatMoney(getCategoriaValue(cat))}</option>`).join("")}
            </select>
          </label>
          <label class="dynamic-calculator-field">
            Años de antigüedad
            <input type="number" min="0" step="1" value="0" data-calc-antiguedad>
          </label>
          <label class="dynamic-calculator-field">
            Adicional manual ($)
            <input type="number" min="0" step="0.01" value="0" data-calc-manual>
          </label>
          <label class="dynamic-calculator-field">
            Descuentos ($)
            <input type="number" min="0" step="0.01" value="0" data-calc-descuentos>
          </label>
        </div>

        <div class="dynamic-calculator-checks">
          <label class="dynamic-calculator-check">
            <input type="checkbox" data-calc-apply-antiguedad ${antiguedadRule ? "checked" : ""}>
            <span><strong>Aplicar antigüedad</strong><small>${escapeHtml(antiguedadRule ? `${antiguedadRule.porcentaje_por_anio || 1}% por año sobre base ${formatMoney(antiguedadRule.base_monto || 0)}` : "Sin regla detectada")}</small></span>
          </label>
          <label class="dynamic-calculator-check">
            <input type="checkbox" data-calc-apply-zona>
            <span><strong>Aplicar zona / región</strong><small>${escapeHtml(zonaRule ? `${zonaRule.porcentaje || 0}% según convenio` : "Sin zona detectada")}</small></span>
          </label>
        </div>

        <div>
          <h4>Adicionales y subsidios detectados</h4>
          <div class="dynamic-calculator-checks">${renderAdicionalControls(adicionales)}</div>
        </div>

        <div class="dynamic-calculator-result" data-calc-result></div>
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
