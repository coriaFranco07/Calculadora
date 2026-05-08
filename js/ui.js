import {
  calculateLiquidation,
  convention,
  getTodayString,
  modelFlow,
  numberOrZero,
  resolveAgreements,
  resolveScale,
  roundMoney,
  ruleSnapshots
} from "./calculadora.js";
import { ejecutarAuditoria } from "./auditor.js";
import { createGeminiClient } from "./gemini-client.js";
import { initPayrollChatBox } from "./chat-box.js";

const currencyFormatter = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "ARS",
  maximumFractionDigits: 2
});

const percentFormatter = new Intl.NumberFormat("es-AR", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

const dateFormatter = new Intl.DateTimeFormat("es-AR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit"
});

const monthFormatter = new Intl.DateTimeFormat("es-AR", {
  month: "short",
  year: "numeric"
});

const geminiClient = createGeminiClient("");
const STORAGE_KEY = "cct244_wizard_state_v3";
const WIZARD_STEPS = [
  {
    key: "general",
    title: "Paso 1 de 6 · Datos generales",
    caption: "Configura el contexto del legajo antes de cargar novedades, conceptos y controles preventivos."
  },
  {
    key: "times",
    title: "Paso 2 de 6 · Novedades y tiempos",
    caption: "Carga dias, horas extra, ausencias y prepara la situacion de revista del periodo."
  },
  {
    key: "concepts",
    title: "Paso 3 de 6 · Conceptos",
    caption: "Concentra adicionales, acuerdos no remunerativos y conceptos configurables del periodo."
  },
  {
    key: "audit",
    title: "Paso 4 de 6 · Auditoria preventiva",
    caption: "Pantalla exclusiva para score, blockers, conciliaciones y trazabilidad AFIP."
  },
  {
    key: "result",
    title: "Paso 5 de 6 · Resultado final",
    caption: "Visualiza recibo, neto, bruto, descuentos y bases sin mezclar auditoria ni IA."
  },
  {
    key: "gemini",
    title: "Paso 6 de 6 · Revision Gemini",
    caption: "Interpretacion opcional del resumen de auditoria ya calculado localmente."
  }
];

const EMPLOYER_REFERENCE_RATES = [
  {
    label: "SIPA empleador",
    base: "social",
    rate: 0.1077,
    note: "Base seguridad social"
  },
  {
    label: "PAMI empleador",
    base: "social",
    rate: 0.0158,
    note: "Base seguridad social"
  },
  {
    label: "Asignaciones familiares",
    base: "social",
    rate: 0.047,
    note: "Base seguridad social"
  },
  {
    label: "Fondo nacional de empleo",
    base: "social",
    rate: 0.0095,
    note: "Base seguridad social"
  },
  {
    label: "Obra social empleador",
    base: "health",
    rate: 0.06,
    note: "Base obra social"
  }
];

const appState = {
  catalogs: null,
  latestInput: null,
  latestLiquidation: null,
  latestAudit: null,
  latestAiText: "",
  aiAvailable: false,
  currentStep: "general",
  isDirty: false
};


window.getPayrollAuditContext = function () {
  return {
    liquidacion: appState.latestLiquidation,
    auditoria: appState.latestAudit,
    entrada: appState.latestInput,
    ai: appState.latestAiText
  };
};


function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatCurrency(value) {
  return currencyFormatter.format(Number.isFinite(Number(value)) ? Number(value) : 0);
}

function formatPercent(value) {
  return percentFormatter.format(Number.isFinite(Number(value)) ? Number(value) : 0);
}

function formatDate(value) {
  if (!value) return "Fecha no informada";
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? "Fecha invalida" : dateFormatter.format(date);
}

function catalogVersion(payload) {
  return payload?.version || payload?.metadata?.version || "s/d";
}

function formatDecimal(value) {
  return Number(value || 0).toFixed(2).replace(".", ",");
}

function safeLocalStorage() {
  if (typeof window === "undefined" || !window.localStorage) return null;
  return window.localStorage;
}

function readPersistedState() {
  try {
    const storage = safeLocalStorage();
    if (!storage) return null;
    const raw = storage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_error) {
    return null;
  }
}

function buildEmptyCatalogs() {
  return {
    conceptos: [],
    reglas: [],
    formulas: [],
    mapeo_afip: [],
    convenio_244_94: [],
    metadata: {
      conceptosVersion: "s/d",
      reglasVersion: "s/d",
      formulasVersion: "s/d",
      mapeoVersion: "s/d",
      convenioVersion: "s/d"
    }
  };
}

async function loadCatalogs() {
  const urls = {
    conceptos: "./data/conceptos.json",
    reglas: "./data/reglas.json",
    formulas: "./data/formulas.json",
    mapeo: "./data/mapeo_afip.json",
    convenio: "./data/convenio_244_94.json"
  };

  const responses = await Promise.all(
    Object.values(urls).map(async (url) => {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`No se pudo cargar ${url}: ${response.status}`);
      }
      return response.json();
    })
  );

  const [conceptos, reglas, formulas, mapeo, convenio244] = responses;
  return {
    conceptos: conceptos.records || [],
    reglas: reglas.records || [],
    formulas: formulas.records || [],
    mapeo_afip: mapeo.records || [],
    convenio_244_94: convenio244.records || [],
    metadata: {
      conceptosVersion: catalogVersion(conceptos),
      reglasVersion: catalogVersion(reglas),
      formulasVersion: catalogVersion(formulas),
      mapeoVersion: catalogVersion(mapeo),
      convenioVersion: catalogVersion(convenio244)
    }
  };
}

function createRefs() {
  return {
    form: document.querySelector("#calculator-form"),
    dateInput: document.querySelector("#liquidation-date"),
    typeInput: document.querySelector("#liquidation-type"),
    categorySelect: document.querySelector("#category-id"),
    agreementsContainer: document.querySelector("#agreements-container"),
    resetButton: document.querySelector("#reset-button"),
    explainButton: document.querySelector("#explain-button"),
    printButton: document.querySelector("#print-button"),
    printResultButton: document.querySelector("#print-result-button"),
    calculateAuditButton: document.querySelector("#calculate-audit-button"),
    debugBox: document.querySelector("#debug-box"),
    skillModal: document.querySelector("#skill-modal"),
    closeSkillButton: document.querySelector("#close-skill-button"),
    toastStack: document.querySelector("#toast-stack"),
    daysLabel: document.querySelector("#days-label"),
    progressTitle: document.querySelector("#wizard-progress-title"),
    progressCaption: document.querySelector("#wizard-progress-caption"),
    progressFill: document.querySelector("#wizard-progress-fill"),
    wizardStepButtons: Array.from(document.querySelectorAll("[data-wizard-step]")),
    wizardNextButtons: Array.from(document.querySelectorAll("[data-wizard-next]")),
    wizardPrevButtons: Array.from(document.querySelectorAll("[data-wizard-prev]")),
    sectionPanes: Array.from(document.querySelectorAll(".section-pane")),
    resultTabs: Array.from(document.querySelectorAll("[data-result-tab]")),
    activeScaleCaptionHero: document.querySelector("#active-scale-caption"),
    activeScaleCaptionStep: document.querySelector("#active-scale-step-caption"),
    jornadaKpi: document.querySelector("#jornada-kpi"),
    modeKpi: document.querySelector("#mode-kpi"),
    messages: document.querySelector("#messages"),
    grossRem: document.querySelector("#gross-rem"),
    deductionsTotal: document.querySelector("#deductions-total"),
    nonRemTotal: document.querySelector("#non-rem-total"),
    takeHomeTotal: document.querySelector("#take-home-total"),
    hourValue: document.querySelector("#hour-value"),
    socialBase: document.querySelector("#social-base"),
    healthBase: document.querySelector("#health-base"),
    discountRate: document.querySelector("#discount-rate"),
    remunerativeBreakdown: document.querySelector("#remunerative-breakdown"),
    deductionsBreakdown: document.querySelector("#deductions-breakdown"),
    nonRemBreakdown: document.querySelector("#non-rem-breakdown"),
    contextBreakdown: document.querySelector("#context-breakdown"),
    explanationText: document.querySelector("#explanation-text"),
    stepByStep: document.querySelector("#step-by-step"),
    debugSteps: document.querySelector("#debug-steps"),
    sourcesPanel: document.querySelector("#sources-panel"),
    receiptView: document.querySelector("#receipt-view"),
    confidenceScore: document.querySelector("#confidence-score"),
    matrixRuleList: document.querySelector("#matrix-rule-list"),
    matrixFlowBody: document.querySelector("#matrix-flow-body"),
    scaleDeck: document.querySelector("#scale-deck"),
    agreementDeck: document.querySelector("#agreement-deck"),
    autoAuditBox: document.querySelector("#auto-audit-box"),
    auditExportCard: document.querySelector("#audit-export-card"),
    auditExportStatus: document.querySelector("#audit-export-status"),
    auditExportCaption: document.querySelector("#audit-export-caption"),
    auditScore: document.querySelector("#audit-score"),
    auditScoreCaption: document.querySelector("#audit-score-caption"),
    auditNetGap: document.querySelector("#audit-net-gap"),
    auditNetGapCaption: document.querySelector("#audit-net-gap-caption"),
    auditCoveredDays: document.querySelector("#audit-covered-days"),
    auditCoveredCaption: document.querySelector("#audit-covered-caption"),
    auditFindings: document.querySelector("#audit-findings"),
    auditSources: document.querySelector("#audit-sources"),
    auditAiRun: document.querySelector("#audit-ai-run"),
    auditAiStatus: document.querySelector("#audit-ai-status"),
    auditAiOutput: document.querySelector("#audit-ai-output"),
    simContextCaption: document.querySelector("#sim-context-caption"),
    simMonthsInput: document.querySelector("#sim-months"),
    simRemPercentInput: document.querySelector("#sim-rem-percent"),
    simNrPercentInput: document.querySelector("#sim-nr-percent"),
    runSimButton: document.querySelector("#run-sim-button"),
    simResult: document.querySelector("#sim-result"),
    compareContextCaption: document.querySelector("#compare-context-caption"),
    compareCategoryLeft: document.querySelector("#compare-category-left"),
    compareCategoryRight: document.querySelector("#compare-category-right"),
    runCompareButton: document.querySelector("#run-compare-button"),
    compareResult: document.querySelector("#compare-result"),
    distributionView: document.querySelector("#distribution-view"),
    employerCostView: document.querySelector("#employer-cost-view"),
    skillStatusBadge: document.querySelector("#skill-status-badge"),
    skillStatusCaption: document.querySelector("#skill-status-caption"),
    skillSummaryText: document.querySelector("#skill-summary-text"),
    skillSummaryMetrics: document.querySelector("#skill-summary-metrics"),
    skillStepList: document.querySelector("#skill-step-list"),
    skillFormulaList: document.querySelector("#skill-formula-list"),
    skillObservationList: document.querySelector("#skill-observation-list")
  };
}

function toast(refs, message, type = "ok", title = "Actualizado") {
  if (!refs.toastStack) return;
  const node = document.createElement("article");
  node.className = `toast-card is-${type}`;
  node.innerHTML = `<strong>${escapeHtml(title)}</strong><small>${escapeHtml(message)}</small>`;
  refs.toastStack.append(node);
  window.setTimeout(() => node.remove(), 2600);
}

function stepIndex(stepKey) {
  return Math.max(0, WIZARD_STEPS.findIndex((step) => step.key === stepKey));
}

function normalizeStepKey(stepKey) {
  return WIZARD_STEPS.some((step) => step.key === stepKey) ? stepKey : "general";
}

function updateWizardProgress(refs, stepKey) {
  const safeStepKey = normalizeStepKey(stepKey);
  const currentStep = WIZARD_STEPS[stepIndex(safeStepKey)] || WIZARD_STEPS[0];
  const progress = ((stepIndex(currentStep.key) + 1) / WIZARD_STEPS.length) * 100;

  if (refs.progressTitle) refs.progressTitle.textContent = currentStep.title;
  if (refs.progressCaption) refs.progressCaption.textContent = currentStep.caption;
  if (refs.progressFill) refs.progressFill.style.width = `${progress}%`;

  refs.wizardStepButtons.forEach((button) => {
    const buttonIndex = stepIndex(button.dataset.wizardStep);
    button.classList.toggle("is-active", button.dataset.wizardStep === currentStep.key);
    button.classList.toggle("is-complete", buttonIndex < stepIndex(currentStep.key));
  });
}

function switchWizardStep(refs, stepKey, { shouldScroll = true } = {}) {
  const safeStepKey = normalizeStepKey(stepKey);
  appState.currentStep = safeStepKey;
  refs.sectionPanes.forEach((pane) => {
    pane.classList.toggle("is-active", pane.id === `section-${safeStepKey}`);
  });
  updateWizardProgress(refs, safeStepKey);
  persistWizardState(refs);
  if (shouldScroll && typeof window !== "undefined") {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function switchResultTab(refs, tabKey) {
  refs.resultTabs.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.resultTab === tabKey);
  });
  document.querySelectorAll(".result-pane").forEach((pane) => {
    pane.classList.toggle("is-active", pane.id === `result-pane-${tabKey}`);
  });
}

function renderRows(container, rows) {
  if (!container) return;
  container.innerHTML = "";

  rows.forEach((row) => {
    const article = document.createElement("article");
    article.className = "row-item";
    const mainValue = row.amount !== undefined ? formatCurrency(row.amount) : row.valueText || "Sin dato";
    article.innerHTML = `
      <div>
        <strong>${escapeHtml(row.label || "Dato")}</strong>
        ${row.note ? `<small>${escapeHtml(row.note)}</small>` : ""}
      </div>
      <span>${escapeHtml(mainValue)}</span>
    `;
    container.append(article);
  });
}

function renderSteps(container, steps) {
  if (!container) return;
  container.innerHTML = "";

  if (!steps.length) {
    container.innerHTML = '<div class="skill-empty">Sin pasos calculados.</div>';
    return;
  }

  steps.forEach((step, index) => {
    const article = document.createElement("article");
    article.className = "step-card";
    article.innerHTML = `
      <div class="step-topline">
        <span class="type-badge badge-info">Paso ${index + 1}</span>
        <strong>${escapeHtml(step.label || step.titulo || "Paso")}</strong>
      </div>
      <p>${escapeHtml(step.formula || step.explicacion || "Sin formula declarada.")}</p>
      ${step.detail ? `<small>${escapeHtml(step.detail)}</small>` : ""}
      ${step.amount !== undefined || step.resultado !== undefined ? `<strong>${escapeHtml(formatCurrency(step.amount ?? step.resultado))}</strong>` : ""}
    `;
    container.append(article);
  });
}

function renderMessages(refs, items) {
  if (!refs.messages) return;
  refs.messages.innerHTML = "";

  if (!items.length) {
    refs.messages.innerHTML = `
      <article class="audit-empty">
        <strong>Motor listo.</strong>
        <p>La liquidacion se calcula primero y luego la auditoria preventiva evalua el objeto final.</p>
      </article>
    `;
    return;
  }

  items.forEach((item) => {
    const article = document.createElement("article");
    article.className = `audit-finding is-${String(item.type || "info").toLowerCase()}`;
    article.innerHTML = `
      <strong>${escapeHtml(item.title)}</strong>
      <p>${escapeHtml(item.body)}</p>
    `;
    refs.messages.append(article);
  });
}

function renderScaleDeck(refs, activeDate) {
  if (!refs.scaleDeck) return;
  refs.scaleDeck.innerHTML = "";

  convention.salaryScales.forEach((scale) => {
    const isActive = activeDate >= scale.validFrom && (!scale.validTo || activeDate <= scale.validTo);
    const grouped = scale.categories.reduce((accumulator, category) => {
      if (!accumulator[category.sector]) accumulator[category.sector] = [];
      accumulator[category.sector].push(category);
      return accumulator;
    }, {});

    const sections = Object.entries(grouped)
      .map(
        ([sector, categories]) => `
          <details ${isActive ? "open" : ""}>
            <summary>${escapeHtml(sector)}</summary>
            <table class="scale-table">
              <thead>
                <tr>
                  <th>Categoria</th>
                  <th>Base</th>
                  <th>Importe</th>
                </tr>
              </thead>
              <tbody>
                ${categories
                  .map(
                    (category) => `
                      <tr>
                        <td>${escapeHtml(category.label)}</td>
                        <td>${category.payBasis === "hourly" ? "Valor hora" : "Mensual"}</td>
                        <td>${escapeHtml(formatCurrency(category.amount))}</td>
                      </tr>
                    `
                  )
                  .join("")}
              </tbody>
            </table>
          </details>
        `
      )
      .join("");

    const card = document.createElement("article");
    card.className = "scale-card";
    card.innerHTML = `
      <header>
        <div>
          <h3>${escapeHtml(scale.label)}</h3>
          <p>${escapeHtml(scale.sourceLabel)}</p>
        </div>
        <span class="pill ${isActive ? "pill-rem" : "pill-info"}">${isActive ? "Activa" : "Historica"}</span>
      </header>
      ${sections}
    `;
    refs.scaleDeck.append(card);
  });
}

function renderAgreementDeck(refs, activeDate) {
  if (!refs.agreementDeck) return;
  refs.agreementDeck.innerHTML = "";

  if (!convention.agreements.length) {
    refs.agreementDeck.innerHTML = '<div class="skill-empty">No hay acuerdos no remunerativos cargados.</div>';
    return;
  }

  convention.agreements.forEach((agreement) => {
    const isActive = activeDate >= agreement.validFrom && (!agreement.validTo || activeDate <= agreement.validTo);
    const entries = Object.entries(agreement.categoryAmounts)
      .map(([categoryId, amount]) => {
        const scale = resolveScale(agreement.validFrom) || convention.salaryScales[0];
        const category = scale?.categories.find((item) => item.id === categoryId);
        return `<tr><td>${escapeHtml(category?.label || categoryId)}</td><td>${escapeHtml(formatCurrency(amount))}</td></tr>`;
      })
      .join("");

    const card = document.createElement("article");
    card.className = "scale-card";
    card.innerHTML = `
      <header>
        <div>
          <h3>${escapeHtml(agreement.label)}</h3>
          <p>${escapeHtml(agreement.notes[0] || "Sin nota")}</p>
        </div>
        <span class="pill ${isActive ? "pill-nr" : "pill-info"}">${isActive ? "Disponible" : "Fuera de vigencia"}</span>
      </header>
      <details ${isActive ? "open" : ""}>
        <summary>Ver importes por categoria</summary>
        <table class="scale-table">
          <thead>
            <tr>
              <th>Categoria</th>
              <th>Importe NR</th>
            </tr>
          </thead>
          <tbody>${entries}</tbody>
        </table>
      </details>
    `;
    refs.agreementDeck.append(card);
  });
}

function renderCategoryOptions(refs) {
  const scale = resolveScale(refs.dateInput.value);
  refs.categorySelect.innerHTML = "";

  if (!scale) {
    if (refs.activeScaleCaptionHero) refs.activeScaleCaptionHero.textContent = "No hay escala activa para la fecha indicada.";
    if (refs.activeScaleCaptionStep) refs.activeScaleCaptionStep.textContent = "No hay escala activa para la fecha indicada.";
    renderToolboxContext(refs);
    return;
  }

  if (refs.activeScaleCaptionHero) refs.activeScaleCaptionHero.textContent = `${scale.label} · ${scale.sourceLabel}`;
  if (refs.activeScaleCaptionStep) refs.activeScaleCaptionStep.textContent = `${scale.label} · ${scale.sourceLabel}`;

  const grouped = scale.categories.reduce((accumulator, category) => {
    if (!accumulator[category.sector]) accumulator[category.sector] = [];
    accumulator[category.sector].push(category);
    return accumulator;
  }, {});

  Object.entries(grouped).forEach(([sector, categories]) => {
    const optgroup = document.createElement("optgroup");
    optgroup.label = sector;
    categories.forEach((category) => {
      const option = document.createElement("option");
      option.value = category.id;
      option.textContent = `${category.label} · ${category.payBasis === "hourly" ? "valor hora" : "mensual"}`;
      optgroup.append(option);
    });
    refs.categorySelect.append(optgroup);
  });

  updateContextKpis(refs);
  renderToolboxContext(refs);
}

function renderAgreementControls(refs) {
  refs.agreementsContainer.innerHTML = "";
  const agreements = resolveAgreements(refs.dateInput.value);

  if (!agreements.length) {
    refs.agreementsContainer.innerHTML = "<p>No hay acuerdos no remunerativos activos para la fecha elegida.</p>";
    return;
  }

  agreements.forEach((agreement) => {
    const card = document.createElement("article");
    card.className = "agreement-card";
    card.innerHTML = `
      <h4>${escapeHtml(agreement.label)}</h4>
      <p>${escapeHtml(agreement.notes[0] || "Sin nota")}</p>
      <div class="agreement-options">
        <label class="agreement-option"><input type="checkbox" name="agreement-${agreement.id}-enabled" ${agreement.defaults.enabled ? "checked" : ""} /><span>Activo</span></label>
        <label class="agreement-option"><input type="checkbox" name="agreement-${agreement.id}-applySeniority" ${agreement.defaults.applySeniority ? "checked" : ""} /><span>Impacta antiguedad</span></label>
        <label class="agreement-option"><input type="checkbox" name="agreement-${agreement.id}-applySocialSecurity" ${agreement.defaults.applySocialSecurity ? "checked" : ""} /><span>Impacta jubilacion / PAMI</span></label>
        <label class="agreement-option"><input type="checkbox" name="agreement-${agreement.id}-applyHealthAndUnion" ${agreement.defaults.applyHealthAndUnion ? "checked" : ""} /><span>Impacta obra social / sindicato</span></label>
        <label class="agreement-option"><input type="checkbox" name="agreement-${agreement.id}-applyZone" ${agreement.defaults.applyZone ? "checked" : ""} /><span>Impacta zona</span></label>
        <label class="agreement-option"><input type="checkbox" name="agreement-${agreement.id}-prorateByDays" ${agreement.defaults.prorateByDays ? "checked" : ""} /><span>Prorratear por dias</span></label>
      </div>
    `;
    refs.agreementsContainer.append(card);
  });
}

function updateConditionalFields(refs) {
  const map = {
    mensual: "Dias trabajados",
    vacaciones: "Dias trabajados del mes de referencia",
    final: "Dias trabajados hasta la baja"
  };
  refs.daysLabel.textContent = map[refs.typeInput.value] || "Dias trabajados";
  document.querySelectorAll(".conditional-field").forEach((field) => {
    field.classList.toggle("is-visible", field.dataset.type === refs.typeInput.value);
  });
}

function updateContextKpis(refs) {
  if (refs.jornadaKpi) {
    refs.jornadaKpi.textContent = formatDecimal(refs.form.elements.jornadaCoefficient?.value || 1);
  }
  if (refs.modeKpi) {
    const labelMap = {
      normal: "Operacion normal",
      revision: "Revision interna",
      cierre: "Cierre previo"
    };
    refs.modeKpi.textContent = labelMap[refs.form.elements.liquidationMode?.value] || "Operacion normal";
  }
}

function collectAgreementOverrides(refs, dateString) {
  return resolveAgreements(dateString).reduce((accumulator, agreement) => {
    accumulator[agreement.id] = {
      enabled: refs.form.elements[`agreement-${agreement.id}-enabled`]?.checked ?? false,
      applySeniority: refs.form.elements[`agreement-${agreement.id}-applySeniority`]?.checked ?? false,
      applySocialSecurity: refs.form.elements[`agreement-${agreement.id}-applySocialSecurity`]?.checked ?? false,
      applyHealthAndUnion: refs.form.elements[`agreement-${agreement.id}-applyHealthAndUnion`]?.checked ?? false,
      applyZone: refs.form.elements[`agreement-${agreement.id}-applyZone`]?.checked ?? false,
      prorateByDays: refs.form.elements[`agreement-${agreement.id}-prorateByDays`]?.checked ?? false
    };
    return accumulator;
  }, {});
}

function collectRevistaSegments(refs) {
  return [1, 2, 3]
    .map((index) => ({
      codigo: String(refs.form.elements[`revistaSegment${index}Code`]?.value || "").trim(),
      desde: Number(refs.form.elements[`revistaSegment${index}From`]?.value || 0),
      hasta: Number(refs.form.elements[`revistaSegment${index}To`]?.value || 0)
    }))
    .filter((segment) => segment.codigo || segment.desde || segment.hasta);
}

function collectInput(refs) {
  const dateString = refs.form.elements.liquidationDate.value;
  return {
    liquidationDate: dateString,
    liquidationType: refs.form.elements.liquidationType.value,
    categoryId: refs.form.elements.categoryId.value,
    seniorityYears: Number(refs.form.elements.seniorityYears.value),
    seniorityMonths: Number(refs.form.elements.seniorityMonths.value),
    jornadaCoefficient: Number(refs.form.elements.jornadaCoefficient?.value || 1),
    liquidationMode: refs.form.elements.liquidationMode?.value || "normal",
    workedDays: Number(refs.form.elements.workedDays.value),
    overtime50Hours: Number(refs.form.elements.overtime50Hours.value),
    overtime100Hours: Number(refs.form.elements.overtime100Hours.value),
    licensedDays: Number(refs.form.elements.licensedDays?.value || 0),
    suspensionDays: Number(refs.form.elements.suspensionDays?.value || 0),
    absenceDays: Number(refs.form.elements.absenceDays?.value || 0),
    vacationDays: Number(refs.form.elements.vacationDays.value),
    unusedVacationDays: Number(refs.form.elements.unusedVacationDays.value),
    semesterDaysWorked: Number(refs.form.elements.semesterDaysWorked.value),
    zoneUnfavorable: refs.form.elements.zoneUnfavorable.checked,
    nightShift: refs.form.elements.nightShift.checked,
    includeNonRemuneratives: refs.form.elements.includeNonRemuneratives.checked,
    presentismo: refs.form.elements.presentismo.checked,
    applyUnion: refs.form.elements.applyUnion.checked,
    previewAudit: refs.form.elements.previewAudit?.checked ?? true,
    persistWizardState: refs.form.elements.persistWizardState?.checked ?? true,
    debugMode: refs.form.elements.debugMode.checked,
    agreementOverrides: collectAgreementOverrides(refs, dateString),
    revistaSegments: collectRevistaSegments(refs)
  };
}

function persistWizardState(refs) {
  try {
    const storage = safeLocalStorage();
    if (!storage) return;
    const persistEnabled = refs.form?.elements?.persistWizardState?.checked ?? true;
    if (!persistEnabled) {
      storage.removeItem(STORAGE_KEY);
      return;
    }
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        currentStep: appState.currentStep,
        input: collectInput(refs)
      })
    );
  } catch (_error) {
    // Ignore local persistence errors to keep the flow offline-friendly.
  }
}

function applyPersistedInput(refs, persistedInput) {
  if (!persistedInput) return;

  const assignValue = (name, value) => {
    const field = refs.form.elements[name];
    if (!field || value === undefined || value === null) return;
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
      return;
    }
    field.value = String(value);
  };

  [
    "liquidationDate",
    "liquidationType",
    "seniorityYears",
    "seniorityMonths",
    "jornadaCoefficient",
    "liquidationMode",
    "workedDays",
    "overtime50Hours",
    "overtime100Hours",
    "licensedDays",
    "suspensionDays",
    "absenceDays",
    "vacationDays",
    "unusedVacationDays",
    "semesterDaysWorked"
  ].forEach((name) => assignValue(name, persistedInput[name]));

  [
    "zoneUnfavorable",
    "nightShift",
    "includeNonRemuneratives",
    "presentismo",
    "applyUnion",
    "previewAudit",
    "persistWizardState",
    "debugMode"
  ].forEach((name) => assignValue(name, persistedInput[name]));

  renderCategoryOptions(refs);
  if (persistedInput.categoryId) {
    assignValue("categoryId", persistedInput.categoryId);
  }

  renderAgreementControls(refs);
  Object.entries(persistedInput.agreementOverrides || {}).forEach(([agreementId, values]) => {
    Object.entries(values || {}).forEach(([key, value]) => {
      assignValue(`agreement-${agreementId}-${key}`, value);
    });
  });

  [1, 2, 3].forEach((index) => {
    const segment = persistedInput.revistaSegments?.[index - 1];
    assignValue(`revistaSegment${index}Code`, segment?.codigo || "");
    assignValue(`revistaSegment${index}From`, segment?.desde || "");
    assignValue(`revistaSegment${index}To`, segment?.hasta || "");
  });

  updateConditionalFields(refs);
  updateContextKpis(refs);
  renderScaleDeck(refs, refs.dateInput.value);
  renderAgreementDeck(refs, refs.dateInput.value);
}

function buildViewModel(liquidation) {
  const values = liquidation?.debug?.values || {};
  return {
    type: liquidation?.metadata?.type || "mensual",
    input: liquidation?.metadata?.input || {},
    category: liquidation?.metadata?.category || {},
    scale: liquidation?.metadata?.scale || {},
    monthlyEquivalent: liquidation?.bases?.equivalenteMensual || 0,
    seniorityPercent: liquidation?.bases?.porcentajeAntiguedad || 0,
    values,
    nonRemConcepts: liquidation?.debug?.nonRemConcepts || [],
    steps: liquidation?.metadata?.steps || [],
    sourceNotes: liquidation?.metadata?.sourceNotes || []
  };
}

function buildExplanationText(liquidation) {
  const view = buildViewModel(liquidation);
  return `La liquidacion se resolvio para ${view.category.label || "la categoria seleccionada"} bajo ${view.scale.label || "la escala activa"}, tomando un equivalente mensual de ${formatCurrency(view.monthlyEquivalent)}, antiguedad del ${formatPercent(view.seniorityPercent)}, bruto remunerativo de ${formatCurrency(view.values.grossRemunerative || 0)}, descuentos por ${formatCurrency(view.values.totalDeductions || 0)} y total en bolsillo de ${formatCurrency(liquidation?.totales?.bolsillo || 0)}. El auditor preventivo corre despues del calculo y controla revista, serie 990, mapeo AFIP y consistencia estructural.`;
}

function getFlowAmount(liquidation, code) {
  if (!liquidation) return null;
  const view = buildViewModel(liquidation);
  const values = view.values;
  const mapping = {
    C001: view.type === "vacaciones" ? values.grossRemunerative : values.basicProportional,
    C002: values.seniority,
    C003: values.presentismo,
    BASE: values.baseCalculation,
    ADIC: roundMoney((values.zone || 0) + (values.nocturnity || 0) + (values.overtime50 || 0) + (values.overtime100 || 0)),
    VH: values.hourValue,
    HEX: roundMoney((values.overtime50 || 0) + (values.overtime100 || 0)),
    BRUTO: values.grossRemunerative,
    BASESS: values.socialSecurityBase,
    DESC: values.totalDeductions,
    NETO: values.netRemunerative,
    NR: values.nonRemunerativeTotal,
    BOLS: values.totalPocket
  };
  return mapping[code] ?? null;
}

function renderReceipt(refs, liquidation) {
  if (!refs.receiptView) return;
  if (!liquidation) {
    refs.receiptView.innerHTML = '<div class="skill-empty">No hay liquidacion calculada para mostrar en formato recibo.</div>';
    return;
  }

  const view = buildViewModel(liquidation);
  const remuneratives = [
    { label: "Basico / concepto principal", amount: view.type === "vacaciones" ? view.values.grossRemunerative : view.values.basicProportional },
    { label: "Antiguedad", amount: view.values.seniority },
    { label: "Zona desfavorable", amount: view.values.zone },
    { label: "Horas extra 50%", amount: view.values.overtime50 },
    { label: "Horas extra 100%", amount: view.values.overtime100 }
  ];

  if (view.type === "final") {
    remuneratives.push(
      { label: "SAC proporcional", amount: view.values.sacProportional },
      { label: "Vacaciones no gozadas", amount: view.values.unusedVacation },
      { label: "SAC s/vacaciones", amount: view.values.sacOnUnusedVacation }
    );
  }

  const renderReceiptRows = (rows) =>
    rows
      .map((row) => `<div class="receipt-row"><span>${escapeHtml(row.label)}</span><span>${escapeHtml(formatCurrency(row.amount || 0))}</span></div>`)
      .join("");

  refs.receiptView.innerHTML = `
    <div class="receipt-hero">
      <strong>Liquidacion ${escapeHtml(view.type)}</strong>
      <div class="receipt-meta">
        <span>${escapeHtml(view.category.label || "Sin categoria")}</span>
        <span>${escapeHtml(view.scale.label || "Sin escala")}</span>
        <span>${escapeHtml(formatDate(view.input.liquidationDate))}</span>
        <span>${view.category.payBasis === "hourly" ? "Jornalizada" : "Mensualizada"}</span>
      </div>
    </div>
    <div class="receipt-columns">
      <section class="receipt-column">
        <h4>Haberes remunerativos</h4>
        ${renderReceiptRows(remuneratives)}
        <div class="receipt-total">
          <strong>Bruto remunerativo</strong>
          <strong>${escapeHtml(formatCurrency(view.values.grossRemunerative || 0))}</strong>
        </div>
      </section>
      <section class="receipt-column">
        <h4>Descuentos</h4>
        ${renderReceiptRows([
          { label: "Jubilacion", amount: view.values.deductions?.retirement },
          { label: "PAMI", amount: view.values.deductions?.pami },
          { label: "Obra social", amount: view.values.deductions?.health },
          { label: "Sindicato", amount: view.values.deductions?.union }
        ])}
        <div class="receipt-total">
          <strong>Total descuentos</strong>
          <strong>${escapeHtml(formatCurrency(view.values.totalDeductions || 0))}</strong>
        </div>
      </section>
    </div>
    <div class="receipt-columns">
      <section class="receipt-column">
        <h4>No remunerativos</h4>
        ${
          view.nonRemConcepts.length
            ? renderReceiptRows(view.nonRemConcepts.map((item) => ({ label: item.label, amount: item.subtotal })))
            : '<div class="receipt-row"><span>Sin conceptos NR activos</span><span>$ 0,00</span></div>'
        }
      </section>
      <section class="receipt-column">
        <h4>Cierre de bolsillo</h4>
        ${renderReceiptRows([
          { label: "Neto remunerativo", amount: view.values.netRemunerative },
          { label: "No remunerativos", amount: view.values.nonRemunerativeTotal }
        ])}
        <div class="receipt-total">
          <strong>Total en bolsillo</strong>
          <strong>${escapeHtml(formatCurrency(liquidation.totales?.bolsillo || 0))}</strong>
        </div>
      </section>
    </div>
  `;
}

function renderSourcesPanel(refs, liquidation) {
  if (!refs.sourcesPanel) return;
  refs.sourcesPanel.innerHTML = "";

  (liquidation?.metadata?.sourceNotes || []).forEach((note) => {
    const article = document.createElement("article");
    article.className = "source-item";
    article.innerHTML = `<strong>${escapeHtml(note.title)}</strong><p>${escapeHtml(note.body)}</p>`;
    refs.sourcesPanel.append(article);
  });
}

function buildEmptyStateMarkup(title, body) {
  return `
    <article class="audit-empty">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(body)}</p>
    </article>
  `;
}

function buildCategorySelectOptions(select, scale) {
  if (!select) return;
  select.innerHTML = "";

  const grouped = scale.categories.reduce((accumulator, category) => {
    if (!accumulator[category.sector]) accumulator[category.sector] = [];
    accumulator[category.sector].push(category);
    return accumulator;
  }, {});

  Object.entries(grouped).forEach(([sector, categories]) => {
    const optgroup = document.createElement("optgroup");
    optgroup.label = sector;
    categories.forEach((category) => {
      const option = document.createElement("option");
      option.value = category.id;
      option.textContent = `${category.label} · ${category.payBasis === "hourly" ? "valor hora" : "mensual"}`;
      optgroup.append(option);
    });
    select.append(optgroup);
  });
}

function getCurrentScenarioLiquidation(refs) {
  return calculateLiquidation(collectInput(refs));
}

function addMonthsToDate(dateString, offset) {
  if (!dateString) return null;
  const [year, month] = String(dateString).split("-").map(Number);
  if (!year || !month) return null;
  return new Date(year, month - 1 + offset, 1);
}

function formatMonthProjection(dateString, offset) {
  const date = addMonthsToDate(dateString, offset);
  return date ? monthFormatter.format(date) : `Mes ${offset}`;
}

function renderToolboxContext(refs) {
  const scale = resolveScale(refs.dateInput?.value);
  const activeDate = refs.dateInput?.value;
  const currentCategory = scale?.categories.find((item) => item.id === refs.categorySelect?.value) || scale?.categories[0];

  if (refs.simContextCaption) {
    refs.simContextCaption.textContent = scale && currentCategory
      ? `Base actual: ${currentCategory.label} · ${scale.label} · ${formatDate(activeDate)}.`
      : "Completa fecha y categoria para habilitar la simulacion.";
  }

  if (refs.compareContextCaption) {
    refs.compareContextCaption.textContent = scale
      ? `Compara categorias sobre la misma fecha, jornada y novedades cargadas en el flujo principal.`
      : "No hay escala activa para la fecha indicada.";
  }

  if (!refs.compareCategoryLeft || !refs.compareCategoryRight) return;

  if (!scale) {
    refs.compareCategoryLeft.innerHTML = '<option value="">Sin escala activa</option>';
    refs.compareCategoryRight.innerHTML = '<option value="">Sin escala activa</option>';
    return;
  }

  const previousLeft = refs.compareCategoryLeft.value;
  const previousRight = refs.compareCategoryRight.value;
  buildCategorySelectOptions(refs.compareCategoryLeft, scale);
  buildCategorySelectOptions(refs.compareCategoryRight, scale);

  const availableIds = scale.categories.map((category) => category.id);
  const preferredLeft = availableIds.includes(previousLeft)
    ? previousLeft
    : availableIds.includes(refs.categorySelect?.value)
      ? refs.categorySelect.value
      : availableIds[0];
  const preferredRight = availableIds.includes(previousRight)
    ? previousRight
    : availableIds.find((categoryId) => categoryId !== preferredLeft) || preferredLeft;

  refs.compareCategoryLeft.value = preferredLeft;
  refs.compareCategoryRight.value = preferredRight;
}

function renderSimulator(refs, liquidation = null) {
  if (!refs.simResult) return;

  let scenario = liquidation;
  try {
    scenario ||= getCurrentScenarioLiquidation(refs);
  } catch (error) {
    refs.simResult.innerHTML = buildEmptyStateMarkup(
      "Simulacion no disponible",
      error.message || "Completa los datos principales para proyectar meses futuros."
    );
    return;
  }

  const months = Math.min(24, Math.max(1, Math.round(numberOrZero(refs.simMonthsInput?.value) || 6)));
  const remRate = numberOrZero(refs.simRemPercentInput?.value) / 100;
  const nrRate = numberOrZero(refs.simNrPercentInput?.value) / 100;
  const currentRem = scenario.totales?.remunerativo || 0;
  const currentNr = scenario.totales?.noRemunerativo || 0;
  const currentPocket = scenario.totales?.bolsillo || 0;
  const discountRate = currentRem > 0 ? (scenario.totales?.descuentos || 0) / currentRem : 0;

  const rows = Array.from({ length: months }, (_item, index) => {
    const monthOffset = index + 1;
    const projectedRem = roundMoney(currentRem * Math.pow(1 + remRate, monthOffset));
    const projectedNr = roundMoney(currentNr * Math.pow(1 + nrRate, monthOffset));
    const projectedDeductions = roundMoney(projectedRem * discountRate);
    const projectedPocket = roundMoney(projectedRem - projectedDeductions + projectedNr);
    const variation = currentPocket > 0 ? (projectedPocket - currentPocket) / currentPocket : 0;

    return `
      <tr>
        <td>${escapeHtml(formatMonthProjection(refs.dateInput?.value, monthOffset))}</td>
        <td>${escapeHtml(formatCurrency(projectedRem))}</td>
        <td>${escapeHtml(formatCurrency(projectedNr))}</td>
        <td>${escapeHtml(formatCurrency(projectedDeductions))}</td>
        <td>${escapeHtml(formatCurrency(projectedPocket))}</td>
        <td>${escapeHtml(formatPercent(variation))}</td>
      </tr>
    `;
  }).join("");

  refs.simResult.innerHTML = `
    <div class="cost-note">
      Proyeccion estimativa sobre la liquidacion actual. Aplica ${escapeHtml(formatPercent(remRate))} mensual sobre remunerativos y ${escapeHtml(formatPercent(nrRate))} sobre no remunerativos, manteniendo la misma estructura de descuentos.
    </div>
    <table class="scale-table">
      <thead>
        <tr>
          <th>Mes</th>
          <th>Remunerativo</th>
          <th>No remunerativo</th>
          <th>Descuentos</th>
          <th>Bolsillo estimado</th>
          <th>Var. bolsillo</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Base actual</strong></td>
          <td>${escapeHtml(formatCurrency(currentRem))}</td>
          <td>${escapeHtml(formatCurrency(currentNr))}</td>
          <td>${escapeHtml(formatCurrency(scenario.totales?.descuentos || 0))}</td>
          <td>${escapeHtml(formatCurrency(currentPocket))}</td>
          <td>${escapeHtml(formatPercent(0))}</td>
        </tr>
        ${rows}
      </tbody>
    </table>
  `;
}

function renderComparator(refs, liquidation = null) {
  if (!refs.compareResult) return;

  const leftCategoryId = refs.compareCategoryLeft?.value;
  const rightCategoryId = refs.compareCategoryRight?.value;
  if (!leftCategoryId || !rightCategoryId) {
    refs.compareResult.innerHTML = buildEmptyStateMarkup(
      "Comparador no disponible",
      "Selecciona una escala activa para comparar categorias."
    );
    return;
  }

  let baseInput;
  try {
    baseInput = collectInput(refs);
  } catch (error) {
    refs.compareResult.innerHTML = buildEmptyStateMarkup(
      "Comparador no disponible",
      error.message || "Completa los datos principales para comparar escenarios."
    );
    return;
  }

  try {
    const leftLiquidation =
      liquidation && liquidation.metadata?.category?.id === leftCategoryId
        ? liquidation
        : calculateLiquidation({ ...baseInput, categoryId: leftCategoryId });
    const rightLiquidation = calculateLiquidation({ ...baseInput, categoryId: rightCategoryId });

    const compareRows = [
      {
        label: "Valor convenio",
        left: leftLiquidation.metadata?.category?.amount || 0,
        right: rightLiquidation.metadata?.category?.amount || 0
      },
      {
        label: "Equivalente mensual",
        left: leftLiquidation.bases?.equivalenteMensual || 0,
        right: rightLiquidation.bases?.equivalenteMensual || 0
      },
      {
        label: "Valor hora",
        left: leftLiquidation.bases?.valorHora || 0,
        right: rightLiquidation.bases?.valorHora || 0
      },
      {
        label: "Bruto remunerativo",
        left: leftLiquidation.totales?.remunerativo || 0,
        right: rightLiquidation.totales?.remunerativo || 0
      },
      {
        label: "Descuentos",
        left: leftLiquidation.totales?.descuentos || 0,
        right: rightLiquidation.totales?.descuentos || 0
      },
      {
        label: "No remunerativo",
        left: leftLiquidation.totales?.noRemunerativo || 0,
        right: rightLiquidation.totales?.noRemunerativo || 0
      },
      {
        label: "Total en bolsillo",
        left: leftLiquidation.totales?.bolsillo || 0,
        right: rightLiquidation.totales?.bolsillo || 0
      }
    ];

    refs.compareResult.innerHTML = `
      <div class="cost-note">
        La comparacion reutiliza la misma fecha, tipo de liquidacion, jornada, antiguedad y novedades. Solo cambia la categoria.
      </div>
      <table class="scale-table">
        <thead>
          <tr>
            <th>Variable</th>
            <th>${escapeHtml(leftLiquidation.metadata?.category?.label || "Categoria A")}</th>
            <th>${escapeHtml(rightLiquidation.metadata?.category?.label || "Categoria B")}</th>
            <th>Diferencia</th>
          </tr>
        </thead>
        <tbody>
          ${compareRows
            .map((row) => {
              const delta = roundMoney(row.right - row.left);
              return `
                <tr>
                  <td>${escapeHtml(row.label)}</td>
                  <td>${escapeHtml(formatCurrency(row.left))}</td>
                  <td>${escapeHtml(formatCurrency(row.right))}</td>
                  <td>${escapeHtml(formatCurrency(delta))}</td>
                </tr>
              `;
            })
            .join("")}
        </tbody>
      </table>
    `;
  } catch (error) {
    refs.compareResult.innerHTML = buildEmptyStateMarkup(
      "Comparador no disponible",
      error.message || "No se pudieron resolver los escenarios comparados."
    );
  }
}

function renderDistribution(refs, liquidation) {
  if (!refs.distributionView) return;

  if (!liquidation) {
    refs.distributionView.innerHTML = buildEmptyStateMarkup(
      "Distribucion pendiente",
      "Calcula una liquidacion para ver como se reparte el salario entre conceptos."
    );
    return;
  }

  const view = buildViewModel(liquidation);
  const values = view.values;
  const rows = [
    {
      label: "Basico convenio",
      amount: view.type === "vacaciones" ? values.grossRemunerative : values.basicProportional,
      color: "#0f766e"
    },
    { label: "Antiguedad", amount: values.seniority, color: "#2563eb" },
    { label: "Presentismo", amount: values.presentismo, color: "#8b5cf6" },
    { label: "Zona desfavorable", amount: values.zone, color: "#f59e0b" },
    { label: "Horas extra 50%", amount: values.overtime50, color: "#ef4444" },
    { label: "Horas extra 100%", amount: values.overtime100, color: "#dc2626" },
    { label: "SAC proporcional", amount: values.sacProportional, color: "#14b8a6" },
    { label: "Vacaciones no gozadas", amount: values.unusedVacation, color: "#0891b2" },
    { label: "SAC s/vacaciones", amount: values.sacOnUnusedVacation, color: "#6366f1" },
    { label: "No remunerativos", amount: values.nonRemunerativeTotal, color: "#ec4899" }
  ].filter((row) => roundMoney(row.amount) > 0);

  const totalPositive = rows.reduce((accumulator, row) => accumulator + row.amount, 0);
  if (!totalPositive) {
    refs.distributionView.innerHTML = buildEmptyStateMarkup(
      "Distribucion vacia",
      "No hay conceptos positivos para representar en el periodo seleccionado."
    );
    return;
  }

  refs.distributionView.innerHTML = `
    <div class="distribution-topline">
      <article>
        <small>Bruto remunerativo</small>
        <strong>${escapeHtml(formatCurrency(liquidation.totales?.remunerativo || 0))}</strong>
      </article>
      <article>
        <small>No remunerativo</small>
        <strong>${escapeHtml(formatCurrency(liquidation.totales?.noRemunerativo || 0))}</strong>
      </article>
      <article>
        <small>Descuentos</small>
        <strong>${escapeHtml(formatCurrency(liquidation.totales?.descuentos || 0))}</strong>
      </article>
      <article>
        <small>Total bolsillo</small>
        <strong>${escapeHtml(formatCurrency(liquidation.totales?.bolsillo || 0))}</strong>
      </article>
    </div>
    <div class="distribution-stack">
      ${rows
        .map((row) => {
          const share = row.amount / totalPositive;
          return `
            <div class="distribution-row">
              <div>
                <strong>${escapeHtml(row.label)}</strong>
                <small>${escapeHtml(formatPercent(share))} del total positivo</small>
              </div>
              <span>${escapeHtml(formatCurrency(row.amount))}</span>
            </div>
            <div class="distribution-track">
              <span class="distribution-fill" style="width:${Math.max(share * 100, 4)}%; background:${row.color};"></span>
            </div>
          `;
        })
        .join("")}
    </div>
    <p class="distribution-footnote">
      La distribucion muestra los conceptos positivos del periodo. Los descuentos se resumen arriba para no distorsionar la composicion del salario generado.
    </p>
  `;
}

function renderEmployerCost(refs, liquidation) {
  if (!refs.employerCostView) return;

  if (!liquidation) {
    refs.employerCostView.innerHTML = buildEmptyStateMarkup(
      "Costo empleador pendiente",
      "Calcula una liquidacion para estimar el costo total del periodo."
    );
    return;
  }

  const socialBase = liquidation.bases?.seguridadSocial || 0;
  const healthBase = liquidation.bases?.obraSocialSindicato || 0;
  const contributionRows = EMPLOYER_REFERENCE_RATES.map((item) => {
    const baseAmount = item.base === "health" ? healthBase : socialBase;
    return {
      ...item,
      baseAmount,
      amount: roundMoney(baseAmount * item.rate)
    };
  }).filter((row) => roundMoney(row.amount) > 0);

  const totalContributions = contributionRows.reduce((accumulator, row) => accumulator + row.amount, 0);
  const directPayroll = roundMoney((liquidation.totales?.remunerativo || 0) + (liquidation.totales?.noRemunerativo || 0));
  const totalEmployerCost = roundMoney(directPayroll + totalContributions);

  refs.employerCostView.innerHTML = `
    <div class="distribution-topline">
      <article>
        <small>Costo salarial directo</small>
        <strong>${escapeHtml(formatCurrency(directPayroll))}</strong>
      </article>
      <article>
        <small>Contribuciones estimadas</small>
        <strong>${escapeHtml(formatCurrency(totalContributions))}</strong>
      </article>
      <article>
        <small>Costo total referencial</small>
        <strong>${escapeHtml(formatCurrency(totalEmployerCost))}</strong>
      </article>
    </div>
    <table class="scale-table">
      <thead>
        <tr>
          <th>Concepto</th>
          <th>Base</th>
          <th>Alicuota</th>
          <th>Importe estimado</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Costo salarial directo</td>
          <td>${escapeHtml(formatCurrency(directPayroll))}</td>
          <td>No aplica</td>
          <td>${escapeHtml(formatCurrency(directPayroll))}</td>
        </tr>
        ${contributionRows
          .map(
            (row) => `
              <tr>
                <td>${escapeHtml(row.label)}</td>
                <td>${escapeHtml(formatCurrency(row.baseAmount))}</td>
                <td>${escapeHtml(formatPercent(row.rate))}</td>
                <td>${escapeHtml(formatCurrency(row.amount))}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
    <p class="cost-note">
      Estimacion referencial armada sobre las bases ya calculadas por la liquidacion. No incluye ART, seguros, alicuotas diferenciales, costos sindicales patronales ni otras cargas indirectas.
    </p>
  `;
}

function renderMatrixPanel(refs, liquidation, audit) {
  if (refs.confidenceScore) {
    refs.confidenceScore.textContent = `${audit?.score ?? 100}/100`;
  }

  renderRows(refs.matrixRuleList, [
    ...ruleSnapshots,
    {
      label: "Escala activa",
      valueText: liquidation?.metadata?.scale?.label || "Sin calculo actual",
      note: liquidation?.metadata?.scale?.sourceLabel || "La matriz toma la fecha de liquidacion seleccionada."
    },
    {
      label: "Acuerdos NR activos",
      valueText: String(liquidation?.debug?.nonRemConcepts?.length || 0),
      note: "Cantidad de conceptos no remunerativos efectivamente usados o disponibles."
    },
    {
      label: "Score preventivo",
      valueText: `${audit?.score ?? 100}/100`,
      note: audit ? `Estado ${audit.estado}` : "Sin auditoria ejecutada."
    }
  ]);

  refs.matrixFlowBody.innerHTML = "";
  modelFlow.forEach((item) => {
    const amount = getFlowAmount(liquidation, item.code);
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.step}</td>
      <td><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.code)}</small></td>
      <td>${escapeHtml(item.rule)}</td>
      <td>${amount === null ? "—" : escapeHtml(formatCurrency(amount))}</td>
    `;
    refs.matrixFlowBody.append(row);
  });
}

function buildAuditCounts(audit) {
  return {
    blockers: audit?.bloqueos?.length || 0,
    critical: audit?.errores?.length || 0,
    warning: audit?.warnings?.length || 0,
    info: audit?.info?.length || 0
  };
}

function collectAuditFindings(audit) {
  return [...(audit?.bloqueos || []), ...(audit?.errores || []), ...(audit?.warnings || []), ...(audit?.info || [])];
}

function renderAuditIdle(refs, message = "Esperando una liquidacion valida para auditar.") {
  if (refs.autoAuditBox) {
    refs.autoAuditBox.open = true;
  }
  refs.auditExportCard?.classList.remove("is-blocked");
  refs.auditExportCard?.classList.add("is-ready");
  refs.auditExportStatus.textContent = "Esperando liquidacion";
  refs.auditExportCaption.textContent = message;
  refs.auditScore.textContent = "--/100";
  refs.auditScoreCaption.textContent = "Sin evaluacion todavia.";
  refs.auditNetGap.textContent = formatCurrency(0);
  refs.auditNetGapCaption.textContent = "996 vs neto reconstruido.";
  refs.auditCoveredDays.textContent = "0 / 30";
  refs.auditCoveredCaption.textContent = "Sin datos todavia.";
  refs.auditFindings.innerHTML = `
    <article class="audit-empty">
      <strong>Motor listo.</strong>
      <p>${escapeHtml(message)}</p>
    </article>
  `;
  refs.auditSources.innerHTML = "";
}

function renderAuditTraceability(refs, audit, liquidation, catalogs) {
  refs.auditSources.innerHTML = "";

  const checklist = document.createElement("article");
  checklist.className = "source-item";
  checklist.innerHTML = `
    <strong>POR QUE APROBO / QUE FALLO</strong>
    <div class="rows">
      ${audit.checklist
        .map(
          (item) => `
            <article class="row-item">
              <div>
                <strong>${escapeHtml(item.label)}</strong>
                <small>${item.ok ? "Cumple" : "Revisar"}</small>
              </div>
              <span>${item.ok ? "OK" : "FALLO"}</span>
            </article>
          `
        )
        .join("")}
    </div>
  `;
  refs.auditSources.append(checklist);

  const traceWrapper = document.createElement("article");
  traceWrapper.className = "source-item";
  traceWrapper.innerHTML = `<strong>TRAZABILIDAD AUDITORIA</strong>`;
  audit.trazabilidad.forEach((trace) => {
    const block = document.createElement("div");
    block.style.marginTop = "14px";
    block.innerHTML = `
      <strong>[${escapeHtml(trace.label)}]</strong>
      <pre style="white-space: pre-wrap; margin: 8px 0 0;">${escapeHtml((trace.lines || []).join("\n"))}</pre>
    `;
    traceWrapper.append(block);
  });
  refs.auditSources.append(traceWrapper);

  const versions = document.createElement("article");
  versions.className = "source-item";
  versions.innerHTML = `
    <strong>Versionado local</strong>
    <p>conceptos ${escapeHtml(catalogs.metadata.conceptosVersion)} · reglas ${escapeHtml(catalogs.metadata.reglasVersion)} · formulas ${escapeHtml(catalogs.metadata.formulasVersion)} · AFIP ${escapeHtml(catalogs.metadata.mapeoVersion)} · convenio ${escapeHtml(catalogs.metadata.convenioVersion)}</p>
  `;
  refs.auditSources.append(versions);

  const findingCodes = new Set(collectAuditFindings(audit).map((item) => item.code));
  const supportingArticles = (catalogs.convenio_244_94 || []).filter((item) =>
    (item.reglas_relacionadas || []).some((code) => findingCodes.has(code))
  );
  if (supportingArticles.length) {
    const article = document.createElement("article");
    article.className = "source-item";
    article.innerHTML = `
      <strong>Soporte convenio relacionado</strong>
      <p>${supportingArticles.map((item) => `${item.articulo}: ${item.tema}`).join(" · ")}</p>
    `;
    refs.auditSources.append(article);
  }

  const revista = liquidation.revista || {};
  const series = liquidation.totales?.serie990 || {};
  const snapshot = document.createElement("article");
  snapshot.className = "source-item";
  snapshot.innerHTML = `
    <strong>Snapshot auditado</strong>
    <p>Revista declarada: ${escapeHtml(String(revista.diasTrabajados ?? 0))} dias trabajados, ${escapeHtml(String(revista.diasSinClasificar ?? 0))} dias sin clasificar. Serie 990: 993 ${escapeHtml(formatCurrency(series["993"] || 0))}, 994 ${escapeHtml(formatCurrency(series["994"] || 0))}, 995 ${escapeHtml(formatCurrency(series["995"] || 0))}, 996 ${escapeHtml(formatCurrency(series["996"] || 0))}.</p>
  `;
  refs.auditSources.append(snapshot);
}

function renderAudit(refs, audit, liquidation, catalogs) {
  if (!audit || !liquidation) {
    renderAuditIdle(refs);
    return;
  }

  const counts = buildAuditCounts(audit);
  const findings = collectAuditFindings(audit);
  const series = liquidation.totales?.serie990 || {};
  const expectedNet = roundMoney((series["993"] || 0) + (series["994"] || 0) + (series["997"] || 0) - (series["995"] || 0));
  const actualNet = roundMoney(series["996"] || 0);
  const gap = roundMoney(actualNet - expectedNet);
  const classifiedDays = (liquidation.revista?.tramos || [])
    .filter((item) => item.codigo)
    .reduce((accumulator, item) => accumulator + Math.max(0, item.hasta - item.desde + 1), 0);
  const totalDays = liquidation.revista?.diasPeriodo || 30;

  if (refs.autoAuditBox) {
    refs.autoAuditBox.open = true;
  }

  refs.auditExportCard?.classList.toggle("is-blocked", audit.estado === "BLOCKED");
  refs.auditExportCard?.classList.toggle("is-ready", audit.estado === "OK");
  refs.auditExportStatus.textContent =
    audit.estado === "BLOCKED"
      ? "Bloquear exportacion"
      : audit.estado === "CRITICAL"
        ? "Correccion prioritaria"
        : audit.estado === "WARNING"
          ? "Revisar antes de cerrar"
          : "Apto";
  refs.auditExportCaption.textContent =
    audit.estado === "BLOCKED"
      ? "Se detectaron reglas bloqueantes antes del cierre."
      : audit.estado === "CRITICAL"
        ? "No hay bloqueo formal, pero la auditoria detecto riesgo alto."
        : audit.estado === "WARNING"
          ? "La liquidacion paso, pero quedan observaciones preventivas."
          : "La liquidacion aprobo las reglas deterministicas actuales.";

  refs.auditScore.textContent = `${audit.score}/100`;
  refs.auditScoreCaption.textContent = `${counts.blockers} blocker · ${counts.critical} critical · ${counts.warning} warning · ${counts.info} info`;
  refs.auditNetGap.textContent = formatCurrency(gap);
  refs.auditNetGapCaption.textContent = `996 esperado ${formatCurrency(expectedNet)} vs 996 calculado ${formatCurrency(actualNet)}`;
  refs.auditCoveredDays.textContent = `${classifiedDays} / ${totalDays}`;
  refs.auditCoveredCaption.textContent = `${liquidation.revista?.tramos?.length || 0} tramos · ${liquidation.revista?.diasSinClasificar || 0} dias sin clasificar`;

  refs.auditFindings.innerHTML = "";
  if (!findings.length) {
    refs.auditFindings.innerHTML = `
      <article class="audit-empty">
        <strong>Sin observaciones criticas.</strong>
        <p>Serie 990, revista, conceptos y mapeo quedaron consistentes para este escenario.</p>
      </article>
    `;
  } else {
    findings.forEach((finding) => {
      const article = document.createElement("article");
      article.className = `audit-finding is-${String(finding.severity || "info").toLowerCase()}`;
      article.innerHTML = `
        <strong>${escapeHtml(finding.title || finding.code)}</strong>
        <small>${escapeHtml(finding.severity || "INFO")} · ${escapeHtml(finding.code || "SIN_CODIGO")}</small>
        <p>${escapeHtml(finding.message || "Sin detalle.")}</p>
      `;
      refs.auditFindings.append(article);
    });
  }

  renderAuditTraceability(refs, audit, liquidation, catalogs);
}

function buildDebugSteps(liquidation, audit) {
  const series = liquidation?.totales?.serie990 || {};
  const revista = liquidation?.revista || {};
  return [
    { label: "Serie 993", amount: series["993"] || 0, formula: "Total remunerativo auditado" },
    { label: "Serie 994", amount: series["994"] || 0, formula: "Total no remunerativo auditado" },
    { label: "Serie 995", amount: series["995"] || 0, formula: "Total descuentos auditado" },
    { label: "Serie 996", amount: series["996"] || 0, formula: "Neto final auditado" },
    {
      label: "Revista declarada",
      amount: revista.diasTrabajados || 0,
      formula: `${revista.diasTrabajados || 0} dias trabajados, ${revista.diasSinClasificar || 0} dias sin clasificar`
    },
    {
      label: "Score preventivo",
      amount: audit?.score || 0,
      formula: audit ? `Estado ${audit.estado}` : "Sin auditoria"
    }
  ];
}

function buildSkillObservations(liquidation, audit) {
  const observations = [];
  (liquidation?.metadata?.warnings || []).forEach((warning) => {
    observations.push({ type: "WARNING", text: warning });
  });
  collectAuditFindings(audit).forEach((finding) => {
    observations.push({ type: finding.severity || "INFO", text: `${finding.code}: ${finding.message}` });
  });
  return observations;
}

function renderSkillModal(refs) {
  const liquidation = appState.latestLiquidation;
  const audit = appState.latestAudit;
  if (!liquidation) return;

  const view = buildViewModel(liquidation);
  const observations = buildSkillObservations(liquidation, audit);
  const badgeClass =
    audit?.estado === "BLOCKED"
      ? "status-error"
      : audit?.estado === "CRITICAL"
        ? "status-warn"
        : audit?.estado === "WARNING"
          ? "status-warn"
          : "status-ok";
  const captionClass =
    audit?.estado === "BLOCKED"
      ? "badge-warn"
      : audit?.estado === "WARNING" || audit?.estado === "CRITICAL"
        ? "badge-info"
        : "badge-info";

  refs.skillStatusBadge.className = `status-badge ${badgeClass}`;
  refs.skillStatusBadge.textContent = audit?.estado || "OK";
  refs.skillStatusCaption.className = `type-badge ${captionClass}`;
  refs.skillStatusCaption.textContent = audit ? `Score ${audit.score}/100` : "Liquidacion interpretada";

  refs.skillSummaryText.innerHTML = `
    <p>${escapeHtml(buildExplanationText(liquidation))}</p>
    <p>Pipeline aplicado: inputs -> calcularLiquidacion() -> objeto liquidacion -> ejecutarAuditoria() -> render UI -> Gemini opcional.</p>
  `;

  refs.skillSummaryMetrics.innerHTML = [
    { label: "Bruto remunerativo", value: formatCurrency(view.values.grossRemunerative || 0) },
    { label: "Descuentos", value: formatCurrency(view.values.totalDeductions || 0) },
    { label: "Total bolsillo", value: formatCurrency(liquidation.totales?.bolsillo || 0) },
    { label: "Revista", value: `${liquidation.revista?.diasTrabajados || 0}/${liquidation.revista?.diasPeriodo || 30}` },
    { label: "Score preventivo", value: `${audit?.score ?? 100}/100` },
    { label: "Estado auditoria", value: audit?.estado || "OK" }
  ]
    .map(
      (item) => `
        <article class="summary-card">
          <span>${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.value)}</strong>
        </article>
      `
    )
    .join("");

  refs.skillStepList.innerHTML = "";
  (liquidation.metadata?.steps || []).forEach((step, index) => {
    const article = document.createElement("article");
    article.className = "skill-step-card";
    article.innerHTML = `
      <div class="step-topline">
        <span class="type-badge badge-info">Paso ${index + 1}</span>
        <strong>${escapeHtml(step.label || "Paso")}</strong>
      </div>
      <p>${escapeHtml(step.formula || "Sin formula")}</p>
      ${step.detail ? `<small>${escapeHtml(step.detail)}</small>` : ""}
      <strong>${escapeHtml(formatCurrency(step.amount || 0))}</strong>
    `;
    refs.skillStepList.append(article);
  });

  refs.skillFormulaList.innerHTML = "";
  liquidation.conceptos.forEach((concept) => {
    const article = document.createElement("article");
    article.className = "skill-formula-card";
    article.innerHTML = `
      <strong>${escapeHtml(concept.descripcion)}</strong>
      <p>${escapeHtml(concept.formula || "Sin formula declarada")}</p>
      <small>Serie ${escapeHtml(concept.serie || "s/d")} · AFIP ${escapeHtml(concept.codigo_afip || "s/d")}</small>
    `;
    refs.skillFormulaList.append(article);
  });

  refs.skillObservationList.innerHTML = "";
  if (!observations.length) {
    refs.skillObservationList.innerHTML = '<div class="skill-empty">No se detectaron observaciones adicionales.</div>';
  } else {
    observations.forEach((item) => {
      const article = document.createElement("article");
      article.className = "skill-observation-card";
      article.innerHTML = `
        <strong>${escapeHtml(item.type)}</strong>
        <p>${escapeHtml(item.text)}</p>
      `;
      refs.skillObservationList.append(article);
    });
  }
}

function openSkillModal(refs) {
  if (!appState.latestLiquidation) return;
  renderSkillModal(refs);
  refs.skillModal.classList.add("is-open");
  refs.skillModal.setAttribute("aria-hidden", "false");
}

function closeSkillModal(refs) {
  refs.skillModal.classList.remove("is-open");
  refs.skillModal.setAttribute("aria-hidden", "true");
}

function renderResult(refs, liquidation, audit) {
  if (!liquidation) {
    refs.grossRem.textContent = formatCurrency(0);
    refs.deductionsTotal.textContent = formatCurrency(0);
    refs.nonRemTotal.textContent = formatCurrency(0);
    refs.takeHomeTotal.textContent = formatCurrency(0);
    refs.hourValue.textContent = formatCurrency(0);
    refs.socialBase.textContent = formatCurrency(0);
    refs.healthBase.textContent = formatCurrency(0);
    refs.discountRate.textContent = formatPercent(0);
    refs.explainButton.disabled = true;
    renderRows(refs.remunerativeBreakdown, []);
    renderRows(refs.deductionsBreakdown, []);
    renderRows(refs.nonRemBreakdown, []);
    renderRows(refs.contextBreakdown, []);
    renderSteps(refs.stepByStep, []);
    renderSteps(refs.debugSteps, []);
    refs.explanationText.innerHTML = "<p>Sin liquidacion calculada.</p>";
    renderReceipt(refs, null);
    renderSourcesPanel(refs, null);
    renderAuditIdle(refs);
    renderMatrixPanel(refs, null, null);
    renderToolboxContext(refs);
    renderSimulator(refs, null);
    renderComparator(refs, null);
    renderDistribution(refs, null);
    renderEmployerCost(refs, null);
    return;
  }

  const view = buildViewModel(liquidation);
  const values = view.values;
  const discountRate = (liquidation.totales?.remunerativo || 0) > 0
    ? (liquidation.totales.descuentos || 0) / liquidation.totales.remunerativo
    : 0;

  refs.explainButton.disabled = false;
  refs.debugBox.open = Boolean(view.input.debugMode);
  refs.grossRem.textContent = formatCurrency(liquidation.totales?.remunerativo || 0);
  refs.deductionsTotal.textContent = formatCurrency(liquidation.totales?.descuentos || 0);
  refs.nonRemTotal.textContent = formatCurrency(liquidation.totales?.noRemunerativo || 0);
  refs.takeHomeTotal.textContent = formatCurrency(liquidation.totales?.bolsillo || 0);
  refs.hourValue.textContent = formatCurrency(liquidation.bases?.valorHora || 0);
  refs.socialBase.textContent = formatCurrency(liquidation.bases?.seguridadSocial || 0);
  refs.healthBase.textContent = formatCurrency(liquidation.bases?.obraSocialSindicato || 0);
  refs.discountRate.textContent = formatPercent(discountRate);

  const remunerativeRows = [
    { label: "Basico convenio", amount: view.type === "vacaciones" ? values.grossRemunerative : values.basicProportional },
    { label: "Antiguedad", amount: values.seniority },
    { label: "Presentismo", amount: values.presentismo },
    { label: "Zona desfavorable", amount: values.zone },
    { label: "Horas extra 50%", amount: values.overtime50 },
    { label: "Horas extra 100%", amount: values.overtime100 }
  ];

  if (view.type === "final") {
    remunerativeRows.push(
      { label: "SAC proporcional", amount: values.sacProportional },
      { label: "Vacaciones no gozadas", amount: values.unusedVacation },
      { label: "SAC s/vacaciones no gozadas", amount: values.sacOnUnusedVacation }
    );
  }

  remunerativeRows.push({ label: "Bruto remunerativo", amount: values.grossRemunerative });

  renderRows(refs.remunerativeBreakdown, remunerativeRows);
  renderRows(refs.deductionsBreakdown, [
    { label: "Jubilacion (11%)", amount: values.deductions?.retirement },
    { label: "PAMI (3%)", amount: values.deductions?.pami },
    { label: "Obra social", amount: values.deductions?.health },
    { label: "Sindicato", amount: values.deductions?.union, note: view.input.applyUnion ? "Activo" : "Desactivado" },
    { label: "Total descuentos", amount: values.totalDeductions }
  ]);
  renderRows(
    refs.nonRemBreakdown,
    view.nonRemConcepts.length
      ? [
          ...view.nonRemConcepts.map((item) => ({ label: item.label, amount: item.subtotal, note: item.note })),
          { label: "Total no remunerativo", amount: values.nonRemunerativeTotal }
        ]
      : [{ label: "Sin acuerdos activos", amount: 0, note: "No se liquidaron conceptos no remunerativos para la fecha elegida." }]
  );
  renderRows(refs.contextBreakdown, [
    { label: "Categoria", valueText: view.category.label || "Sin categoria", note: view.category.payBasis === "hourly" ? "Categoria jornalizada / valor hora" : "Categoria mensualizada" },
    { label: "Escala aplicada", valueText: view.scale.label || "Sin escala" },
    { label: "Tipo de liquidacion", valueText: view.type },
    { label: "Fecha de liquidacion", valueText: formatDate(view.input.liquidationDate) },
    { label: "Equivalente mensual", amount: view.monthlyEquivalent }
  ]);

  refs.explanationText.innerHTML = `<p>${escapeHtml(buildExplanationText(liquidation))}</p>`;
  renderSteps(refs.stepByStep, view.steps);
  renderSteps(refs.debugSteps, buildDebugSteps(liquidation, audit));
  renderToolboxContext(refs);
  renderSimulator(refs, liquidation);
  renderComparator(refs, liquidation);
  renderReceipt(refs, liquidation);
  renderSourcesPanel(refs, liquidation);
  renderDistribution(refs, liquidation);
  renderEmployerCost(refs, liquidation);
  renderMatrixPanel(refs, liquidation, audit);
  renderAudit(refs, audit, liquidation, appState.catalogs || buildEmptyCatalogs());
  switchResultTab(refs, "summary");
}

async function refreshGeminiHealth(refs) {
  if (!refs.auditAiRun || !refs.auditAiStatus) return;

  try {
    const payload = await geminiClient.health();
    appState.aiAvailable = Boolean(payload.ai_enabled);
    refs.auditAiRun.disabled = !appState.aiAvailable;
    refs.auditAiStatus.innerHTML = appState.aiAvailable
      ? `<strong>Gemini disponible.</strong><p>Modelo: ${escapeHtml(payload.model || "sin-modelo")}.</p>`
      : "<strong>Gemini no configurado.</strong><p>Defini GEMINI_API_KEY en el backend para habilitar revision experta opcional.</p>";
  } catch (error) {
    appState.aiAvailable = false;
    refs.auditAiRun.disabled = true;
    refs.auditAiStatus.innerHTML = "<strong>Backend no disponible.</strong><p>Levanta el proxy local para habilitar la capa Gemini opcional.</p>";
  }
}

async function requestGeminiReview(refs) {
  if (!appState.latestAudit) {
    toast(refs, "Todavia no hay una liquidacion auditada.", "warn", "Auditor IA");
    return;
  }

  if (!appState.aiAvailable) {
    toast(refs, "Gemini no esta disponible en este runtime.", "warn", "Auditor IA");
    return;
  }

  refs.auditAiOutput.hidden = false;
  refs.auditAiOutput.textContent = "Generando revision experta...";

  try {
    const payload = await geminiClient.audit(appState.latestAudit.resumenIA);
    appState.latestAiText = payload.text || "Gemini no devolvio contenido.";
    refs.auditAiOutput.textContent = appState.latestAiText;
  } catch (error) {
    refs.auditAiOutput.textContent = `No se pudo consultar Gemini: ${error.message}`;
  }
}

function shouldAutoPreview(refs) {
  return refs.form?.elements?.previewAudit?.checked ?? true;
}

function moveToStep(refs, stepKey) {
  const targetIndex = stepIndex(stepKey);
  if (targetIndex >= stepIndex("audit")) {
    run(refs, { silent: true });
    if (!appState.latestLiquidation) return;
  }
  switchWizardStep(refs, stepKey);
}

function run(refs, { silent = false } = {}) {
  try {
    const input = collectInput(refs);
    const liquidation = calculateLiquidation(input);
    const audit = ejecutarAuditoria(liquidation, appState.catalogs || buildEmptyCatalogs());
    appState.latestInput = input;
    appState.latestLiquidation = liquidation;
    appState.latestAudit = audit;
    appState.isDirty = false;
    renderResult(refs, liquidation, audit);
    updateContextKpis(refs);
    persistWizardState(refs);

    const messageItems = [
      ...(liquidation.metadata?.warnings || []).map((warning) => ({
        type: "warning",
        title: "Advertencia de configuracion",
        body: warning
      }))
    ];

    if (audit.estado === "BLOCKED") {
      messageItems.unshift({
        type: "blocker",
        title: "Exportacion observada",
        body: "El motor preventivo detecto inconsistencias bloqueantes sobre la liquidacion terminada."
      });
    } else if (audit.estado === "WARNING" || audit.estado === "CRITICAL") {
      messageItems.unshift({
        type: "warning",
        title: "Revision preventiva",
        body: "La liquidacion calculo bien sus montos base, pero la auditoria encontro observaciones a revisar."
      });
    }

    renderMessages(refs, messageItems);
    refs.auditAiOutput.hidden = true;
    refs.auditAiOutput.textContent = "";

    if (!silent) {
      toast(refs, "La liquidacion se recalculo y la auditoria preventiva corrio sobre el objeto final.", "ok", "Liquidacion calculada");
    }

    document.dispatchEvent(
      new CustomEvent("cct244:result-rendered", {
        detail: {
          liquidacion: liquidation,
          auditoria: audit
        }
      })
    );
  } catch (error) {
    appState.latestInput = null;
    appState.latestLiquidation = null;
    appState.latestAudit = null;
    appState.isDirty = true;
    renderResult(refs, null, null);
    renderMessages(refs, [
      {
        type: "blocker",
        title: "No se pudo calcular",
        body: error.message || "Error inesperado en el motor de liquidacion."
      }
    ]);
    toast(refs, "Corregi los datos de entrada para volver a calcular.", "warn", "Liquidacion no calculada");
  }
}

function resetForm(refs) {
  refs.form.elements.liquidationDate.value = getTodayString();
  refs.form.elements.liquidationType.value = "mensual";
  refs.form.elements.seniorityYears.value = 0;
  refs.form.elements.seniorityMonths.value = 0;
  refs.form.elements.jornadaCoefficient.value = 1;
  refs.form.elements.liquidationMode.value = "normal";
  refs.form.elements.workedDays.value = 30;
  refs.form.elements.overtime50Hours.value = 0;
  refs.form.elements.overtime100Hours.value = 0;
  refs.form.elements.licensedDays.value = 0;
  refs.form.elements.suspensionDays.value = 0;
  refs.form.elements.absenceDays.value = 0;
  refs.form.elements.vacationDays.value = 14;
  refs.form.elements.unusedVacationDays.value = 0;
  refs.form.elements.semesterDaysWorked.value = 90;
  refs.form.elements.zoneUnfavorable.checked = false;
  refs.form.elements.nightShift.checked = false;
  refs.form.elements.includeNonRemuneratives.checked = true;
  refs.form.elements.presentismo.checked = false;
  refs.form.elements.applyUnion.checked = true;
  refs.form.elements.previewAudit.checked = true;
  refs.form.elements.persistWizardState.checked = true;
  refs.form.elements.debugMode.checked = false;
  if (refs.simMonthsInput) refs.simMonthsInput.value = 6;
  if (refs.simRemPercentInput) refs.simRemPercentInput.value = 2;
  if (refs.simNrPercentInput) refs.simNrPercentInput.value = 1;
  [1, 2, 3].forEach((index) => {
    refs.form.elements[`revistaSegment${index}Code`].value = "";
    refs.form.elements[`revistaSegment${index}From`].value = "";
    refs.form.elements[`revistaSegment${index}To`].value = "";
  });
  renderCategoryOptions(refs);
  renderAgreementControls(refs);
  renderScaleDeck(refs, refs.dateInput.value);
  renderAgreementDeck(refs, refs.dateInput.value);
  updateConditionalFields(refs);
  updateContextKpis(refs);
  renderToolboxContext(refs);
  appState.currentStep = "general";
  switchWizardStep(refs, "general", { shouldScroll: false });
  run(refs, { silent: true });
}

function bindEvents(refs) {
  refs.dateInput.addEventListener("change", () => {
    renderCategoryOptions(refs);
    renderAgreementControls(refs);
    renderScaleDeck(refs, refs.dateInput.value);
    renderAgreementDeck(refs, refs.dateInput.value);
    if (shouldAutoPreview(refs)) {
      run(refs, { silent: true });
    } else {
      appState.isDirty = true;
      updateContextKpis(refs);
      persistWizardState(refs);
    }
  });

  refs.typeInput.addEventListener("change", () => {
    updateConditionalFields(refs);
    renderToolboxContext(refs);
    if (shouldAutoPreview(refs)) {
      run(refs, { silent: true });
    } else {
      appState.isDirty = true;
      persistWizardState(refs);
    }
  });

  refs.form.addEventListener("input", (event) => {
    updateContextKpis(refs);
    renderToolboxContext(refs);
    if (event.target.name && event.target.name.startsWith("agreement-")) {
      if (shouldAutoPreview(refs)) {
        run(refs, { silent: true });
      } else {
        appState.isDirty = true;
        persistWizardState(refs);
      }
      return;
    }
    if (shouldAutoPreview(refs)) {
      run(refs, { silent: true });
    } else {
      appState.isDirty = true;
      persistWizardState(refs);
    }
  });

  refs.form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(refs);
    if (appState.latestLiquidation) {
      switchWizardStep(refs, "audit");
    }
  });

  refs.wizardStepButtons.forEach((button) => {
    button.addEventListener("click", () => moveToStep(refs, button.dataset.wizardStep));
  });

  refs.wizardNextButtons.forEach((button) => {
    button.addEventListener("click", () => moveToStep(refs, button.dataset.wizardNext));
  });

  refs.wizardPrevButtons.forEach((button) => {
    button.addEventListener("click", () => switchWizardStep(refs, button.dataset.wizardPrev));
  });

  refs.resultTabs.forEach((button) => {
    button.addEventListener("click", () => switchResultTab(refs, button.dataset.resultTab));
  });

  refs.runSimButton?.addEventListener("click", () => renderSimulator(refs));
  refs.runCompareButton?.addEventListener("click", () => renderComparator(refs));
  refs.compareCategoryLeft?.addEventListener("change", () => renderComparator(refs));
  refs.compareCategoryRight?.addEventListener("change", () => renderComparator(refs));
  [refs.simMonthsInput, refs.simRemPercentInput, refs.simNrPercentInput]
    .filter(Boolean)
    .forEach((field) => field.addEventListener("input", () => renderSimulator(refs)));

  refs.resetButton.addEventListener("click", () => {
    resetForm(refs);
    toast(refs, "Se volvio al caso base y se recalculo la liquidacion inicial.", "ok", "Nueva simulacion");
  });

  refs.explainButton.addEventListener("click", () => openSkillModal(refs));
  refs.closeSkillButton.addEventListener("click", () => closeSkillModal(refs));
  refs.skillModal.addEventListener("click", (event) => {
    if (event.target.dataset.closeSkill === "true") {
      closeSkillModal(refs);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && refs.skillModal.classList.contains("is-open")) {
      closeSkillModal(refs);
    }
  });

  refs.auditAiRun?.addEventListener("click", () => requestGeminiReview(refs));
  refs.printButton?.addEventListener("click", () => window.print());
  refs.printResultButton?.addEventListener("click", () => window.print());
}

async function bootstrap() {
  const refs = createRefs();
  if (!refs.form) return;

  try {
    appState.catalogs = await loadCatalogs();
  } catch (error) {
    appState.catalogs = buildEmptyCatalogs();
    toast(refs, "No se pudieron cargar los catalogos JSON. El motor sigue, pero con auditoria parcial.", "warn", "Catalogos");
  }

  bindEvents(refs);
  const persistedState = readPersistedState();
  if (persistedState?.input) {
    resetForm(refs);
    applyPersistedInput(refs, persistedState.input);
    appState.currentStep = persistedState.currentStep || "general";
    switchWizardStep(refs, appState.currentStep, { shouldScroll: false });
    run(refs, { silent: true });
  } else {
    resetForm(refs);
  }
  refreshGeminiHealth(refs);
  updateWizardProgress(refs, appState.currentStep);

  window.__cct244CalculatorContext = {
    convention,
    formatCurrency,
    roundMoney,
    numberOrZero,
    toast: (message, type, title) => toast(refs, message, type, title),
    getLatestCalculationResult: () => appState.latestLiquidation,
    getLatestAuditResult: () => appState.latestAudit
  };

  document.dispatchEvent(new CustomEvent("cct244:ready"));
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPayrollChatBox);
} else {
  initPayrollChatBox();
}
