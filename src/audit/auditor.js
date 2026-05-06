import { analyzeAfipMapping } from "./afip.js";
import { computeSeriesDifferences, RuleEngine } from "./reglas.js";
import { bySeverity, cloneJson, roundMoney, toNumber } from "./utils.js";

function sanitizeRevista(items) {
  return (items || [])
    .map((item) => ({
      codigo: String(item.codigo || "").trim(),
      etiqueta: String(item.etiqueta || "").trim(),
      desde: Math.max(0, Math.trunc(toNumber(item.desde))),
      hasta: Math.max(0, Math.trunc(toNumber(item.hasta)))
    }))
    .filter((item) => item.codigo || item.etiqueta || item.desde || item.hasta)
    .sort((left, right) => left.desde - right.desde);
}

function sanitizeConcepts(items) {
  return (items || [])
    .map((item) => ({
      descripcion: String(item.descripcion || "").trim(),
      importe: roundMoney(item.importe),
      serie: String(item.serie || "sin_tanque").trim() || "sin_tanque",
      lado: item.lado === "descuento" ? "descuento" : "haber",
      codigo_afip: String(item.codigo_afip || "").trim(),
      formula: String(item.formula || "").trim(),
      usa_auxiliar_a: Boolean(item.usa_auxiliar_a)
    }))
    .filter((item) => item.descripcion);
}

function buildRevistaFacts(payload) {
  const segments = sanitizeRevista(payload.revista);
  const gaps = [];
  const overlaps = [];
  let coveredDays = 0;
  let previousEnd = 0;

  segments.forEach((segment) => {
    if (segment.hasta >= segment.desde && segment.desde > 0) {
      coveredDays += segment.hasta - segment.desde + 1;
    }

    if (segment.desde <= previousEnd && previousEnd > 0) {
      overlaps.push(`${segment.codigo || "??"} (${segment.desde}-${segment.hasta})`);
    } else if (segment.desde > previousEnd + 1 && previousEnd > 0) {
      gaps.push(`${previousEnd + 1}-${segment.desde - 1}`);
    } else if (previousEnd === 0 && segment.desde > 1) {
      gaps.push(`1-${segment.desde - 1}`);
    }

    previousEnd = Math.max(previousEnd, segment.hasta);
  });

  if (previousEnd > 0 && previousEnd < payload.dias_periodo) {
    gaps.push(`${previousEnd + 1}-${payload.dias_periodo}`);
  }

  return {
    segments,
    segmentCount: segments.length,
    coveredDays,
    gaps,
    overlaps,
    lastCode: segments.length ? segments[segments.length - 1].codigo : ""
  };
}

function buildFormulaFacts(payload, afipAnalysis) {
  const missingAuxiliarA = afipAnalysis.concepts.filter((concept) => {
    if (payload.coeficiente_jornada >= 1) return false;
    if (!concept.requiresAuxiliarA) return false;
    if (concept.lado === "descuento") return false;
    const mentionsAuxiliarA = /aux(\s*iliar)?[_\s-]*a|coeficiente|jornada|l\/8/i.test(concept.formula);
    return !mentionsAuxiliarA;
  });

  return { missingAuxiliarA };
}

function buildTotalizerFacts(payload, afipAnalysis) {
  const totals = payload.totalizadores;
  const rebuiltNet = roundMoney(totals["993"] + totals["994"] + totals["997"] - totals["995"]);
  const differencesBySeries = computeSeriesDifferences(totals, afipAnalysis.totalsFromConcepts);

  return {
    rebuiltNet,
    differencesBySeries,
    hasConceptBreakdown: afipAnalysis.concepts.length > 0,
    orphanAmount: afipAnalysis.orphanAmount,
    orphanConceptCount: afipAnalysis.concepts.filter((item) => item.serie === "sin_tanque").length,
    receiptNetFromConcepts: afipAnalysis.receiptNetFromConcepts,
    receiptVs996Gap: roundMoney(payload.totalizadores.neto_impreso - totals["996"])
  };
}

function summarize(findings) {
  const counters = {
    error: findings.filter((item) => item.severity === "error").length,
    warning: findings.filter((item) => item.severity === "warning").length,
    info: findings.filter((item) => item.severity === "info").length
  };

  const score = Math.max(0, 100 - counters.error * 22 - counters.warning * 8 - counters.info * 2);
  return {
    counters,
    score,
    blocked: findings.some((item) => item.blocksExport),
    status: counters.error ? "bloqueado" : counters.warning ? "revisar" : "ok"
  };
}

export function sanitizePayload(rawPayload) {
  return {
    periodo: String(rawPayload?.periodo || ""),
    dias_periodo: Math.max(1, Math.trunc(toNumber(rawPayload?.dias_periodo || 30))),
    situacion_general: String(rawPayload?.situacion_general || "").trim(),
    coeficiente_jornada: roundMoney(rawPayload?.coeficiente_jornada || 1),
    dias_trabajados_f931: Math.max(0, Math.trunc(toNumber(rawPayload?.dias_trabajados_f931 || 0))),
    horas_trabajadas_f931: Math.max(0, Math.trunc(toNumber(rawPayload?.horas_trabajadas_f931 || 0))),
    totalizadores: {
      "993": roundMoney(rawPayload?.totalizadores?.["993"] || 0),
      "994": roundMoney(rawPayload?.totalizadores?.["994"] || 0),
      "995": roundMoney(rawPayload?.totalizadores?.["995"] || 0),
      "996": roundMoney(rawPayload?.totalizadores?.["996"] || 0),
      "997": roundMoney(rawPayload?.totalizadores?.["997"] || 0),
      neto_impreso: roundMoney(rawPayload?.totalizadores?.neto_impreso || 0)
    },
    revista: sanitizeRevista(rawPayload?.revista),
    conceptos: sanitizeConcepts(rawPayload?.conceptos)
  };
}

export class PreventiveAuditService {
  constructor(catalogs) {
    this.catalogs = catalogs;
    this.ruleEngine = new RuleEngine(catalogs.reglas);
  }

  audit(rawPayload) {
    const payload = sanitizePayload(cloneJson(rawPayload));
    const afipAnalysis = analyzeAfipMapping(payload.conceptos, this.catalogs);
    const facts = {
      revista: buildRevistaFacts(payload),
      totalizers: buildTotalizerFacts(payload, afipAnalysis),
      formulas: buildFormulaFacts(payload, afipAnalysis),
      afipFindings: afipAnalysis.findings,
      afipConcepts: afipAnalysis.concepts
    };

    const ruleFindings = this.ruleEngine.evaluate({ payload, facts, catalogs: this.catalogs });
    const allFindings = [...ruleFindings, ...afipAnalysis.findings].sort(bySeverity);
    const summary = summarize(allFindings);

    return {
      payload,
      facts,
      summary,
      findings: allFindings,
      geminiPayload: {
        periodo: payload.periodo,
        resumen_totalizadores: payload.totalizadores,
        resumen_revista: {
          dias_periodo: payload.dias_periodo,
          tramos: payload.revista.length,
          situacion_general: payload.situacion_general,
          ultimo_tramo: facts.revista.lastCode
        },
        errores_detectados: allFindings
          .filter((item) => item.severity === "error" || item.severity === "warning")
          .map((item) => ({
            codigo: item.code,
            severidad: item.severity,
            mensaje: item.message
          }))
      }
    };
  }
}
