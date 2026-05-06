import { moneyDiff, nearlyEqual, roundMoney } from "./utils.js";

function findingFromRule(rule, overrides) {
  return {
    code: rule.codigo,
    severity: rule.severidad,
    domain: rule.dominio || "general",
    title: rule.codigo,
    message: rule.descripcion,
    blocksExport: Boolean(rule.bloquea_exportacion),
    ...overrides
  };
}

const evaluators = {
  revista_total_days_equals_expected({ payload, facts, rule }) {
    if (facts.revista.coveredDays === payload.dias_periodo) return null;
    return findingFromRule(rule, {
      title: "Revista no cierra contra el periodo",
      message: `Los tramos cubren ${facts.revista.coveredDays} dias y deberian cerrar ${payload.dias_periodo}.`
    });
  },

  revista_no_gaps_or_overlaps({ facts, rule }) {
    if (!facts.revista.gaps.length && !facts.revista.overlaps.length) return null;
    const details = [];
    if (facts.revista.gaps.length) {
      details.push(`Huecos: ${facts.revista.gaps.join(", ")}`);
    }
    if (facts.revista.overlaps.length) {
      details.push(`Superposiciones: ${facts.revista.overlaps.join(", ")}`);
    }
    return findingFromRule(rule, {
      title: "Revista con huecos o superposiciones",
      message: details.join(" | ")
    });
  },

  revista_max_segments({ facts, rule }) {
    const max = rule.condicion?.params?.max ?? 3;
    if (facts.revista.segmentCount <= max) return null;
    return findingFromRule(rule, {
      title: "Revista excede cantidad de tramos",
      message: `Se informaron ${facts.revista.segmentCount} tramos y el limite configurado es ${max}.`
    });
  },

  revista_general_matches_last({ payload, facts, rule }) {
    if (!payload.situacion_general || !facts.revista.lastCode) return null;
    if (payload.situacion_general === facts.revista.lastCode) return null;
    return findingFromRule(rule, {
      title: "Situacion general distinta al ultimo tramo",
      message: `Cabecera ${payload.situacion_general} y ultimo tramo ${facts.revista.lastCode}.`
    });
  },

  worked_days_or_hours_exclusive({ payload, rule }) {
    if (!(payload.dias_trabajados_f931 > 0 && payload.horas_trabajadas_f931 > 0)) return null;
    return findingFromRule(rule, {
      title: "Dias y horas trabajadas cargados al mismo tiempo",
      message: "Para el mismo periodo se deberia informar dias o horas, no ambos simultaneamente."
    });
  },

  serie_990_equation({ payload, facts, rule }) {
    const rebuilt = facts.totalizers.rebuiltNet;
    const expected = payload.totalizadores["996"];
    if (nearlyEqual(rebuilt, expected)) return null;
    return findingFromRule(rule, {
      title: "La ecuacion 996 no coincide",
      message: `996 informado ${expected} vs reconstruido ${rebuilt} con 993 + 994 + 997 - 995.`
    });
  },

  totals_match_concepts({ facts, rule }) {
    if (!facts.totalizers.hasConceptBreakdown) return null;
    const mismatches = Object.entries(facts.totalizers.differencesBySeries)
      .filter(([, diff]) => !nearlyEqual(diff, 0))
      .map(([serie, diff]) => `${serie}: diferencia ${diff}`);

    if (!mismatches.length) return null;
    return findingFromRule(rule, {
      title: "Totalizadores no conciliados contra conceptos",
      message: mismatches.join(" | ")
    });
  },

  orphan_concepts({ facts, rule }) {
    if (!facts.totalizers.orphanConceptCount) return null;
    return findingFromRule(rule, {
      title: "Hay conceptos impresos sin tanque",
      message: `Se detectaron ${facts.totalizers.orphanConceptCount} conceptos huerfanos por ${facts.totalizers.orphanAmount}.`
    });
  },

  auxiliar_a_required({ payload, facts, rule }) {
    if (payload.coeficiente_jornada >= 1) return null;
    if (!facts.formulas.missingAuxiliarA.length) return null;
    return findingFromRule(rule, {
      title: "Formulas de jornada parcial sin AUXILIAR_A",
      message: `Revisar: ${facts.formulas.missingAuxiliarA.map((item) => item.descripcion).join(", ")}.`
    });
  },

  afip_type_matches_series({ facts, rule }) {
    const critical = facts.afipFindings.filter((item) =>
      item.code === "AFIP_TIPO_SERIE_COMPATIBILIDAD" || item.code === "AFIP_SERIE_INVALIDA_996"
    );
    if (!critical.length) return null;
    return findingFromRule(rule, {
      title: "Tipos AFIP incompatibles con la serie",
      message: critical.map((item) => item.message).join(" | ")
    });
  },

  afip_expected_mapping({ facts, rule }) {
    const warnings = facts.afipFindings.filter((item) =>
      item.code === "AFIP_CODIGO_DISTINTO_AL_ESPERADO" || item.code === "AFIP_NR_RANGO_LIBRE"
    );
    if (!warnings.length) return null;
    return findingFromRule(rule, {
      title: "Mapeos AFIP a revisar",
      message: warnings.map((item) => item.message).join(" | ")
    });
  }
};

export class RuleEngine {
  constructor(rules) {
    this.rules = rules || [];
  }

  evaluate(context) {
    return this.rules
      .map((rule) => {
        const evaluator = evaluators[rule.condicion?.type];
        if (!evaluator) return null;
        return evaluator({ ...context, rule });
      })
      .filter(Boolean);
  }
}

export function computeSeriesDifferences(inputTotals, conceptTotals) {
  return {
    "993": roundMoney(moneyDiff(inputTotals["993"], conceptTotals["993"])),
    "994": roundMoney(moneyDiff(inputTotals["994"], conceptTotals["994"])),
    "995": roundMoney(moneyDiff(inputTotals["995"], conceptTotals["995"])),
    "997": roundMoney(moneyDiff(inputTotals["997"], conceptTotals["997"]))
  };
}
