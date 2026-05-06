import { PreventiveAuditService } from "./auditor.js";
import { escapeHtml, formatCurrency, hasHttpRuntime, roundMoney } from "./utils.js";

const SOURCE_NOTES = [
  {
    title: "AFIP - Conceptos basicos y guia de uso LSD",
    body:
      "Base documental para conceptos fijos, rangos libres y tratamiento de conceptos remunerativos, no remunerativos y descuentos.",
    url: "https://www.afip.gob.ar/librodesueldosdigital/documentos/nuevos/LS_Conceptos_Basicos_y_Guia_de_Uso_V2.0.pdf"
  },
  {
    title: "AFIP - Situacion de revista y errores frecuentes",
    body:
      "La ayuda oficial remarca que solo se informan hasta tres situaciones por periodo y que la situacion general debe coincidir con el ultimo tramo.",
    url: "https://serviciosweb.afip.gob.ar/genericos/guiasPasoPaso/VerGuia.aspx?id=433"
  },
  {
    title: "CCT 244/94 - Art. 11",
    body:
      "Mensualizacion del salario obrero en base a 25 dias o 200 horas. Se usa como soporte para controles de proporcionalidad y jornada.",
    url: ""
  },
  {
    title: "CCT 244/94 - Arts. 27 y 30",
    body:
      "Soportan la separacion de conceptos y el control mensual sobre retenciones y aportes, utiles para conciliacion interna.",
    url: ""
  }
];

function notify(context, message, type = "ok", title = "Auditor") {
  if (typeof context.toast === "function") {
    context.toast(message, type, title);
    return;
  }
  console.info(title, message);
}

function buildPayloadFromCurrentLiquidation(result) {
  if (!result?.values || !result?.input) return null;

  const workedDays = Math.min(30, Math.max(0, Math.trunc(result.input.workedDays || 30)));
  const payload = {
    periodo: String(result.input.liquidationDate || "").slice(0, 7),
    dias_periodo: 30,
    situacion_general: "01",
    coeficiente_jornada: 1,
    dias_trabajados_f931: workedDays,
    horas_trabajadas_f931: 0,
    totalizadores: {
      "993": roundMoney(result.values.grossRemunerative || 0),
      "994": roundMoney(result.values.nonRemunerativeTotal || 0),
      "995": roundMoney(result.values.totalDeductions || 0),
      "996": roundMoney(result.values.totalPocket || 0),
      "997": 0,
      neto_impreso: roundMoney(result.values.totalPocket || 0)
    },
    revista: [
      {
        codigo: "01",
        etiqueta: "Activo",
        desde: 1,
        hasta: workedDays || 30
      }
    ],
    conceptos: []
  };

  if (workedDays > 0 && workedDays < 30) {
    payload.revista.push({
      codigo: "",
      etiqueta: "Completar tramo restante",
      desde: workedDays + 1,
      hasta: 30
    });
  }

  const addConcept = (descripcion, importe, serie, lado, codigoAfip, formula, usaAuxiliarA = false) => {
    if (!roundMoney(importe)) return;
    payload.conceptos.push({
      descripcion,
      importe: roundMoney(importe),
      serie,
      lado,
      codigo_afip: codigoAfip,
      formula,
      usa_auxiliar_a: usaAuxiliarA
    });
  };

  addConcept("Basico convenio", result.values.basicProportional || result.values.grossRemunerative, "993", "haber", "110000", "BASICO_MENSUAL / 30 * DIAS_TRABAJADOS * AUXILIAR_A", true);
  addConcept("Adicional por antiguedad", result.values.seniority, "993", "haber", "160001", "BASICO_PROPORCIONAL * PORCENTAJE_ANTIGUEDAD * AUXILIAR_A", true);
  addConcept("Zona desfavorable", result.values.zone, "993", "haber", "140000", "BASICO_PROPORCIONAL * PORCENTAJE_ZONA * AUXILIAR_A", true);
  addConcept("Horas extras al 50", result.values.overtime50, "993", "haber", "130001", "VALOR_HORA * HORAS_50 * 1.5");
  addConcept("Horas extras al 100", result.values.overtime100, "993", "haber", "130002", "VALOR_HORA * HORAS_100 * 2");
  addConcept("SAC proporcional", result.values.sacProportional, "993", "haber", "120003", "BASE_SAC / 12 * DIAS_SEMESTRE / 180");
  addConcept("Vacaciones no gozadas", result.values.unusedVacation, "994", "haber", "520012", "BASE_VACACIONES / 25 * DIAS_NO_GOZADOS");

  (result.nonRemConcepts || []).forEach((concept) => {
    addConcept(
      concept.label || "Acuerdo no remunerativo",
      concept.subtotal,
      "994",
      "haber",
      "531000",
      concept.runtime?.prorateByDays ? "MONTO_ACUERDO * DIAS_TRABAJADOS / 30" : "MONTO_ACUERDO"
    );
  });

  addConcept("Aporte jubilacion 11%", result.values.deductions?.retirement, "995", "descuento", "810000", "BASE_JUBILACION * 0.11");
  addConcept("PAMI", result.values.deductions?.pami, "995", "descuento", "810001", "BASE_JUBILACION * 0.03");
  addConcept("Obra social", result.values.deductions?.health, "995", "descuento", "810002", "BASE_OS * 0.03");
  addConcept("Cuota sindical", result.values.deductions?.union, "995", "descuento", "810004", "BASE_SINDICATO * 0.02");

  return payload;
}

function renderSources(refs, catalogs) {
  refs.sources.innerHTML = "";
  SOURCE_NOTES.forEach((source) => {
    const article = document.createElement("article");
    article.innerHTML = source.url
      ? `<strong><a href="${source.url}" target="_blank" rel="noopener">${escapeHtml(source.title)}</a></strong><p>${escapeHtml(source.body)}</p>`
      : `<strong>${escapeHtml(source.title)}</strong><p>${escapeHtml(source.body)}</p>`;
    refs.sources.append(article);
  });

  const versions = document.createElement("article");
  versions.innerHTML = `
    <strong>Versionado local</strong>
    <p>
      conceptos ${escapeHtml(catalogs.metadata.conceptosVersion)} ·
      reglas ${escapeHtml(catalogs.metadata.reglasVersion)} ·
      AFIP ${escapeHtml(catalogs.metadata.mapeoVersion)} ·
      formulas ${escapeHtml(catalogs.metadata.formulasVersion)} ·
      convenio ${escapeHtml(catalogs.metadata.convenioVersion)}
    </p>
  `;
  refs.sources.append(versions);
}

function renderIdle(refs, message = "Esperando una liquidacion valida para auditar.") {
  if (refs.box) {
    refs.box.open = true;
  }
  refs.exportCard.classList.remove("is-blocked");
  refs.exportCard.classList.add("is-ready");
  refs.exportStatus.textContent = "Esperando liquidacion";
  refs.exportCaption.textContent = message;
  refs.score.textContent = "--/100";
  refs.scoreCaption.textContent = "Sin evaluacion todavia.";
  refs.netGap.textContent = formatCurrency(0, null);
  refs.netGapCaption.textContent = "996 vs neto reconstruido.";
  refs.coveredDays.textContent = "0 / 30";
  refs.coveredCaption.textContent = "Sin datos todavia.";
  refs.findings.innerHTML = `
    <article class="audit-empty">
      <strong>Motor listo.</strong>
      <p>${escapeHtml(message)}</p>
    </article>
  `;
}

function renderFindings(refs, result) {
  refs.findings.innerHTML = "";
  if (!result.findings.length) {
    refs.findings.innerHTML = `
      <article class="audit-empty">
        <strong>Sin observaciones criticas.</strong>
        <p>La liquidacion quedo consistente contra las reglas deterministicas cargadas.</p>
      </article>
    `;
    return;
  }

  result.findings.forEach((finding) => {
    const article = document.createElement("article");
    article.className = `audit-finding is-${finding.severity}`;
    article.innerHTML = `
      <strong>${escapeHtml(finding.title)}</strong>
      <small>${escapeHtml((finding.domain || "general").toUpperCase())} · ${escapeHtml(finding.code)}</small>
      <p>${escapeHtml(finding.message)}</p>
    `;
    refs.findings.append(article);
  });
}

function renderSummary(refs, context, result) {
  const formatter = context.formatCurrency;
  if (refs.box) {
    refs.box.open = result.summary.blocked || result.summary.counters.warning > 0;
  }
  refs.score.textContent = `${result.summary.score}/100`;
  refs.scoreCaption.textContent = `${result.summary.counters.error} errores · ${result.summary.counters.warning} advertencias`;
  refs.netGap.textContent = formatCurrency(result.facts.totalizers.receiptVs996Gap, formatter);
  refs.netGapCaption.textContent = `Neto impreso ${formatCurrency(result.payload.totalizadores.neto_impreso, formatter)} vs 996 ${formatCurrency(result.payload.totalizadores["996"], formatter)}`;
  refs.coveredDays.textContent = `${result.facts.revista.coveredDays} / ${result.payload.dias_periodo}`;
  refs.coveredCaption.textContent = `${result.facts.revista.segmentCount} tramos auditados`;
  refs.exportCard.classList.toggle("is-blocked", result.summary.blocked);
  refs.exportCard.classList.toggle("is-ready", !result.summary.blocked);
  refs.exportStatus.textContent = result.summary.blocked
    ? "Bloquear exportacion"
    : result.summary.status === "revisar"
      ? "Revisar antes de cerrar"
      : "Apto";
  refs.exportCaption.textContent = result.summary.blocked
    ? "Se detectaron reglas bloqueantes previas al cierre/exportacion."
    : result.summary.status === "revisar"
      ? "No hay bloqueo automatico, pero existen advertencias preventivas."
      : "No se detectaron inconsistencias deterministicas.";
}

export function mountAuditorUI({ context, catalogs }) {
  const refs = {
    box: document.querySelector("#auto-audit-box"),
    exportCard: document.querySelector("#audit-export-card"),
    exportStatus: document.querySelector("#audit-export-status"),
    exportCaption: document.querySelector("#audit-export-caption"),
    score: document.querySelector("#audit-score"),
    scoreCaption: document.querySelector("#audit-score-caption"),
    netGap: document.querySelector("#audit-net-gap"),
    netGapCaption: document.querySelector("#audit-net-gap-caption"),
    coveredDays: document.querySelector("#audit-covered-days"),
    coveredCaption: document.querySelector("#audit-covered-caption"),
    findings: document.querySelector("#audit-findings"),
    sources: document.querySelector("#audit-sources"),
    aiButton: document.querySelector("#audit-ai-run"),
    aiStatus: document.querySelector("#audit-ai-status"),
    aiOutput: document.querySelector("#audit-ai-output")
  };

  if (!refs.findings) return;

  const service = new PreventiveAuditService(catalogs);
  let lastResult = null;
  let aiEnabled = false;
  let previousBlockedState = null;

  function auditLiquidation(liquidationResult) {
    const payload = buildPayloadFromCurrentLiquidation(liquidationResult);
    if (!payload) {
      lastResult = null;
      previousBlockedState = null;
      renderIdle(refs);
      context.getPreventiveAuditResult = () => null;
      return null;
    }

    lastResult = service.audit(payload);
    renderSummary(refs, context, lastResult);
    renderFindings(refs, lastResult);

    if (previousBlockedState !== lastResult.summary.blocked) {
      if (lastResult.summary.blocked) {
        notify(context, "La auditoria preventiva detecto bloqueos antes del cierre.", "warn", "Auditor preventivo");
      } else if (previousBlockedState === true && !lastResult.summary.blocked) {
        notify(context, "La liquidacion volvio a quedar apta segun el auditor preventivo.", "ok", "Auditor preventivo");
      }
    }

    previousBlockedState = lastResult.summary.blocked;
    context.getPreventiveAuditResult = () => lastResult;
    return lastResult;
  }

  async function refreshAiHealth() {
    if (!hasHttpRuntime()) {
      refs.aiButton.disabled = true;
      return;
    }

    try {
      const response = await fetch("/health", { cache: "no-store" });
      if (!response.ok) throw new Error("Health check no disponible");
      const payload = await response.json();
      aiEnabled = Boolean(payload.ai_enabled);
      refs.aiButton.disabled = !aiEnabled;
      refs.aiStatus.innerHTML = aiEnabled
        ? `<strong>Gemini disponible.</strong><p>Modelo: ${escapeHtml(payload.model || "sin-modelo")}.</p>`
        : `<strong>Gemini no configurado.</strong><p>Defini GEMINI_API_KEY en el backend para habilitar revision experta opcional.</p>`;
    } catch (error) {
      aiEnabled = false;
      refs.aiButton.disabled = true;
      refs.aiStatus.innerHTML = `<strong>Backend no disponible.</strong><p>Servi la app con FastAPI o con el servidor local para habilitar la capa Gemini.</p>`;
    }
  }

  async function requestGeminiAudit() {
    if (!lastResult) {
      notify(context, "Todavia no hay una liquidacion auditada.", "warn", "Auditor IA");
      return;
    }
    if (!aiEnabled) {
      notify(context, "Gemini no esta disponible en este runtime.", "warn", "Auditor IA");
      return;
    }

    refs.aiOutput.hidden = false;
    refs.aiOutput.textContent = "Generando revision experta...";

    try {
      const response = await fetch("/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(lastResult.geminiPayload)
      });

      if (!response.ok) {
        throw new Error(`Error ${response.status}`);
      }

      const payload = await response.json();
      refs.aiOutput.textContent = payload.text || "Gemini no devolvio contenido.";
    } catch (error) {
      refs.aiOutput.textContent = `No se pudo consultar Gemini: ${error.message}`;
    }
  }

  document.addEventListener("cct244:result-rendered", (event) => {
    auditLiquidation(event.detail?.result || null);
  });

  refs.aiButton?.addEventListener("click", requestGeminiAudit);
  renderSources(refs, catalogs);
  renderIdle(refs, "El auditor se ejecuta automaticamente con cada liquidacion.");
  auditLiquidation(context.getLatestCalculationResult?.());
  refreshAiHealth();
}
