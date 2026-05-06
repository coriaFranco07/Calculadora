const SEVERITY_ORDER = { BLOCKER: 0, CRITICAL: 1, WARNING: 2, INFO: 3 };
const SEVERITY_PENALTY = { BLOCKER: 30, CRITICAL: 18, WARNING: 8, INFO: 2 };

export function normalizeText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

export function roundMoney(value) {
  return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
}

export function nearlyEqual(left, right, tolerance = 0.01) {
  return Math.abs(Number(left || 0) - Number(right || 0)) <= tolerance;
}

function severityBucket(items, severity) {
  return items.filter((item) => item.severity === severity);
}

function catalogConceptFor(description, catalogs) {
  const normalized = normalizeText(description);
  return (catalogs.conceptos || []).find((item) =>
    (item.keywords || []).some((keyword) => normalized.includes(normalizeText(keyword)))
  ) || null;
}

function afipType(code) {
  const numeric = Number(code || 0);
  if (!numeric) return "desconocido";
  if (numeric >= 810000 && numeric <= 829999) return "descuento";
  if (numeric >= 510000 && numeric <= 799999) return "no_remunerativo";
  if (numeric >= 110000 && numeric <= 499999) return "remunerativo";
  return "desconocido";
}

export function validarRevista(liquidacion) {
  const revista = liquidacion.revista || {};
  const tramos = revista.tramos || [];
  const diasPeriodo = revista.diasPeriodo || 30;
  const diasClasificados = tramos
    .filter((item) => item.codigo)
    .reduce((acc, item) => acc + Math.max(0, item.hasta - item.desde + 1), 0);
  const gaps = Math.max(0, diasPeriodo - diasClasificados);
  const findings = [];

  if (diasClasificados !== diasPeriodo) {
    findings.push({
      code: "REVISTA_30_DIAS",
      severity: "BLOCKER",
      title: "Revista incompleta",
      message: `La revista clasificada cubre ${diasClasificados} de ${diasPeriodo} dias.`,
      blocksExport: true
    });
  }

  if ((tramos || []).length > 3) {
    findings.push({
      code: "REVISTA_MAX_3_TRAMOS",
      severity: "BLOCKER",
      title: "Revista excede 3 tramos",
      message: `Se informaron ${tramos.length} tramos y LSD admite hasta 3.`,
      blocksExport: true
    });
  }

  if ((revista.situacionGeneral || "") !== ((tramos.filter((item) => item.codigo).slice(-1)[0] || {}).codigo || "")) {
    findings.push({
      code: "REVISTA_SITUACION_GENERAL",
      severity: "BLOCKER",
      title: "Situacion general inconsistente",
      message: "La situacion general no coincide con el ultimo tramo clasificado.",
      blocksExport: true
    });
  }

  return {
    findings,
    trace: {
      label: "REVISTA",
      lines: [
        `Dias trabajados declarados: ${revista.diasTrabajados ?? 0}`,
        `Licencias: ${revista.diasLicencia ?? 0}`,
        `Suspensiones: ${revista.diasSuspension ?? 0}`,
        `Ausencias: ${revista.diasAusencia ?? 0}`,
        `Dias sin clasificar: ${revista.diasSinClasificar ?? gaps}`,
        `Dias clasificados: ${diasClasificados}`,
        `Total periodo: ${diasPeriodo}`,
        `Resultado: ${diasClasificados === diasPeriodo ? "OK" : "INCOMPLETA"}`
      ]
    },
    checklist: {
      label: "Revista completa",
      ok: diasClasificados === diasPeriodo
    }
  };
}

export function validarSerie990(liquidacion) {
  const serie = liquidacion.totales?.serie990 || {};
  const esperado = roundMoney((serie["993"] || 0) + (serie["994"] || 0) + (serie["997"] || 0) - (serie["995"] || 0));
  const calculado = roundMoney(serie["996"] || 0);
  const ok = nearlyEqual(esperado, calculado);

  return {
    findings: ok
      ? []
      : [
          {
            code: "SERIE_990",
            severity: "BLOCKER",
            title: "Serie 990 no conciliada",
            message: `996 esperado ${esperado} y 996 calculado ${calculado}.`,
            blocksExport: true
          }
        ],
    trace: {
      label: "SERIE 990",
      lines: [
        `993: ${roundMoney(serie["993"] || 0)}`,
        `994: ${roundMoney(serie["994"] || 0)}`,
        `995: ${roundMoney(serie["995"] || 0)}`,
        `997: ${roundMoney(serie["997"] || 0)}`,
        `996 esperado: ${esperado}`,
        `996 calculado: ${calculado}`,
        `Resultado: ${ok ? "OK" : "ERROR"}`
      ]
    },
    checklist: {
      label: "Serie 990 conciliada",
      ok
    }
  };
}

export function validarConceptosHuerfanos(liquidacion) {
  const orphanConcepts = (liquidacion.conceptos || []).filter((item) => !["993", "994", "995", "997"].includes(item.serie));
  return {
    findings: orphanConcepts.length
      ? [
          {
            code: "CONCEPTOS_HUERFANOS",
            severity: "BLOCKER",
            title: "Conceptos sin tanque",
            message: `Se detectaron ${orphanConcepts.length} conceptos sin impacto en serie 990.`,
            blocksExport: true
          }
        ]
      : [],
    trace: {
      label: "CONCEPTOS",
      lines: orphanConcepts.length
        ? orphanConcepts.map((item) => `${item.descripcion}: sin serie asignada`)
        : ["No se detectaron conceptos huerfanos."]
    },
    checklist: {
      label: "Conceptos mapeados a tanques",
      ok: orphanConcepts.length === 0
    }
  };
}

export function validarAuxiliarA(liquidacion, catalogs) {
  const jornada = Number(liquidacion.empleado?.jornadaCoeficiente || 1);
  const offenders = (liquidacion.conceptos || []).filter((item) => {
    const conceptCatalog = catalogConceptFor(item.descripcion, catalogs);
    const formulaCatalog = (catalogs.formulas || []).find((entry) => entry.concepto === conceptCatalog?.id_concepto);
    const requiresAux = item.usa_auxiliar_a || conceptCatalog?.requiere_auxiliar_a || formulaCatalog?.requiere_auxiliar_a;
    const mentionsAux = /aux(\s*iliar)?[_\s-]*a|coeficiente|jornada/i.test(item.formula || "");
    return jornada < 1 && item.lado === "haber" && requiresAux && !mentionsAux;
  });

  return {
    findings: offenders.length
      ? [
          {
            code: "AUXILIAR_A",
            severity: "WARNING",
            title: "Formulas sin AUXILIAR_A",
            message: `Revisar proporcionalidad en ${offenders.map((item) => item.descripcion).join(", ")}.`,
            blocksExport: false
          }
        ]
      : [],
    trace: {
      label: "JORNADA",
      lines: [
        `Coeficiente jornada: ${jornada}`,
        offenders.length ? `Conceptos observados: ${offenders.map((item) => item.descripcion).join(", ")}` : "No hay formulas observadas."
      ]
    },
    checklist: {
      label: "Jornada proporcional validada",
      ok: offenders.length === 0
    }
  };
}

export function validarMapeoAFIP(liquidacion, catalogs) {
  const findings = [];
  const observed = [];
  let allOk = true;

  (liquidacion.conceptos || []).forEach((concept) => {
    const catalog = catalogConceptFor(concept.descripcion, catalogs);
    const expectedSeries = catalog?.tanque_sugerido || (catalog?.impacta_993 ? "993" : catalog?.impacta_994 ? "994" : null);
    const type = afipType(concept.codigo_afip);
    const expectedType = concept.serie === "995" ? "descuento" : concept.serie === "993" ? "remunerativo" : ["994", "997"].includes(concept.serie) ? "no_remunerativo" : "desconocido";

    if (concept.codigo_afip && expectedType !== "desconocido" && type !== expectedType) {
      findings.push({
        code: "AFIP_TIPO_SERIE",
        severity: "BLOCKER",
        title: "Codigo AFIP incompatible con la serie",
        message: `${concept.descripcion} usa ${concept.codigo_afip} pero impacta serie ${concept.serie}.`,
        blocksExport: true
      });
      allOk = false;
    }

    if (catalog?.codigo_afip && concept.codigo_afip && catalog.codigo_afip !== concept.codigo_afip) {
      findings.push({
        code: "AFIP_MAPEO_ESPERADO",
        severity: "WARNING",
        title: "Codigo AFIP distinto al esperado",
        message: `${concept.descripcion} suele mapearse a ${catalog.codigo_afip} y se informo ${concept.codigo_afip}.`,
        blocksExport: false
      });
      allOk = false;
    }

    if (expectedSeries && concept.serie !== expectedSeries) {
      observed.push(`${concept.descripcion}: serie ${concept.serie}, sugerida ${expectedSeries}`);
    }
  });

  return {
    findings,
    trace: {
      label: "MAPEO AFIP",
      lines: observed.length ? observed : ["No se detectaron desalineaciones relevantes de mapeo."]
    },
    checklist: {
      label: "Conceptos mapeados",
      ok: allOk
    }
  };
}

export function validarEscalas(liquidacion) {
  const ok = Boolean(liquidacion.metadata?.scale?.id && liquidacion.metadata?.category?.id);
  return {
    findings: ok
      ? []
      : [
          {
            code: "ESCALAS",
            severity: "CRITICAL",
            title: "Escala no resuelta",
            message: "La liquidacion no pudo vincular categoria y escala activa.",
            blocksExport: false
          }
        ],
    trace: {
      label: "ESCALAS",
      lines: [
        `Escala: ${liquidacion.metadata?.scale?.label || "Sin escala"}`,
        `Categoria: ${liquidacion.metadata?.category?.label || "Sin categoria"}`,
        `Resultado: ${ok ? "OK" : "REVISAR"}`
      ]
    },
    checklist: {
      label: "Bases imponibles consistentes",
      ok
    }
  };
}

export function buildAuditSummary(findings) {
  const sorted = [...findings].sort((left, right) => (SEVERITY_ORDER[left.severity] ?? 99) - (SEVERITY_ORDER[right.severity] ?? 99));
  const score = Math.max(0, 100 - sorted.reduce((acc, item) => acc + (SEVERITY_PENALTY[item.severity] ?? 0), 0));
  const blockers = severityBucket(sorted, "BLOCKER");
  const critical = severityBucket(sorted, "CRITICAL");
  const warnings = severityBucket(sorted, "WARNING");
  const info = severityBucket(sorted, "INFO");

  return {
    score,
    estado: blockers.length ? "BLOCKED" : critical.length ? "CRITICAL" : warnings.length ? "WARNING" : "OK",
    bloqueos: blockers,
    errores: critical,
    warnings,
    info
  };
}
