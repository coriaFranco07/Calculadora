export const roundMoney = (value) => Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
export const numberOrZero = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export function getTodayString() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeJornadaCoefficient(value) {
  const numeric = numberOrZero(value);
  if (!numeric) return 1;
  return Math.min(1, Math.max(0.1, numeric));
}

const buildCategory = (id, sector, label, payBasis, amount) => ({
  id,
  sector,
  label,
  payBasis,
  amount
});

export const convention = {
  id: "cct-244-94",
  name: "CCT 244/94 - Industria de la Alimentacion",
  rules: {
    proportionalMonthDivisor: 30,
    vacationDivisor: 25,
    hourDivisor: 200,
    overtimeMultipliers: { 50: 1.5, 100: 2 },
    seniority: {
      countMode: "completed-years",
      tiers: [
        { maxYearsInclusive: 10, annualRate: 0.01 },
        { maxYearsInclusive: 20, annualRate: 0.0125 },
        { maxYearsInclusive: null, annualRate: 0.015 }
      ]
    },
    presentismo: {
      enabled: false,
      note: "El CCT base no trae un adicional general de presentismo cargado."
    },
    zone: {
      enabled: true,
      percentage: 0.2
    },
    nocturnity: {
      enabled: false,
      note: "No se cargo una regla monetaria general de nocturnidad."
    },
    deductions: {
      retirement: { label: "Jubilacion", percentage: 0.11 },
      pami: { label: "PAMI", percentage: 0.03 },
      health: { label: "Obra social", percentage: 0.03 },
      union: { label: "Sindicato", percentage: 0.02 }
    }
  },
  salaryScales: [
    {
      id: "nov-2025",
      label: "Escala remunerativa noviembre 2025",
      validFrom: "2025-11-01",
      validTo: "2026-03-31",
      sourceLabel: "Escala salarial agosto-noviembre 2025",
      categories: [
        buildCategory("elab-operario", "Elaboracion, envasamiento y varios", "Operario", "hourly", 5960),
        buildCategory("elab-operario-general", "Elaboracion, envasamiento y varios", "Operario general", "hourly", 6193.41),
        buildCategory("elab-operario-calificado", "Elaboracion, envasamiento y varios", "Operario calificado", "hourly", 6418.66),
        buildCategory("elab-medio-oficial", "Elaboracion, envasamiento y varios", "Medio oficial", "hourly", 6713.47),
        buildCategory("elab-oficial", "Elaboracion, envasamiento y varios", "Oficial", "hourly", 7321.3),
        buildCategory("elab-oficial-general", "Elaboracion, envasamiento y varios", "Oficial general", "hourly", 7757.28),
        buildCategory("elab-oficial-calificado", "Elaboracion, envasamiento y varios", "Oficial calificado", "hourly", 8119.07),
        buildCategory("mant-operario-calificado", "Mantenimiento", "Operario calificado", "hourly", 6418.66),
        buildCategory("mant-medio-oficial-general", "Mantenimiento", "Medio oficial general", "hourly", 7757.28),
        buildCategory("mant-oficial-oficios-varios", "Mantenimiento", "Oficial de oficios varios", "hourly", 7942.73),
        buildCategory("mant-oficial-oficios-generales", "Mantenimiento", "Oficial de oficios generales", "hourly", 8487.94),
        buildCategory("mant-oficial-calificado", "Mantenimiento", "Oficial calificado", "hourly", 8925.26),
        buildCategory("admin-categoria-i", "Administracion", "Categoria I", "monthly", 1193082.58),
        buildCategory("admin-categoria-ii", "Administracion", "Categoria II", "monthly", 1261241.28),
        buildCategory("admin-categoria-iii", "Administracion", "Categoria III", "monthly", 1378455.01),
        buildCategory("admin-categoria-iv", "Administracion", "Categoria IV", "monthly", 1501527.79),
        buildCategory("admin-categoria-v", "Administracion", "Categoria V", "monthly", 1575375.55),
        buildCategory("admin-categoria-vi", "Administracion", "Categoria VI", "monthly", 1716913.57),
        buildCategory("admin-segundo-jefe", "Administracion", "2do jefe de seccion", "monthly", 1987677.27),
        buildCategory("mens-celadores", "Personal obrero mensualizado", "Celadores, cuidadores y camarera comedor", "monthly", 1191998.29),
        buildCategory("mens-encargada-cocina", "Personal obrero mensualizado", "Encargada, ayudante cocina comedor personal", "monthly", 1204438.74),
        buildCategory("mens-porteros-serenos", "Personal obrero mensualizado", "Porteros y serenos", "monthly", 1249885.79),
        buildCategory("mens-ayudante-repartidor", "Personal obrero mensualizado", "Ayudante repartidor", "monthly", 1204438.74),
        buildCategory("mens-cocinero-comedor", "Personal obrero mensualizado", "Cocinero comedor personal", "monthly", 1272606.39),
        buildCategory("mens-chofer-repartidor", "Personal obrero mensualizado", "Chofer y chofer repartidor", "monthly", 1306688.33)
      ]
    },
    {
      id: "apr-2026",
      label: "Escala remunerativa abril 2026",
      validFrom: "2026-04-01",
      validTo: null,
      sourceLabel: "Escala abril 2026 publicada sin texto completo del acuerdo",
      notes: [
        "La fuente difundio la escala y la suma extraordinaria, pero no el texto completo del acuerdo al 18/03/2026."
      ],
      categories: [
        buildCategory("elab-operario", "Elaboracion, envasamiento y varios", "Operario", "hourly", 6700),
        buildCategory("elab-operario-general", "Elaboracion, envasamiento y varios", "Operario general", "hourly", 6962.38),
        buildCategory("elab-operario-calificado", "Elaboracion, envasamiento y varios", "Operario calificado", "hourly", 7215.61),
        buildCategory("elab-medio-oficial", "Elaboracion, envasamiento y varios", "Medio oficial", "hourly", 7547.02),
        buildCategory("elab-oficial", "Elaboracion, envasamiento y varios", "Oficial", "hourly", 8230.32),
        buildCategory("elab-oficial-general", "Elaboracion, envasamiento y varios", "Oficial general", "hourly", 8720.42),
        buildCategory("elab-oficial-calificado", "Elaboracion, envasamiento y varios", "Oficial calificado", "hourly", 9127.14),
        buildCategory("mant-operario-calificado", "Mantenimiento", "Operario calificado", "hourly", 7215.61),
        buildCategory("mant-medio-oficial-general", "Mantenimiento", "Medio oficial general", "hourly", 8720.42),
        buildCategory("mant-oficial-oficios-varios", "Mantenimiento", "Oficial de oficios varios", "hourly", 8928.9),
        buildCategory("mant-oficial-oficios-generales", "Mantenimiento", "Oficial de oficios generales", "hourly", 9541.8),
        buildCategory("mant-oficial-calificado", "Mantenimiento", "Oficial calificado", "hourly", 10033.43),
        buildCategory("admin-categoria-i", "Administracion", "Categoria I", "monthly", 1341216.37),
        buildCategory("admin-categoria-ii", "Administracion", "Categoria II", "monthly", 1417837.69),
        buildCategory("admin-categoria-iii", "Administracion", "Categoria III", "monthly", 1549604.74),
        buildCategory("admin-categoria-iv", "Administracion", "Categoria IV", "monthly", 1687958.31),
        buildCategory("admin-categoria-v", "Administracion", "Categoria V", "monthly", 1770975.05),
        buildCategory("admin-categoria-vi", "Administracion", "Categoria VI", "monthly", 1930086.51),
        buildCategory("admin-segundo-jefe", "Administracion", "2do jefe de seccion", "monthly", 2234468.37),
        buildCategory("mens-celadores", "Personal obrero mensualizado", "Celadores, cuidadores y camarera comedor", "monthly", 1339997.45),
        buildCategory("mens-encargada-cocina", "Personal obrero mensualizado", "Encargada, ayudante cocina comedor personal", "monthly", 1353982.52),
        buildCategory("mens-porteros-serenos", "Personal obrero mensualizado", "Porteros y serenos", "monthly", 1405072.3),
        buildCategory("mens-ayudante-repartidor", "Personal obrero mensualizado", "Ayudante repartidor", "monthly", 1353982.52),
        buildCategory("mens-cocinero-comedor", "Personal obrero mensualizado", "Cocinero comedor personal", "monthly", 1430613.9),
        buildCategory("mens-chofer-repartidor", "Personal obrero mensualizado", "Chofer y chofer repartidor", "monthly", 1468927.47)
      ]
    }
  ],
  agreements: [
    {
      id: "nr-mar-2026",
      label: "Suma no remunerativa extraordinaria de marzo 2026",
      validFrom: "2026-03-01",
      validTo: "2026-03-31",
      notes: [
        "Se abona por unica vez y la planilla publicada indica pago antes del 24/03/2026.",
        "Como no estaba disponible el acuerdo integro, los impactos sobre descuentos y adicionales quedan configurables."
      ],
      defaults: {
        enabled: true,
        prorateByDays: false,
        applySeniority: false,
        applySocialSecurity: false,
        applyHealthAndUnion: false,
        applyZone: false
      },
      categoryAmounts: {
        "elab-operario": 100000,
        "elab-operario-general": 103916.23,
        "elab-operario-calificado": 107695.72,
        "elab-medio-oficial": 112642.2,
        "elab-oficial": 122840.68,
        "elab-oficial-general": 130155.65,
        "elab-oficial-calificado": 136225.98,
        "mant-operario-calificado": 107695.72,
        "mant-medio-oficial-general": 130155.65,
        "mant-oficial-oficios-varios": 133267.26,
        "mant-oficial-oficios-generales": 142415.06,
        "mant-oficial-calificado": 149752.71,
        "admin-categoria-i": 100090.84,
        "admin-categoria-ii": 105808.85,
        "admin-categoria-iii": 115642.22,
        "admin-categoria-iv": 125967.12,
        "admin-categoria-v": 132162.4,
        "admin-categoria-vi": 144036.4,
        "admin-segundo-jefe": 166751.48,
        "mens-celadores": 100000,
        "mens-encargada-cocina": 101043.54,
        "mens-porteros-serenos": 104856.21,
        "mens-ayudante-repartidor": 101043.54,
        "mens-cocinero-comedor": 106762.3,
        "mens-chofer-repartidor": 109621.52
      }
    }
  ],
  sources: [
    "CCT 244/94 - arts. 11, 15, 16, 17 y 19",
    "Escala salarial noviembre 2025",
    "Escala salarial abril 2026",
    "Planillas y exportes de e-Sueldos aportados por el usuario"
  ]
};

export const modelFlow = [
  { step: 1, code: "C001", label: "Sueldo basico proporcional", rule: "Basico mensual equivalente / 30 x dias trabajados" },
  { step: 2, code: "C002", label: "Antiguedad", rule: "Basico proporcional x porcentaje por anos cumplidos" },
  { step: 3, code: "C003", label: "Presentismo", rule: "Concepto preparado, no general en esta base" },
  { step: 4, code: "BASE", label: "Base de calculo", rule: "Basico + antiguedad + presentismo" },
  { step: 5, code: "ADIC", label: "Adicionales", rule: "Zona, nocturnidad y otros adicionales remunerativos" },
  { step: 6, code: "VH", label: "Valor hora", rule: "Base horaria / 200" },
  { step: 7, code: "HEX", label: "Horas extra", rule: "Valor hora x cantidad x multiplicador" },
  { step: 8, code: "BRUTO", label: "Total remunerativo", rule: "Suma de conceptos remunerativos" },
  { step: 9, code: "BASESS", label: "Base seguridad social", rule: "Bruto mas impactos NR configurados" },
  { step: 10, code: "DESC", label: "Descuentos", rule: "Jubilacion 11%, PAMI 3%, obra social y sindicato" },
  { step: 11, code: "NETO", label: "Neto remunerativo", rule: "Bruto remunerativo - descuentos" },
  { step: 12, code: "NR", label: "No remunerativos", rule: "Suma NR y adicionales configurados" },
  { step: 13, code: "BOLS", label: "Total en bolsillo", rule: "Neto remunerativo + no remunerativos" }
];

export const ruleSnapshots = [
  {
    label: "Base de calculo",
    valueText: "Base simple",
    note: "Se parte del basico proporcional y luego se agregan antiguedad y adicionales."
  },
  {
    label: "Presentismo general",
    valueText: convention.rules.presentismo.enabled ? "Confirmado" : "No confirmado",
    note: convention.rules.presentismo.note
  },
  {
    label: "Nocturnidad",
    valueText: convention.rules.nocturnity.enabled ? "Activa" : "Pendiente de regla especifica",
    note: convention.rules.nocturnity.note
  },
  {
    label: "Zona desfavorable",
    valueText: "20%",
    note: "Se toma como adicional configurable del 20%."
  },
  {
    label: "Sindicato",
    valueText: "2%",
    note: "Se puede desactivar para simular casos sin aporte sindical."
  }
];

export function resolveScale(dateString, activeConvention = convention) {
  return activeConvention.salaryScales.find((scale) => {
    if (dateString < scale.validFrom) return false;
    if (scale.validTo && dateString > scale.validTo) return false;
    return true;
  });
}

export function resolveAgreements(dateString, activeConvention = convention) {
  return activeConvention.agreements.filter((agreement) => {
    if (dateString < agreement.validFrom) return false;
    if (agreement.validTo && dateString > agreement.validTo) return false;
    return true;
  });
}

export function getMonthlyEquivalent(category, activeConvention = convention) {
  return category.payBasis === "hourly"
    ? roundMoney(category.amount * activeConvention.rules.hourDivisor)
    : roundMoney(category.amount);
}

export function computeSeniorityPercent(years, activeConvention = convention) {
  let remaining = Math.max(0, Math.floor(years));
  let previousLimit = 0;
  let totalPercent = 0;

  for (const tier of activeConvention.rules.seniority.tiers) {
    if (remaining <= 0) break;
    if (tier.maxYearsInclusive === null) {
      totalPercent += remaining * tier.annualRate;
      break;
    }
    const span = tier.maxYearsInclusive - previousLimit;
    const tierYears = Math.min(remaining, span);
    totalPercent += tierYears * tier.annualRate;
    remaining -= tierYears;
    previousLimit = tier.maxYearsInclusive;
  }

  return totalPercent;
}

export function validateLiquidationInput(input, activeConvention = convention) {
  const errors = [];
  const warnings = [];
  const scale = resolveScale(input.liquidationDate, activeConvention);
  const category = scale?.categories.find((item) => item.id === input.categoryId);
  const jornadaCoefficient = normalizeJornadaCoefficient(input.jornadaCoefficient);

  if (!scale) errors.push("No hay escala cargada para la fecha indicada.");
  if (!category) errors.push("La categoria elegida no existe en la escala vigente.");
  if (input.seniorityMonths > 11) errors.push("Los meses de antiguedad deben estar entre 0 y 11.");
  if (input.workedDays < 0 || input.overtime50Hours < 0 || input.overtime100Hours < 0) {
    errors.push("No se admiten valores negativos.");
  }
  if (numberOrZero(input.jornadaCoefficient) > 1) {
    errors.push("El coeficiente de jornada no puede superar 1.");
  }
  if (input.liquidationType === "mensual" && input.workedDays > 30) {
    errors.push("En liquidacion mensual los dias trabajados no pueden superar 30.");
  }
  if (input.liquidationType === "vacaciones" && input.vacationDays <= 0) {
    errors.push("Indica los dias de vacaciones a liquidar.");
  }
  if (input.seniorityMonths > 0) {
    warnings.push("La antiguedad se computa por anos cumplidos; los meses no alteran el porcentaje.");
  }
  if (jornadaCoefficient < 1) {
    warnings.push(`La jornada parcial se tomara con coeficiente ${jornadaCoefficient.toFixed(2)}.`);
  }
  if (scale?.notes?.length) warnings.push(scale.notes[0]);

  return { errors, warnings, scale, category, agreements: resolveAgreements(input.liquidationDate, activeConvention) };
}

function calculateAgreementValue(agreement, categoryId, workedDays, overrides) {
  const baseAmount = numberOrZero(agreement.categoryAmounts[categoryId]);
  const proportion = overrides.prorateByDays ? workedDays / 30 : 1;
  return roundMoney(baseAmount * proportion);
}

function buildRevistaDerivada(input, activeConvention = convention) {
  const daysInPeriod = activeConvention.rules.proportionalMonthDivisor;
  const manualSegments = (input.revistaSegments || [])
    .map((segment) => ({
      codigo: String(segment.codigo || "").trim(),
      etiqueta: String(segment.codigo || "").trim() ? `Tramo ${String(segment.codigo || "").trim()}` : "Tramo sin codigo",
      desde: Math.max(0, Math.trunc(numberOrZero(segment.desde))),
      hasta: Math.max(0, Math.trunc(numberOrZero(segment.hasta))),
      origen: "manual"
    }))
    .filter((segment) => segment.codigo || segment.desde || segment.hasta)
    .sort((left, right) => left.desde - right.desde);

  if (manualSegments.length) {
    const codedSegments = manualSegments.filter((segment) => segment.codigo);
    const classifiedDays = codedSegments.reduce(
      (accumulator, segment) => accumulator + Math.max(0, segment.hasta - segment.desde + 1),
      0
    );
    const workedDaysFromSegments = codedSegments
      .filter((segment) => segment.codigo === "01")
      .reduce((accumulator, segment) => accumulator + Math.max(0, segment.hasta - segment.desde + 1), 0);
    const lastCode = codedSegments.slice(-1)[0]?.codigo || "";

    return {
      diasPeriodo: daysInPeriod,
      diasTrabajados: workedDaysFromSegments || Math.max(0, Math.min(daysInPeriod, Math.trunc(numberOrZero(input.workedDays)))),
      diasLicencia: Math.max(0, Math.trunc(numberOrZero(input.licensedDays))),
      diasSuspension: Math.max(0, Math.trunc(numberOrZero(input.suspensionDays))),
      diasAusencia: Math.max(0, Math.trunc(numberOrZero(input.absenceDays))),
      diasSinClasificar: Math.max(0, daysInPeriod - classifiedDays),
      situacionGeneral: lastCode,
      tramos: manualSegments,
      origen: "Revista tomada desde la carga explicita de tramos del wizard."
    };
  }

  const workedDays = Math.max(0, Math.min(daysInPeriod, Math.trunc(numberOrZero(input.workedDays))));
  const missingDays = Math.max(0, daysInPeriod - workedDays);
  const tramos = [];

  if (workedDays > 0) {
    tramos.push({ codigo: "01", etiqueta: "Activo", desde: 1, hasta: workedDays, origen: "derivado" });
  }
  if (missingDays > 0) {
    tramos.push({
      codigo: "",
      etiqueta: "Dias pendientes de clasificar",
      desde: workedDays + 1,
      hasta: daysInPeriod,
      origen: "derivado"
    });
  }

  return {
    diasPeriodo: daysInPeriod,
    diasTrabajados: workedDays,
    diasLicencia: Math.max(0, Math.trunc(numberOrZero(input.licensedDays))),
    diasSuspension: Math.max(0, Math.trunc(numberOrZero(input.suspensionDays))),
    diasAusencia: Math.max(0, Math.trunc(numberOrZero(input.absenceDays))),
    diasSinClasificar: missingDays,
    situacionGeneral: missingDays === 0 ? "01" : "",
    tramos,
    origen: missingDays === 0
      ? "Revista derivada automaticamente desde dias trabajados."
      : "La UI deriva revista desde dias trabajados y deja visible el faltante temporal hasta que exista clasificacion explicita."
  };
}

function buildStructuredLiquidation({
  input,
  category,
  scale,
  agreements,
  result,
  activeConvention = convention
}) {
  const appliedAgreements = result.nonRemConcepts || [];
  const remunerationConcepts = [
    {
      descripcion: "Basico convenio",
      importe: result.type === "vacaciones" ? result.values.grossRemunerative : result.values.basicProportional,
      serie: "993",
      lado: "haber",
      codigo_afip: result.type === "vacaciones" ? "150000" : "110000",
      formula: result.type === "vacaciones" ? "BASE_VACACIONES / 25 * DIAS_VACACIONES" : "BASICO_MENSUAL / 30 * DIAS_TRABAJADOS * AUXILIAR_A",
      usa_auxiliar_a: result.type !== "vacaciones"
    },
    {
      descripcion: "Adicional por antiguedad",
      importe: result.values.seniority,
      serie: "993",
      lado: "haber",
      codigo_afip: "160001",
      formula: "BASICO_PROPORCIONAL * PORCENTAJE_ANTIGUEDAD * AUXILIAR_A",
      usa_auxiliar_a: true
    },
    {
      descripcion: "Zona desfavorable",
      importe: result.values.zone,
      serie: "993",
      lado: "haber",
      codigo_afip: "140000",
      formula: "BASICO_PROPORCIONAL * PORCENTAJE_ZONA * AUXILIAR_A",
      usa_auxiliar_a: true
    },
    {
      descripcion: "Horas extras al 50",
      importe: result.values.overtime50,
      serie: "993",
      lado: "haber",
      codigo_afip: "130001",
      formula: "VALOR_HORA * HORAS_50 * 1.5",
      usa_auxiliar_a: false
    },
    {
      descripcion: "Horas extras al 100",
      importe: result.values.overtime100,
      serie: "993",
      lado: "haber",
      codigo_afip: "130002",
      formula: "VALOR_HORA * HORAS_100 * 2",
      usa_auxiliar_a: false
    },
    {
      descripcion: "SAC proporcional",
      importe: result.values.sacProportional,
      serie: "993",
      lado: "haber",
      codigo_afip: "120003",
      formula: "BASE_SAC / 12 * DIAS_SEMESTRE / 180",
      usa_auxiliar_a: false
    }
  ].filter((item) => roundMoney(item.importe) !== 0);

  const nonRemunerativeConcepts = [
    ...appliedAgreements.map((concept) => ({
      descripcion: concept.label,
      importe: concept.subtotal,
      serie: "994",
      lado: "haber",
      codigo_afip: "531000",
      formula: concept.runtime?.prorateByDays ? "MONTO_ACUERDO * DIAS_TRABAJADOS / 30" : "MONTO_ACUERDO",
      usa_auxiliar_a: false
    })),
    ...(roundMoney(result.values.unusedVacation) !== 0
      ? [
          {
            descripcion: "Vacaciones no gozadas",
            importe: result.values.unusedVacation,
            serie: "994",
            lado: "haber",
            codigo_afip: "520012",
            formula: "BASE_VACACIONES / 25 * DIAS_NO_GOZADOS",
            usa_auxiliar_a: false
          }
        ]
      : [])
  ];

  const discountConcepts = [
    {
      descripcion: "Aporte jubilacion 11%",
      importe: result.values.deductions.retirement,
      serie: "995",
      lado: "descuento",
      codigo_afip: "810000",
      formula: "BASE_JUBILACION * 0.11",
      usa_auxiliar_a: false
    },
    {
      descripcion: "PAMI",
      importe: result.values.deductions.pami,
      serie: "995",
      lado: "descuento",
      codigo_afip: "810001",
      formula: "BASE_JUBILACION * 0.03",
      usa_auxiliar_a: false
    },
    {
      descripcion: "Obra social",
      importe: result.values.deductions.health,
      serie: "995",
      lado: "descuento",
      codigo_afip: "810002",
      formula: "BASE_OS * 0.03",
      usa_auxiliar_a: false
    },
    {
      descripcion: "Cuota sindical",
      importe: result.values.deductions.union,
      serie: "995",
      lado: "descuento",
      codigo_afip: "810004",
      formula: "BASE_SINDICATO * 0.02",
      usa_auxiliar_a: false
    }
  ].filter((item) => roundMoney(item.importe) !== 0);

  return {
    empleado: {
      categoriaId: category.id,
      categoria: category.label,
      sector: category.sector,
      antiguedadAnios: input.seniorityYears,
      antiguedadMeses: input.seniorityMonths,
      jornadaCoeficiente: normalizeJornadaCoefficient(input.jornadaCoefficient)
    },
    conceptos: [
      ...remunerationConcepts,
      ...nonRemunerativeConcepts,
      ...discountConcepts
    ],
    totales: {
      remunerativo: result.values.grossRemunerative,
      noRemunerativo: result.values.nonRemunerativeTotal,
      descuentos: result.values.totalDeductions,
      netoRemunerativo: result.values.netRemunerative,
      bolsillo: result.values.totalPocket,
      serie990: {
        "993": result.values.grossRemunerative,
        "994": result.values.nonRemunerativeTotal,
        "995": result.values.totalDeductions,
        "996": result.values.totalPocket,
        "997": 0
      }
    },
    bases: {
      seguridadSocial: result.values.socialSecurityBase,
      obraSocialSindicato: result.values.healthAndUnionBase,
      valorHora: result.values.hourValue,
      equivalenteMensual: result.monthlyEquivalent,
      porcentajeAntiguedad: result.seniorityPercent,
      baseCalculo: result.values.baseCalculation
    },
    revista: buildRevistaDerivada(input, activeConvention),
    descuentos: result.values.deductions,
    metadata: {
      conventionId: activeConvention.id,
      conventionName: activeConvention.name,
      scale,
      category,
      type: result.type,
      sourceNotes: [
        { title: "Escala activa", body: `${scale.label}. ${scale.sourceLabel}.` },
        ...(scale.notes || []).map((note) => ({ title: "Nota de escala", body: note })),
        ...agreements.flatMap((agreement) => agreement.notes.map((note) => ({ title: agreement.label, body: note }))),
        ...activeConvention.sources.map((source) => ({ title: "Fuente", body: source }))
      ],
      agreementsApplied: appliedAgreements,
      steps: result.steps,
      input,
      warnings: []
    },
    debug: {
      values: result.values,
      meta: result.meta,
      nonRemConcepts: result.nonRemConcepts
    }
  };
}

function calculateMensual(input, category, agreements, activeConvention = convention) {
  const jornadaCoefficient = normalizeJornadaCoefficient(input.jornadaCoefficient);
  const monthlyEquivalent = roundMoney(getMonthlyEquivalent(category, activeConvention) * jornadaCoefficient);
  const seniorityPercent = computeSeniorityPercent(input.seniorityYears, activeConvention);
  const basicProportional = roundMoney((monthlyEquivalent / 30) * input.workedDays);
  const seniority = roundMoney(basicProportional * seniorityPercent);
  const presentismo = 0;
  const baseCalculation = roundMoney(basicProportional + seniority + presentismo);
  const zone = input.zoneUnfavorable ? roundMoney(basicProportional * activeConvention.rules.zone.percentage) : 0;
  const nocturnity = 0;
  const hourValueBase = roundMoney(baseCalculation + zone);
  const hourValue = roundMoney(hourValueBase / activeConvention.rules.hourDivisor);
  const overtime50 = roundMoney(hourValue * input.overtime50Hours * activeConvention.rules.overtimeMultipliers[50]);
  const overtime100 = roundMoney(hourValue * input.overtime100Hours * activeConvention.rules.overtimeMultipliers[100]);
  const grossRemunerative = roundMoney(basicProportional + seniority + presentismo + zone + overtime50 + overtime100);

  const nonRemConcepts = [];
  let nonRemunerativeTotal = 0;
  let socialAgreementBase = 0;
  let healthAgreementBase = 0;

  if (input.includeNonRemuneratives) {
    agreements.forEach((agreement) => {
      const runtime = { ...agreement.defaults, ...(input.agreementOverrides[agreement.id] || {}) };
      if (!runtime.enabled) return;
      const amount = calculateAgreementValue(agreement, category.id, input.workedDays, runtime);
      const nrSeniority = runtime.applySeniority ? roundMoney(amount * seniorityPercent) : 0;
      const nrZone = runtime.applyZone && input.zoneUnfavorable ? roundMoney(amount * activeConvention.rules.zone.percentage) : 0;
      const subtotal = roundMoney(amount + nrSeniority + nrZone);
      if (runtime.applySocialSecurity) socialAgreementBase += subtotal;
      if (runtime.applyHealthAndUnion) healthAgreementBase += subtotal;
      nonRemunerativeTotal += subtotal;
      nonRemConcepts.push({
        label: agreement.label,
        amount,
        seniorityAmount: nrSeniority,
        zoneAmount: nrZone,
        subtotal,
        note: agreement.notes[0],
        runtime
      });
    });
  }

  const socialSecurityBase = roundMoney(grossRemunerative + socialAgreementBase);
  const healthAndUnionBase = roundMoney(grossRemunerative + healthAgreementBase);
  const deductions = {
    retirement: roundMoney(socialSecurityBase * activeConvention.rules.deductions.retirement.percentage),
    pami: roundMoney(socialSecurityBase * activeConvention.rules.deductions.pami.percentage),
    health: roundMoney(healthAndUnionBase * activeConvention.rules.deductions.health.percentage),
    union: input.applyUnion ? roundMoney(healthAndUnionBase * activeConvention.rules.deductions.union.percentage) : 0
  };
  const totalDeductions = roundMoney(deductions.retirement + deductions.pami + deductions.health + deductions.union);
  const netRemunerative = roundMoney(grossRemunerative - totalDeductions);
  const totalPocket = roundMoney(netRemunerative + nonRemunerativeTotal);

  return {
    type: "mensual",
    monthlyEquivalent,
    seniorityPercent,
    values: {
      basicProportional,
      seniority,
      presentismo,
      baseCalculation,
      zone,
      nocturnity,
      hourValue,
      overtime50,
      overtime100,
      grossRemunerative,
      socialSecurityBase,
      healthAndUnionBase,
      deductions,
      totalDeductions,
      netRemunerative,
      nonRemunerativeTotal,
      totalPocket,
      sacProportional: 0,
      unusedVacation: 0,
      sacOnUnusedVacation: 0
    },
    nonRemConcepts,
    steps: [
      {
        label: "Sueldo basico proporcional",
        amount: basicProportional,
        formula: "Basico mensual equivalente / 30 x dias trabajados",
        detail: `${monthlyEquivalent.toFixed(2)} / 30 x ${input.workedDays}`
      },
      {
        label: "Antiguedad",
        amount: seniority,
        formula: "Basico proporcional x % de antiguedad",
        detail: `${basicProportional.toFixed(2)} x ${(seniorityPercent * 100).toFixed(2)}%`
      },
      {
        label: "Base de calculo",
        amount: baseCalculation,
        formula: "Basico proporcional + antiguedad + presentismo"
      },
      {
        label: "Zona desfavorable",
        amount: zone,
        formula: "Basico proporcional x 20%",
        detail: input.zoneUnfavorable ? `${basicProportional.toFixed(2)} x 20%` : "No aplica"
      },
      {
        label: "Valor hora",
        amount: hourValue,
        formula: "Base horaria / 200",
        detail: `${hourValueBase.toFixed(2)} / 200`
      },
      {
        label: "Horas extra 50%",
        amount: overtime50,
        formula: "Valor hora x horas 50% x 1.5",
        detail: `${hourValue.toFixed(2)} x ${input.overtime50Hours} x 1.5`
      },
      {
        label: "Horas extra 100%",
        amount: overtime100,
        formula: "Valor hora x horas 100% x 2",
        detail: `${hourValue.toFixed(2)} x ${input.overtime100Hours} x 2`
      },
      {
        label: "Total remunerativo bruto",
        amount: grossRemunerative,
        formula: "Suma de conceptos remunerativos"
      },
      {
        label: "Base de seguridad social",
        amount: socialSecurityBase,
        formula: "Remunerativo + NR que impactan seguridad social"
      },
      {
        label: "Descuentos",
        amount: totalDeductions,
        formula: "Jubilacion + PAMI + obra social + sindicato"
      },
      {
        label: "Neto remunerativo",
        amount: netRemunerative,
        formula: "Bruto remunerativo - descuentos"
      },
      {
        label: "No remunerativos",
        amount: nonRemunerativeTotal,
        formula: "Suma NR y adicionales configurados"
      },
      {
        label: "Total en bolsillo",
        amount: totalPocket,
        formula: "Neto remunerativo + no remunerativos"
      }
    ],
    meta: {
      basicInputAmount: category.amount,
      basicInputBasis: category.payBasis,
      hourValueBase,
      socialSecurityAgreementBase: socialAgreementBase,
      healthAgreementBase
    }
  };
}

function calculateVacations(input, category, activeConvention = convention) {
  const jornadaCoefficient = normalizeJornadaCoefficient(input.jornadaCoefficient);
  const monthlyEquivalent = roundMoney(getMonthlyEquivalent(category, activeConvention) * jornadaCoefficient);
  const seniorityPercent = computeSeniorityPercent(input.seniorityYears, activeConvention);
  const base = roundMoney(
    monthlyEquivalent +
      monthlyEquivalent * seniorityPercent +
      (input.zoneUnfavorable ? monthlyEquivalent * activeConvention.rules.zone.percentage : 0)
  );
  const grossRemunerative = roundMoney((base / activeConvention.rules.vacationDivisor) * input.vacationDays);
  const socialSecurityBase = grossRemunerative;
  const healthAndUnionBase = grossRemunerative;
  const deductions = {
    retirement: roundMoney(socialSecurityBase * activeConvention.rules.deductions.retirement.percentage),
    pami: roundMoney(socialSecurityBase * activeConvention.rules.deductions.pami.percentage),
    health: roundMoney(healthAndUnionBase * activeConvention.rules.deductions.health.percentage),
    union: input.applyUnion ? roundMoney(healthAndUnionBase * activeConvention.rules.deductions.union.percentage) : 0
  };
  const totalDeductions = roundMoney(deductions.retirement + deductions.pami + deductions.health + deductions.union);
  const totalPocket = roundMoney(grossRemunerative - totalDeductions);

  return {
    type: "vacaciones",
    monthlyEquivalent,
    seniorityPercent,
    values: {
      basicProportional: 0,
      seniority: roundMoney(monthlyEquivalent * seniorityPercent),
      presentismo: 0,
      baseCalculation: base,
      zone: input.zoneUnfavorable ? roundMoney(monthlyEquivalent * activeConvention.rules.zone.percentage) : 0,
      nocturnity: 0,
      hourValue: roundMoney(base / activeConvention.rules.hourDivisor),
      overtime50: 0,
      overtime100: 0,
      grossRemunerative,
      socialSecurityBase,
      healthAndUnionBase,
      deductions,
      totalDeductions,
      netRemunerative: totalPocket,
      nonRemunerativeTotal: 0,
      totalPocket,
      sacProportional: 0,
      unusedVacation: 0,
      sacOnUnusedVacation: 0
    },
    nonRemConcepts: [],
    steps: [
      { label: "Base vacaciones", amount: base, formula: "Basico mensual equivalente + antiguedad + adicionales habituales" },
      {
        label: "Vacaciones",
        amount: grossRemunerative,
        formula: "Base vacaciones / 25 x dias de vacaciones",
        detail: `${base.toFixed(2)} / 25 x ${input.vacationDays}`
      },
      {
        label: "Descuentos",
        amount: totalDeductions,
        formula: "Jubilacion + PAMI + obra social + sindicato"
      }
    ],
    meta: {
      basicInputAmount: category.amount,
      basicInputBasis: category.payBasis,
      hourValueBase: base,
      socialSecurityAgreementBase: 0,
      healthAgreementBase: 0
    }
  };
}

function calculateFinal(input, category, agreements, activeConvention = convention) {
  const mensual = calculateMensual({ ...input, includeNonRemuneratives: false }, category, agreements, activeConvention);
  const monthlyEquivalent = mensual.monthlyEquivalent;
  const seniorityPercent = mensual.seniorityPercent;
  const fullMonthBase = roundMoney(
    monthlyEquivalent +
      monthlyEquivalent * seniorityPercent +
      (input.zoneUnfavorable ? monthlyEquivalent * activeConvention.rules.zone.percentage : 0)
  );
  const sacProportional = roundMoney((fullMonthBase / 12) * (input.semesterDaysWorked / 180));
  const unusedVacation = roundMoney((fullMonthBase / activeConvention.rules.vacationDivisor) * input.unusedVacationDays);
  const sacOnUnusedVacation = roundMoney(unusedVacation / 12);
  const grossRemunerative = roundMoney(
    mensual.values.grossRemunerative + sacProportional + unusedVacation + sacOnUnusedVacation
  );
  const socialSecurityBase = grossRemunerative;
  const healthAndUnionBase = grossRemunerative;
  const deductions = {
    retirement: roundMoney(socialSecurityBase * activeConvention.rules.deductions.retirement.percentage),
    pami: roundMoney(socialSecurityBase * activeConvention.rules.deductions.pami.percentage),
    health: roundMoney(healthAndUnionBase * activeConvention.rules.deductions.health.percentage),
    union: input.applyUnion ? roundMoney(healthAndUnionBase * activeConvention.rules.deductions.union.percentage) : 0
  };
  const totalDeductions = roundMoney(deductions.retirement + deductions.pami + deductions.health + deductions.union);
  const totalPocket = roundMoney(grossRemunerative - totalDeductions);

  return {
    type: "final",
    monthlyEquivalent,
    seniorityPercent,
    values: {
      ...mensual.values,
      grossRemunerative,
      socialSecurityBase,
      healthAndUnionBase,
      deductions,
      totalDeductions,
      netRemunerative: totalPocket,
      totalPocket,
      sacProportional,
      unusedVacation,
      sacOnUnusedVacation
    },
    nonRemConcepts: [],
    steps: [
      ...mensual.steps,
      {
        label: "SAC proporcional",
        amount: sacProportional,
        formula: "Mejor remuneracion estimada / 12 x dias del semestre / 180",
        detail: `${fullMonthBase.toFixed(2)} / 12 x ${input.semesterDaysWorked} / 180`
      },
      {
        label: "Vacaciones no gozadas",
        amount: unusedVacation,
        formula: "Base vacaciones / 25 x dias pendientes",
        detail: `${fullMonthBase.toFixed(2)} / 25 x ${input.unusedVacationDays}`
      },
      {
        label: "SAC s/vacaciones no gozadas",
        amount: sacOnUnusedVacation,
        formula: "Vacaciones no gozadas / 12"
      }
    ],
    meta: {
      ...mensual.meta,
      fullMonthBase
    }
  };
}

export function calculateLiquidation(input, activeConvention = convention) {
  const precheck = validateLiquidationInput(input, activeConvention);
  if (precheck.errors.length) {
    throw new Error(precheck.errors.join(" | "));
  }

  let result;
  if (input.liquidationType === "vacaciones") {
    result = calculateVacations(input, precheck.category, activeConvention);
  } else if (input.liquidationType === "final") {
    result = calculateFinal(input, precheck.category, precheck.agreements, activeConvention);
  } else {
    result = calculateMensual(input, precheck.category, precheck.agreements, activeConvention);
  }

  const liquidation = buildStructuredLiquidation({
    input,
    category: precheck.category,
    scale: precheck.scale,
    agreements: precheck.agreements,
    result,
    activeConvention
  });

  liquidation.metadata.warnings = precheck.warnings;
  return liquidation;
}
