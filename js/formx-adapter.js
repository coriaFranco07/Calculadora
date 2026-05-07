function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function slugify(value) {
  return normalizeText(value)
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64) || "item";
}

function toNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value === null || value === undefined) return null;
  const normalized = String(value)
    .replace(/\s/g, "")
    .replace(/\$/g, "")
    .replace(/\./g, "")
    .replace(/,/g, ".");
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function getDocuments(formxPayload) {
  if (Array.isArray(formxPayload?.documents)) return formxPayload.documents;
  if (formxPayload?.document) return [formxPayload.document];
  return [];
}

function getMainDocument(formxPayload) {
  return getDocuments(formxPayload)[0] || {};
}

function getOcrPages(formxPayload) {
  return getDocuments(formxPayload)
    .flatMap((doc) => Array.isArray(doc?.ocr) ? doc.ocr : [])
    .filter(Boolean);
}

function getOcrText(formxPayload) {
  return getOcrPages(formxPayload).join("\n\n");
}

function getLineItems(formxPayload) {
  return getDocuments(formxPayload)
    .flatMap((doc) => Array.isArray(doc?.data?.line_items) ? doc.data.line_items : [])
    .filter((item) => item && typeof item === "object");
}

function pickMatch(text, regex, groupIndex = 1) {
  const match = String(text || "").match(regex);
  return match?.[groupIndex]?.trim() || null;
}

function uniqueBy(items, getKey) {
  const seen = new Set();
  return items.filter((item) => {
    const key = getKey(item);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function extractConvenio(formxPayload, ocrText) {
  const doc = getMainDocument(formxPayload);
  const data = doc.data || {};
  const metadata = doc.metadata || {};
  const numero = data.order_number || pickMatch(ocrText, /(?:CCT|Convenio\s+Colectivo)\s*(?:N[°ºro\.\s]*)?(\d+\s*\/\s*\d{4})/i);
  const actividad = pickMatch(ocrText, /Actividad\s*:\s*([^\n]+)/i) || data.vendor_name || null;
  const ambito = pickMatch(ocrText, /Zona de aplicaci[oó]n\s*:\s*([^\n]+)/i)
    || pickMatch(ocrText, /todo el territorio de la Rep[uú]blica Argentina/i, 0);
  const vigencia = pickMatch(ocrText, /Vigencia Desde\s*:\s*([^\n]+)/i)
    || pickMatch(ocrText, /APLICACI[OÓ]N\s*:\s*DESDE\s+([^\n]+)/i)
    || pickMatch(ocrText, /Vigencia\s*:\s*([^\n]+)/i);

  return {
    numero,
    nombre: numero ? `CCT ${numero}` : "CCT cargado desde FormX.ai",
    actividad,
    ambito,
    vigencia_detectada: vigencia || data.date || null,
    archivo_fuente: metadata.file_name || "formx.json",
    fuente: "FormX.ai",
    observaciones: "JSON importado desde FormX.ai. Revisar escalas, adicionales y vigencias antes de liquidar."
  };
}

function extractJornada(ocrText) {
  const horasSemanales = pickMatch(ocrText, /hasta\s+(\d+)\s+horas\s+semanales/i);
  const horasMensuales = pickMatch(ocrText, /(?:tope de|m[oó]dulo de|total de)\s+(\d+)\s+horas\s+mensuales/i)
    || pickMatch(ocrText, /(\d+)\s+horas\s+mensuales/i);
  return {
    horas_semanales: toNumber(horasSemanales),
    horas_mensuales: toNumber(horasMensuales),
    horas_diarias: pickMatch(ocrText, /(?:raz[oó]n de|de)\s+(\d+)\s+horas\s+diarias/i) ? toNumber(pickMatch(ocrText, /(?:raz[oó]n de|de)\s+(\d+)\s+horas\s+diarias/i)) : null,
    fuente_textual: pickMatch(ocrText, /(jornada laboral[^\n]+(?:\n[^\n]+){0,2})/i)
  };
}

function classifyLineItem(item) {
  const description = String(item.description || "").trim();
  const normalized = normalizeText(description);
  if (!description) return "ignorar";
  if (normalized.includes("subsidio") || normalized.includes("casamiento") || normalized.includes("nacimiento") || normalized.includes("fallecimiento") || normalized.includes("idiomas") || normalized.includes("titulo") || normalized.includes("caja") || normalized.includes("discapacitado")) return "subsidio";
  if (normalized.includes("antiguedad") || normalized.includes("computo")) return "regla";
  return "categoria";
}

function extractCategorias(formxPayload) {
  const lineItems = getLineItems(formxPayload);
  const categorias = lineItems
    .filter((item) => classifyLineItem(item) === "categoria")
    .map((item, index) => {
      const nombre = String(item.description || `Categoría ${index + 1}`).replace(/\s+/g, " ").trim();
      const basico = toNumber(item.unit_price ?? item.subtotal);
      return {
        id: slugify(nombre),
        nombre,
        basico_mensual: basico,
        valor: basico,
        tipo_valor: "mensual",
        grupo: null,
        fuente: "FormX.ai line_items",
        fuente_textual: item.description || null,
        requiere_revision: false
      };
    });
  return uniqueBy(categorias, (cat) => `${cat.id}_${cat.basico_mensual ?? ""}`);
}

function extractSubsidios(formxPayload) {
  return getLineItems(formxPayload)
    .filter((item) => classifyLineItem(item) === "subsidio")
    .map((item) => ({
      id: slugify(item.description),
      nombre: String(item.description || "Subsidio").replace(/\s+/g, " ").trim(),
      tipo: "monto_fijo",
      valor: toNumber(item.unit_price ?? item.subtotal),
      base: null,
      condicion: null,
      fuente: "FormX.ai line_items",
      fuente_textual: item.description || null
    }));
}

function extractAdicionalesFromOcr(ocrText) {
  const adicionales = [];
  const add = (item) => {
    if (!item?.nombre) return;
    adicionales.push({
      id: slugify(item.nombre),
      tipo: item.tipo || "porcentaje",
      valor: item.valor ?? null,
      base: item.base || null,
      condicion: item.condicion || null,
      fuente: "OCR FormX.ai",
      fuente_textual: item.fuente_textual || null,
      nombre: item.nombre
    });
  };

  if (/antig[uü]edad/i.test(ocrText)) {
    add({
      nombre: "Adicional por antigüedad",
      tipo: "porcentaje_por_anio",
      valor: 1,
      base: "salario_basico_computo_antiguedad",
      condicion: "1% por cada año de antigüedad, según escala del convenio",
      fuente_textual: pickMatch(ocrText, /(ADICIONAL POR ANTIG[ÜU]EDAD[\s\S]{0,450})/i)
    });
  }

  const zonaPatagonica = pickMatch(ocrText, /(?:Neuqu[eé]n|R[ií]o Negro|Chubut|Santa Cruz|Tierra del Fuego)[\s\S]{0,180}?(\d{1,2})\s*%/i);
  if (zonaPatagonica) {
    add({
      nombre: "Condiciones especiales región patagónica",
      tipo: "porcentaje",
      valor: toNumber(zonaPatagonica),
      base: "remuneracion",
      condicion: "Neuquén, Río Negro, Chubut, Santa Cruz y Tierra del Fuego",
      fuente_textual: pickMatch(ocrText, /(CONDICIONES ESPECIALES[^\n]*(?:\n[^\n]+){0,3})/i)
    });
  }

  const productividad = pickMatch(ocrText, /PRODUCTIVIDAD[\s\S]{0,180}?(\d{1,2})\s*%/i);
  if (productividad) {
    add({
      nombre: "Productividad mano de obra",
      tipo: "porcentaje",
      valor: toNumber(productividad),
      base: "facturacion_neta_mano_de_obra",
      condicion: "Sobre facturado sin impuestos, según artículo aplicable",
      fuente_textual: pickMatch(ocrText, /(PRODUCTIVIDAD[^\n]*(?:\n[^\n]+){0,5})/i)
    });
  }

  const servicioDiferencial = pickMatch(ocrText, /SERVICIO DIFERENCIAL[\s\S]{0,180}?PESOS\s+([A-Z\s]+|\d+(?:[,.]\d+)?)/i);
  if (servicioDiferencial) {
    add({
      nombre: "Servicio diferencial",
      tipo: "monto_fijo",
      valor: /CIEN/i.test(servicioDiferencial) ? 100 : toNumber(servicioDiferencial),
      base: null,
      condicion: "Provincias patagónicas según convenio",
      fuente_textual: pickMatch(ocrText, /(SERVICIO DIFERENCIAL[^\n]*(?:\n[^\n]+){0,3})/i)
    });
  }

  return uniqueBy(adicionales, (item) => item.id);
}

function extractReglasLiquidacion(ocrText) {
  return {
    antiguedad: {
      tipo: "porcentaje_por_anio",
      porcentaje_por_anio: /antig[uü]edad/i.test(ocrText) ? 1 : null,
      base_monto: toNumber(pickMatch(ocrText, /salario b[aá]sico[^$]{0,80}\$\s*(\d+(?:[,.]\d+)?)/i)) || 1100,
      tope_anios: toNumber(pickMatch(ocrText, /(\d+)\s+30\s*%/i)) || 30,
      fuente_textual: pickMatch(ocrText, /(ADICIONAL POR ANTIG[ÜU]EDAD[\s\S]{0,700})/i)
    },
    jornada: extractJornada(ocrText),
    zona_desfavorable: /Tierra del Fuego|Santa Cruz|Chubut|R[ií]o Negro|Neuqu[eé]n/i.test(ocrText) ? {
      porcentaje: toNumber(pickMatch(ocrText, /TREINTA POR CIENTO|30\s*%/i, 0)?.match(/30/)?.[0]) || 30,
      provincias: ["Neuquén", "Río Negro", "Chubut", "Santa Cruz", "Tierra del Fuego"],
      fuente_textual: pickMatch(ocrText, /(CONDICIONES ESPECIALES[^\n]*(?:\n[^\n]+){0,4})/i)
    } : null,
    horas_extra: {
      feriados_recargo_porcentaje: /100\s*%\s+de\s+recargo/i.test(ocrText) ? 100 : null,
      fuente_textual: pickMatch(ocrText, /(FERIADOS[^\n]*(?:\n[^\n]+){0,4})/i)
    },
    licencias: [],
    no_remunerativos: []
  };
}

function parseFormxJson(rawValue) {
  if (typeof rawValue === "object" && rawValue !== null) return rawValue;
  const text = String(rawValue || "").trim();
  if (!text) throw new Error("Pegá el JSON exportado por FormX.ai.");
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`El contenido pegado no es un JSON válido: ${error.message}`);
  }
}

function buildCalculatorFromFormX(rawValue) {
  const formxPayload = parseFormxJson(rawValue);
  const doc = getMainDocument(formxPayload);
  const ocrText = getOcrText(formxPayload);
  const categorias = extractCategorias(formxPayload);
  const subsidios = extractSubsidios(formxPayload);
  const adicionales = [...extractAdicionalesFromOcr(ocrText), ...subsidios];
  const convenio = extractConvenio(formxPayload, ocrText);
  const pageCount = Array.isArray(doc?.metadata?.page_no) ? doc.metadata.page_no.length : getOcrPages(formxPayload).length;

  return {
    version: new Date().toISOString().slice(0, 10),
    archivo_fuente: convenio.archivo_fuente,
    estado: "json_formx_importado",
    origen: {
      proveedor: "FormX.ai",
      request_id: formxPayload?.metadata?.request_id || doc?.metadata?.request_id || null,
      job_id: formxPayload?.metadata?.job_id || null,
      paginas_procesadas: pageCount || null
    },
    convenio,
    categorias,
    jornada: extractJornada(ocrText),
    adicionales,
    reglas_liquidacion: extractReglasLiquidacion(ocrText),
    texto_ocr_resumen: ocrText.slice(0, 4000),
    pendientes_revision: [
      "Verificar que cada categoría pertenezca al grupo/rama correcto",
      "Confirmar vigencia de la escala salarial importada",
      "Revisar categorías duplicadas o mal leídas por OCR",
      "Validar adicionales porcentuales y montos fijos antes de liquidar",
      "Completar reglas que no estén explícitas en el JSON de FormX"
    ],
    alertas: categorias.length ? [] : ["No se detectaron categorías en line_items de FormX"],
    nivel_confianza: categorias.length && ocrText ? 0.78 : 0.45,
    raw_formx: formxPayload
  };
}

export { buildCalculatorFromFormX, parseFormxJson };
