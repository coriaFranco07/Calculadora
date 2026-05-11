const CCT_STORAGE_KEY = "cct_calculator_draft_v2";
let lastExtractedJson = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

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
    .slice(0, 48) || "categoria";
}

function extractCategories(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  const categoryHints = ["operario", "oficial", "administrativo", "categoria", "chofer", "cadete", "medio oficial"];
  return lines
    .filter((line) => categoryHints.some((hint) => normalizeText(line).includes(normalizeText(hint))))
    .slice(0, 18)
    .map((line, index) => ({
      id: slugify(line) || `cat_${index + 1}`,
      nombre: line.slice(0, 120),
      fuente_textual: line.slice(0, 180)
    }));
}

function extractPercentages(text) {
  const matches = [...String(text || "").matchAll(/(.{0,55})(\d{1,2}(?:[,.]\d{1,2})?)\s*%(.{0,55})/g)];
  return matches.slice(0, 18).map((match, index) => ({
    nombre: `Adicional detectado ${index + 1}`,
    tipo: "porcentaje",
    valor: Number(String(match[2]).replace(",", ".")),
    base: null,
    condicion: null,
    fuente_textual: `${match[1]}${match[2]}%${match[3]}`.replace(/\s+/g, " ").trim()
  }));
}

function buildCctJson(rawText, fileName = "CCT.pdf") {
  const text = String(rawText || "").trim();
  return {
    version: new Date().toISOString().slice(0, 10),
    archivo_fuente: fileName,
    estado: text ? "borrador_local" : "sin_texto",
    convenio: {
      nombre: "CCT cargado por usuario",
      actividad: null,
      ambito: null,
      vigencia_detectada: null,
      observaciones: "Borrador local de respaldo. Revisar con IA o liquidador antes de usar."
    },
    categorias: extractCategories(text),
    jornada: {
      horas_mensuales: text.match(/200\s*horas/i) ? 200 : null,
      dias_mensuales: text.match(/25\s*d[ii]as/i) ? 25 : null,
      horas_diarias: null,
      fuente_textual: null
    },
    adicionales: extractPercentages(text),
    reglas_liquidacion: {
      antiguedad: null,
      zona_desfavorable: null,
      presentismo: null,
      horas_extra: null,
      licencias: [],
      no_remunerativos: []
    },
    pendientes_revision: [
      "Confirmar vigencia salarial",
      "Cargar o validar escalas por categoria",
      "Validar adicionales convencionales",
      "Validar jornada y proporcionalidad",
      "Revisar formulas antes de liquidar"
    ],
    alertas: ["JSON generado como borrador local por fallback"],
    nivel_confianza: 0.35
  };
}

function saveDraft(payload) {
  lastExtractedJson = payload;
  try {
    localStorage.setItem(CCT_STORAGE_KEY, JSON.stringify(payload));
  } catch (_error) {
    // Local storage can be unavailable in private contexts.
  }
}

async function analyzePdfWithBackend(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/extract-cct-pdf", {
    method: "POST",
    body: formData
  });

  const rawText = await response.text();
  let payload = null;
  try {
    payload = rawText ? JSON.parse(rawText) : null;
  } catch (_error) {
    payload = null;
  }

  if (!response.ok) {
    const detail = payload?.detail || rawText || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return payload?.result || payload;
}

function buildAnalysisStatus(payload) {
  const state = String(payload?.estado || "").toLowerCase();
  const alertCount = Array.isArray(payload?.alertas) ? payload.alertas.length : 0;

  if (state.includes("parcial")) {
    return "PDF analizado con recuperacion parcial. Revisa el JSON antes de crear la calculadora.";
  }

  if (state.includes("fallback")) {
    return "PDF analizado con extractor local de respaldo. Revisalo manualmente antes de usarlo.";
  }

  if (alertCount > 0) {
    return `PDF analizado con ${alertCount} alerta(s). Revisa el JSON antes de crear la calculadora.`;
  }

  return "PDF analizado. Ya podes crear la calculadora.";
}

function injectStyles() {
  if (document.querySelector("#cct-loader-styles")) return;
  const style = document.createElement("style");
  style.id = "cct-loader-styles";
  style.textContent = `
    .cct-loader-shell { margin: 22px auto; max-width: 1180px; border: 1px solid rgba(31,106,82,.14); border-radius: 30px; overflow: hidden; background: linear-gradient(180deg, rgba(255,253,248,.98), rgba(255,248,237,.96)); box-shadow: 0 22px 70px rgba(15,21,19,.10); }
    .cct-loader-hero { padding: 30px; background: radial-gradient(circle at 15% 10%, rgba(208,98,36,.18), transparent 34%), linear-gradient(135deg, rgba(31,106,82,.14), rgba(208,98,36,.10)); display: grid; gap: 12px; }
    .cct-loader-hero small { color: #53615d; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; }
    .cct-loader-hero h2 { margin: 0; font-size: clamp(1.9rem, 3vw, 3.2rem); color: #1b2321; letter-spacing: -.045em; }
    .cct-loader-hero p { margin: 0; max-width: 820px; color: #53615d; line-height: 1.55; }
    .cct-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding: 18px 22px 0; }
    .cct-flow-step { border: 1px solid rgba(27,35,33,.08); border-radius: 18px; padding: 12px; background: rgba(255,255,255,.68); color: #53615d; font-weight: 800; }
    .cct-flow-step.is-active { background: rgba(31,106,82,.11); color: #1f6a52; border-color: rgba(31,106,82,.22); }
    .cct-loader-grid { display: grid; grid-template-columns: minmax(0, .9fr) minmax(360px, 1.1fr); gap: 18px; padding: 22px; }
    .cct-loader-card { border: 1px solid rgba(27,35,33,.08); border-radius: 24px; background: rgba(255,255,255,.80); padding: 18px; }
    .cct-loader-card h3 { margin: 0 0 10px; color: #1b2321; }
    .cct-dropzone { position: relative; display: grid; place-items: center; min-height: 235px; border: 2px dashed rgba(31,106,82,.25); border-radius: 22px; background: rgba(31,106,82,.055); text-align: center; padding: 24px; cursor: pointer; transition: border-color .15s ease, background .15s ease; }
    .cct-dropzone:hover { border-color: rgba(208,98,36,.38); background: rgba(208,98,36,.055); }
    .cct-dropzone input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
    .cct-dropzone strong { display: block; font-size: 1.15rem; color: #1b2321; margin-bottom: 6px; }
    .cct-dropzone span { color: #53615d; }
    .cct-status { margin-top: 14px; padding: 13px 14px; border-radius: 16px; background: rgba(31,106,82,.08); color: #1f6a52; font-weight: 800; }
    .cct-status.is-error { background: rgba(160,43,43,.10); color: #8d2929; }
    .cct-loader-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .cct-loader-button { border: 0; border-radius: 15px; padding: 12px 15px; background: linear-gradient(135deg, #1f6a52, #d06224); color: white; font-weight: 900; cursor: pointer; }
    .cct-loader-button.secondary { background: rgba(31,106,82,.10); color: #1f6a52; }
    .cct-loader-button[disabled] { opacity: .48; cursor: not-allowed; filter: grayscale(.2); }
    .cct-loader-output { white-space: pre-wrap; overflow: auto; max-height: 500px; padding: 14px; border-radius: 16px; background: #1b2321; color: #f7efe2; font-size: .86rem; line-height: 1.45; }
    .generated-calculator { margin-top: 16px; padding: 16px; border-radius: 20px; background: rgba(31,106,82,.08); border: 1px solid rgba(31,106,82,.16); }
    .generated-calculator h4 { margin: 0 0 8px; color: #1f6a52; }
    .generated-calculator ul { margin: 8px 0 0; padding-left: 20px; }
    @media (max-width: 900px) { .cct-loader-grid, .cct-flow { grid-template-columns: 1fr; } }
  `;
  document.head.append(style);
}

function setFlowStep(shell, index) {
  shell.querySelectorAll(".cct-flow-step").forEach((item, itemIndex) => {
    item.classList.toggle("is-active", itemIndex <= index);
  });
}

function renderGeneratedCalculator(container, payload) {
  const convenio = payload?.convenio || {};
  const categorias = Array.isArray(payload?.categorias) ? payload.categorias : [];
  const adicionales = Array.isArray(payload?.adicionales) ? payload.adicionales : [];
  container.innerHTML = `
    <div class="generated-calculator">
      <h4>Calculadora creada</h4>
      <p><strong>Convenio:</strong> ${escapeHtml(convenio.nombre || "CCT cargado")}</p>
      <p><strong>Categorias detectadas:</strong> ${categorias.length}</p>
      <p><strong>Adicionales detectados:</strong> ${adicionales.length}</p>
      <ul>
        ${categorias.slice(0, 8).map((cat) => `<li>${escapeHtml(cat.nombre || cat.id || "Categoria")}</li>`).join("") || "<li>Sin categorias detectadas automaticamente</li>"}
      </ul>
    </div>
  `;
}

function createShell() {
  const existing = document.querySelector("#cct-loader-shell");
  if (existing) return existing;

  const shell = document.createElement("section");
  shell.id = "cct-loader-shell";
  shell.className = "cct-loader-shell";
  shell.innerHTML = `
    <div class="cct-loader-hero">
      <small>Constructor IA de calculadoras</small>
      <h2>Subi un CCT en PDF y crea la calculadora</h2>
      <p>Flujo: subis el PDF, la IA lo analiza, revisas el JSON generado y presionas "Crear calculadora" para dejar una calculadora preliminar basada en ese convenio.</p>
    </div>
    <div class="cct-flow">
      <div class="cct-flow-step is-active">1. Subir PDF</div>
      <div class="cct-flow-step">2. Analizando PDF</div>
      <div class="cct-flow-step">3. Crear calculadora</div>
      <div class="cct-flow-step">4. Calculadora creada</div>
    </div>
    <div class="cct-loader-grid">
      <article class="cct-loader-card">
        <h3>1. Cargar CCT en PDF</h3>
        <label class="cct-dropzone">
          <input type="file" accept="application/pdf,.pdf" data-cct-pdf>
          <div>
            <strong>Arrastra o selecciona el PDF del CCT</strong>
            <span>La IA extraera categorias, jornada, adicionales y reglas liquidables.</span>
          </div>
        </label>
        <div class="cct-status" data-cct-status>Esperando PDF del CCT...</div>
        <div class="cct-loader-actions">
          <button type="button" class="cct-loader-button" data-cct-create disabled>Crear calculadora</button>
          <button type="button" class="cct-loader-button secondary" data-cct-example>Cargar ejemplo sin PDF</button>
        </div>
        <div data-cct-calculator-preview></div>
      </article>
      <article class="cct-loader-card">
        <h3>2. Resultado del analisis IA</h3>
        <pre class="cct-loader-output" data-cct-output>Esperando analisis del PDF...</pre>
      </article>
    </div>
  `;

  const main = document.querySelector("main") || document.body;
  main.prepend(shell);
  return shell;
}

function setStatus(statusNode, message, isError = false) {
  statusNode.textContent = message;
  statusNode.classList.toggle("is-error", isError);
}

async function handlePdf(file, refs) {
  refs.create.disabled = true;
  refs.preview.innerHTML = "";
  setFlowStep(refs.shell, 1);
  setStatus(refs.status, "Analizando PDF... enviando archivo al backend");
  refs.output.textContent = "Analizando PDF...";

  try {
    const payload = await analyzePdfWithBackend(file);
    saveDraft(payload);
    lastExtractedJson = payload;
    refs.output.textContent = JSON.stringify(payload, null, 2);
    refs.create.disabled = false;
    setFlowStep(refs.shell, 2);
    setStatus(refs.status, buildAnalysisStatus(payload));
  } catch (error) {
    setFlowStep(refs.shell, 0);
    const detail = error?.message || String(error);
    refs.output.textContent = `No pude analizar el PDF.\n\nDetalle tecnico:\n${detail}`;
    setStatus(refs.status, `No pude analizar el PDF: ${detail}`, true);
  }
}

function initCctLoader() {
  injectStyles();


  refs.file.addEventListener("change", async () => {
    const file = refs.file.files?.[0];
    if (!file) return;
    await handlePdf(file, refs);
  });

  refs.create.addEventListener("click", () => {
    if (!lastExtractedJson) return;
    setFlowStep(shell, 3);
    saveDraft({ ...lastExtractedJson, estado: "calculadora_creada" });
    setStatus(refs.status, "Calculadora creada desde el CCT. Revisa categorias y completa escalas pendientes.");
    renderGeneratedCalculator(refs.preview, lastExtractedJson);
  });

  refs.example.addEventListener("click", () => {
    const text = `CCT ejemplo Alimentacion
Categoria Operario: tareas generales.
Categoria Operario Calificado: responsabilidad en elaboracion.
Categoria Administrativo I: trabajos simples.
Adicional zona desfavorable 20%.
Antiguedad 1% por ano.
Jornada mensual 200 horas.`;
    const payload = buildCctJson(text, "ejemplo-cct.txt");
    saveDraft(payload);
    refs.output.textContent = JSON.stringify(payload, null, 2);
    refs.create.disabled = false;
    setFlowStep(shell, 2);
    setStatus(refs.status, "Ejemplo analizado. Ya podes crear la calculadora.");
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initCctLoader);
} else {
  initCctLoader();
}

export { buildCctJson };
