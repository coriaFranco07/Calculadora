import {
  buildAuditSummary,
  validarAuxiliarA,
  validarConceptosHuerfanos,
  validarEscalas,
  validarMapeoAFIP,
  validarRevista,
  validarSerie990
} from "./reglas.js";

export function ejecutarAuditoria(liquidacion, catalogs) {
  const validations = [
    validarRevista(liquidacion, catalogs),
    validarSerie990(liquidacion, catalogs),
    validarConceptosHuerfanos(liquidacion, catalogs),
    validarAuxiliarA(liquidacion, catalogs),
    validarMapeoAFIP(liquidacion, catalogs),
    validarEscalas(liquidacion, catalogs)
  ];

  const findings = validations.flatMap((item) => item.findings || []);
  const summary = buildAuditSummary(findings);

  return {
    ...summary,
    findings,
    counters: {
      blockers: summary.bloqueos.length,
      critical: summary.errores.length,
      warning: summary.warnings.length,
      info: summary.info.length,
      total: findings.length
    },
    trazabilidad: validations.map((item) => item.trace).filter(Boolean),
    checklist: validations.map((item) => item.checklist).filter(Boolean),
    resumenIA: {
      periodo: liquidacion.metadata?.input?.liquidationDate?.slice(0, 7) || "",
      resumen_totalizadores: {
        ...liquidacion.totales?.serie990,
        neto_impreso: liquidacion.totales?.bolsillo || 0
      },
      resumen_revista: {
        dias_periodo: liquidacion.revista?.diasPeriodo || 30,
        tramos: liquidacion.revista?.tramos?.length || 0,
        situacion_general: liquidacion.revista?.situacionGeneral || "",
        ultimo_tramo: (liquidacion.revista?.tramos || []).filter((item) => item.codigo).slice(-1)[0]?.codigo || ""
      },
      errores_detectados: findings.map((item) => ({
        codigo: item.code,
        severidad: item.severity,
        mensaje: item.message
      }))
    }
  };
}
