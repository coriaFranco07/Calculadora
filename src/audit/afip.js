import { normalizeText, roundMoney, toNumber } from "./utils.js";

function buildIndex(records, key) {
  return new Map((records || []).map((item) => [String(item[key] || ""), item]));
}

export function inferAfipType(codigoAfip) {
  const raw = String(codigoAfip || "").trim();
  if (!/^\d{6}$/.test(raw)) return "desconocido";
  const numeric = Number(raw);
  if (numeric >= 810000 && numeric <= 829999) return "descuento";
  if (numeric >= 510000 && numeric <= 799999) return "no_remunerativo";
  if (numeric >= 110000 && numeric <= 499999) return "remunerativo";
  return "desconocido";
}

export function expectedSeriesFromCatalog(catalogConcept) {
  if (!catalogConcept) return null;
  if (catalogConcept.tanque_sugerido) return catalogConcept.tanque_sugerido;
  if (catalogConcept.impacta_993) return "993";
  if (catalogConcept.impacta_994) return "994";
  return null;
}

export function findCatalogConcept(description, conceptosCatalog) {
  const normalized = normalizeText(description);
  return (conceptosCatalog || []).find((item) =>
    (item.keywords || []).some((keyword) => normalized.includes(normalizeText(keyword)))
  ) || null;
}

export function findFormulaCatalog(catalogConcept, formulasCatalog) {
  if (!catalogConcept) return null;
  return (formulasCatalog || []).find((item) => item.concepto === catalogConcept.id_concepto) || null;
}

function isAllowedNoRemRange(code) {
  const numeric = Number(code);
  if (!Number.isFinite(numeric)) return false;
  return (
    (numeric >= 510000 && numeric <= 519999) ||
    (numeric >= 520000 && numeric <= 529999) ||
    (numeric >= 531000 && numeric <= 539999) ||
    (numeric >= 541000 && numeric <= 549999) ||
    (numeric >= 551000 && numeric <= 559999)
  );
}

function compatibleSeries(serie, afipType) {
  if (!serie || serie === "sin_tanque") return false;
  if (serie === "996") return false;
  if (afipType === "remunerativo") return serie === "993";
  if (afipType === "descuento") return serie === "995";
  if (afipType === "no_remunerativo") return serie === "994" || serie === "997";
  return true;
}

export function analyzeAfipMapping(concepts, catalogs) {
  const afipIndex = buildIndex(catalogs.mapeoAfip, "codigo_afip");
  const enrichedConcepts = [];
  const findings = [];
  const seriesFromConcepts = {
    "993": 0,
    "994": 0,
    "995": 0,
    "997": 0
  };
  let receiptCredits = 0;
  let receiptDebits = 0;
  let orphanAmount = 0;

  (concepts || []).forEach((concept, index) => {
    const normalized = {
      descripcion: String(concept.descripcion || "").trim(),
      importe: roundMoney(concept.importe),
      serie: String(concept.serie || "sin_tanque").trim() || "sin_tanque",
      lado: concept.lado === "descuento" ? "descuento" : "haber",
      codigoAfip: String(concept.codigo_afip || "").trim(),
      formula: String(concept.formula || "").trim(),
      usaAuxiliarA: Boolean(concept.usa_auxiliar_a)
    };

    if (!normalized.descripcion) return;

    const catalogConcept = findCatalogConcept(normalized.descripcion, catalogs.conceptos);
    const formulaCatalog = findFormulaCatalog(catalogConcept, catalogs.formulas);
    const afipType = inferAfipType(normalized.codigoAfip);
    const afipRecord = afipIndex.get(normalized.codigoAfip) || null;
    const expectedSeries = expectedSeriesFromCatalog(catalogConcept);
    const requiresAuxiliarA =
      normalized.usaAuxiliarA ||
      Boolean(catalogConcept?.requiere_auxiliar_a) ||
      Boolean(formulaCatalog?.requiere_auxiliar_a);

    if (normalized.lado === "haber") {
      receiptCredits = roundMoney(receiptCredits + normalized.importe);
    } else {
      receiptDebits = roundMoney(receiptDebits + normalized.importe);
    }

    if (normalized.serie in seriesFromConcepts) {
      seriesFromConcepts[normalized.serie] = roundMoney(seriesFromConcepts[normalized.serie] + normalized.importe);
    } else {
      orphanAmount = roundMoney(orphanAmount + normalized.importe);
    }

    if (!normalized.codigoAfip) {
      findings.push({
        code: "AFIP_CONCEPTO_SIN_MAPEO",
        severity: "warning",
        domain: "afip",
        title: `Concepto sin codigo AFIP`,
        message: `"${normalized.descripcion}" no tiene codigo AFIP cargado.`,
        conceptIndex: index,
        blocksExport: false
      });
    }

    if (normalized.serie === "996") {
      findings.push({
        code: "AFIP_SERIE_INVALIDA_996",
        severity: "error",
        domain: "afip",
        title: `Serie 996 usada como concepto`,
        message: `"${normalized.descripcion}" no deberia mapearse directo a 996; 996 debe reconstruirse como total neto.`,
        conceptIndex: index,
        blocksExport: true
      });
    }

    if (normalized.serie === "sin_tanque") {
      findings.push({
        code: "CONCEPTO_HUERFANO",
        severity: "error",
        domain: "conceptos",
        title: `Concepto sin tanque`,
        message: `"${normalized.descripcion}" se imprime pero no impacta 993/994/995/997.`,
        conceptIndex: index,
        blocksExport: true
      });
    }

    if (normalized.codigoAfip && !compatibleSeries(normalized.serie, afipType)) {
      findings.push({
        code: "AFIP_TIPO_SERIE_COMPATIBILIDAD",
        severity: "error",
        domain: "afip",
        title: `Serie incompatible con codigo AFIP`,
        message: `"${normalized.descripcion}" usa ${normalized.codigoAfip} (${afipType}) pero impacta serie ${normalized.serie}.`,
        conceptIndex: index,
        blocksExport: true
      });
    }

    if (expectedSeries && normalized.serie !== "sin_tanque" && expectedSeries !== normalized.serie) {
      findings.push({
        code: "AFIP_SERIE_SUGERIDA",
        severity: "warning",
        domain: "afip",
        title: `Serie distinta a la sugerida`,
        message: `"${normalized.descripcion}" suele impactar ${expectedSeries}, pero quedo en ${normalized.serie}.`,
        conceptIndex: index,
        blocksExport: false
      });
    }

    if (catalogConcept?.codigo_afip && normalized.codigoAfip && catalogConcept.codigo_afip !== normalized.codigoAfip) {
      const isNoRemFreeRange =
        catalogConcept.id_concepto === "acuerdo_nr" &&
        isAllowedNoRemRange(normalized.codigoAfip);

      if (!isNoRemFreeRange) {
        findings.push({
          code: "AFIP_CODIGO_DISTINTO_AL_ESPERADO",
          severity: "warning",
          domain: "afip",
          title: `Codigo AFIP distinto al esperado`,
          message: `"${normalized.descripcion}" suele mapearse como ${catalogConcept.codigo_afip}, pero se informo ${normalized.codigoAfip}.`,
          conceptIndex: index,
          blocksExport: false
        });
      }
    }

    if (catalogConcept?.id_concepto === "acuerdo_nr" && normalized.codigoAfip && !isAllowedNoRemRange(normalized.codigoAfip)) {
      findings.push({
        code: "AFIP_NR_RANGO_LIBRE",
        severity: "warning",
        domain: "afip",
        title: `No remunerativo fuera de rango libre sugerido`,
        message:
          `"${normalized.descripcion}" parece no remunerativo y conviene revisar si corresponde un rango 531xxx, 541xxx o 551xxx segun su tratamiento.`,
        conceptIndex: index,
        blocksExport: false
      });
    }

    if (normalized.serie === "995" && normalized.lado !== "descuento") {
      findings.push({
        code: "DESCUENTO_MAL_LADO",
        severity: "warning",
        domain: "afip",
        title: `Descuento marcado como haber`,
        message: `"${normalized.descripcion}" impacta 995 pero no esta marcado como descuento.`,
        conceptIndex: index,
        blocksExport: false
      });
    }

    enrichedConcepts.push({
      ...normalized,
      afipType,
      afipRecord,
      catalogConcept,
      formulaCatalog,
      expectedSeries,
      requiresAuxiliarA
    });
  });

  return {
    findings,
    concepts: enrichedConcepts,
    totalsFromConcepts: seriesFromConcepts,
    receiptNetFromConcepts: roundMoney(receiptCredits - receiptDebits),
    orphanAmount: roundMoney(orphanAmount)
  };
}
