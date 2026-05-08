import { renderCalculator } from "./calculator-renderer.js";

const STORAGE_KEY = "gemini_codex_calculator_builder_v1";

const defaultState = () => ({
  cct: { normalized: null, fileName: "", diagnostics: null },
  scale: { normalized: null, fileName: "", diagnostics: null },
  merged: null,
  diagnostics: null,
  published: null,
});

let state = defaultState();

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (_error) {}
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    const parsed = JSON.parse(raw);
    return {
      ...defaultState(),
      ...parsed,
      cct: { ...defaultState().cct, ...(parsed?.cct || {}) },
      scale: { ...defaultState().scale, ...(parsed?.scale || {}) },
    };
  } catch (_error) {
    return defaultState();
  }
}

async function postFile(url, file) {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(url, { method: "POST", body: form });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || `Error HTTP ${response.status}`);
  }
  return data;
}

async function postFullFiles(cctFile, escalaFile) {
  const form = new FormData();
  form.append("cct_file", cctFile, cctFile.name);
  form.append("escala_file", escalaFile, escalaFile.name);
  const response = await fetch("/extract-full-calculator", { method: "POST", body: form });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || `Error HTTP ${response.status}`);
  }
  return data;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || `Error HTTP ${response.status}`);
  }
  return data;
}

async function publishCalculator(payload) {
  return postJson("/create-calculator-page", { payload });
}

function injectStyles() {
  if (document.querySelector("#ocr-builder-styles")) return;
  const style = document.createElement("style");
  style.id = "ocr-builder-styles";
  style.textContent = `
    .builder-shell{width:min(1280px,calc(100% - 36px));margin:24px auto 48px;display:grid;gap:20px}
    .builder-hero{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(320px,.8fr);gap:18px;padding:28px;border-radius:30px;background:linear-gradient(140deg,rgba(31,106,82,.12),transparent 34%),linear-gradient(180deg,#fffdf8,#f6efe4);border:1px solid rgba(27,35,33,.08);box-shadow:0 24px 60px rgba(27,35,33,.08)}
    .builder-hero h1{margin:0;font-size:clamp(32px,4vw,52px);line-height:.96;letter-spacing:-.04em}
    .builder-hero p{margin:14px 0 0;color:#5a6660;line-height:1.6;max-width:760px}
    .builder-kicker{margin:0 0 12px;color:#5a6660;text-transform:uppercase;letter-spacing:.16em;font-size:.74rem;font-weight:900}
    .builder-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:22px}
    .builder-btn,.builder-link{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:0 16px;border-radius:16px;border:1px solid rgba(27,35,33,.08);font-weight:900;text-decoration:none;cursor:pointer;font:inherit}
    .builder-btn{background:#fff;color:#1b2321}
    .builder-btn.primary{background:linear-gradient(135deg,#1f6a52,#2f8567);color:#fff;border-color:#1f6a52;box-shadow:0 14px 28px rgba(31,106,82,.18)}
    .builder-btn.secondary,.builder-link{background:rgba(255,255,255,.82);color:#1b2321}
    .builder-btn[disabled]{opacity:.5;cursor:not-allowed}
    .builder-side{display:grid;gap:12px}
    .builder-stat{padding:16px 18px;border-radius:20px;border:1px solid rgba(27,35,33,.08);background:rgba(255,255,255,.72)}
    .builder-stat small{display:block;color:#5a6660;text-transform:uppercase;letter-spacing:.08em;font-weight:800}
    .builder-stat strong{display:block;margin-top:8px;font-size:1.9rem;letter-spacing:-.04em}
    .builder-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
    .builder-step{padding:16px 18px;border-radius:18px;border:1px solid rgba(27,35,33,.08);background:rgba(255,255,255,.82)}
    .builder-step small{display:block;color:#5a6660;font-weight:900;text-transform:uppercase;letter-spacing:.08em}
    .builder-step strong{display:block;margin-top:10px}
    .builder-step span{display:block;margin-top:6px;color:#5a6660;font-size:.92rem}
    .builder-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
    .builder-card{display:grid;gap:16px;padding:22px;border-radius:24px;border:1px solid rgba(27,35,33,.08);background:rgba(255,255,255,.9);box-shadow:0 18px 40px rgba(27,35,33,.06)}
    .builder-card h2,.builder-card h3{margin:0}
    .builder-card p{margin:0;color:#5a6660;line-height:1.58}
    .builder-field{display:grid;gap:8px}
    .builder-field label{font-weight:900;color:#1b2321}
    .builder-field input[type="file"]{width:100%;border-radius:16px;border:1px solid rgba(27,35,33,.12);padding:14px;background:#fff;color:#1b2321;font:inherit}
    .builder-status{padding:12px 14px;border-radius:16px;background:#eef7f3;color:#1f6a52;font-weight:800}
    .builder-status.error{background:#fff0f0;color:#8b2e2e}
    .builder-status small{display:block;margin-top:6px;color:inherit;opacity:.78;font-weight:700}
    .builder-output{margin:0;padding:16px;border-radius:18px;background:#182120;color:#f6f0e6;min-height:220px;max-height:420px;overflow:auto;white-space:pre-wrap}
    .builder-merge{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:18px}
    .builder-summary{display:grid;gap:12px}
    .builder-preview{min-height:220px}
    .builder-note{padding:14px 16px;border-radius:18px;background:#fff7ef;border:1px solid rgba(195,93,39,.15);color:#5c4232;line-height:1.55}
    .builder-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
    .builder-meta div{padding:12px 14px;border-radius:16px;background:rgba(31,106,82,.05);border:1px solid rgba(31,106,82,.1)}
    .builder-meta small{display:block;color:#5a6660;text-transform:uppercase;letter-spacing:.08em;font-weight:800}
    .builder-meta strong{display:block;margin-top:6px}
    @media(max-width:1040px){.builder-hero,.builder-merge{grid-template-columns:1fr}.builder-steps,.builder-grid,.builder-meta{grid-template-columns:1fr 1fr}}
    @media(max-width:720px){.builder-shell{width:min(100% - 24px,1280px)}.builder-steps,.builder-grid,.builder-meta{grid-template-columns:1fr}}
  `;
  document.head.appendChild(style);
}

function createShell() {
  const shell = document.createElement("section");
  shell.className = "builder-shell";
  shell.innerHTML = `
    <section class="builder-hero">
      <div>
        <p class="builder-kicker">Gemini + Codex + Parser local</p>
        <h1>Crear calculadoras desde CCT y escalas en PDF</h1>
        <p>
          Carga el convenio y la escala. El backend extrae texto, lo compacta por chunks,
          analiza con Gemini y usa Codex/parser local para estructurar el JSON final.
        </p>
        <div class="builder-actions">
          <a class="builder-link" href="/">Volver al panel principal</a>
          <button class="builder-btn primary" type="button" data-merge disabled>Fusionar CCT + Escala</button>
          <button class="builder-btn" type="button" data-create disabled>Crear calculadora</button>
        </div>
      </div>
      <div class="builder-side">
        <div class="builder-stat">
          <small>Pipeline</small>
          <strong>PDF → Gemini → Codex</strong>
        </div>
        <div class="builder-stat">
          <small>Salida</small>
          <strong>JSON + HTML + dashboard</strong>
        </div>
      </div>
    </section>

    <section class="builder-steps">
      <article class="builder-step">
        <small>Paso 1</small>
        <strong>CCT</strong>
        <span data-step-cct>Esperando PDF</span>
      </article>
      <article class="builder-step">
        <small>Paso 2</small>
        <strong>Escala</strong>
        <span data-step-scale>Esperando PDF</span>
      </article>
      <article class="builder-step">
        <small>Paso 3</small>
        <strong>Fusion</strong>
        <span data-step-merge>Sin fusion</span>
      </article>
      <article class="builder-step">
        <small>Paso 4</small>
        <strong>Publicacion</strong>
        <span data-step-publish>Sin publicar</span>
      </article>
    </section>

    <section class="builder-grid">
      <article class="builder-card">
        <div>
          <h2>CCT</h2>
          <p>Sube el PDF del convenio. El sistema extrae markdown OCR, reglas, categorías y artículos relevantes.</p>
        </div>
        <div class="builder-field">
          <label for="cct-file">PDF del CCT</label>
          <input id="cct-file" type="file" accept=".pdf" data-file="cct">
        </div>
        <div class="builder-actions">
          <button class="builder-btn primary" type="button" data-process="cct">Procesar CCT</button>
          <button class="builder-btn secondary" type="button" data-clear="cct">Limpiar</button>
        </div>
        <div class="builder-status" data-status="cct">Esperando CCT...</div>
        <pre class="builder-output" data-output="cct">Sin datos normalizados.</pre>
      </article>

      <article class="builder-card">
        <div>
          <h2>Escala salarial</h2>
          <p>Sube el PDF de la escala vigente. El sistema detecta vigencia, categorías, básicos y acuerdos.</p>
        </div>
        <div class="builder-field">
          <label for="scale-file">PDF de la escala</label>
          <input id="scale-file" type="file" accept=".pdf" data-file="scale">
        </div>
        <div class="builder-actions">
          <button class="builder-btn primary" type="button" data-process="scale">Procesar Escala</button>
          <button class="builder-btn secondary" type="button" data-clear="scale">Limpiar</button>
        </div>
        <div class="builder-status" data-status="scale">Esperando escala...</div>
        <pre class="builder-output" data-output="scale">Sin datos normalizados.</pre>
      </article>
    </section>

    <section class="builder-card builder-merge">
      <div class="builder-summary">
        <div>
          <h3>Merge auditable</h3>
          <p>Une reglas del CCT con categorías y básicos de la escala antes de publicar.</p>
        </div>
        <div class="builder-meta">
          <div><small>Convenio</small><strong data-merge-convenio>Sin fusion</strong></div>
          <div><small>Categorias</small><strong data-merge-categorias>0</strong></div>
          <div><small>Adicionales</small><strong data-merge-adicionales>0</strong></div>
        </div>
        <div class="builder-note" data-merge-note>
          Procesa ambos PDFs y luego ejecuta la fusión para revisar el payload final antes de publicar.
        </div>
        <pre class="builder-output" data-output="merge">Sin payload fusionado.</pre>
      </div>
      <div class="builder-preview">
        <div class="builder-status" data-status="merge">Sin fusion.</div>
        <div data-calculator-preview></div>
      </div>
    </section>
  `;
  document.body.prepend(shell);
  return shell;
}

function setStatus(node, message, isError = false) {
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", Boolean(isError));
}

function updateStep(ref, message) {
  if (ref) ref.textContent = message;
}

function summarizeDiagnostics(diagnostics = {}) {
  const model = diagnostics.modelo_usado || diagnostics.model || "fallback local";
  const chunks = diagnostics.chunks_enviados ?? diagnostics.chunks ?? "-";
  const fallback = diagnostics.fallback_activo || diagnostics.fallback_used ? "fallback activo" : "sin fallback";
  const errors = Array.isArray(diagnostics.errores) ? diagnostics.errores.length : 0;
  return `Modelo: ${model}. Chunks: ${chunks}. ${fallback}.${errors ? ` Errores: ${errors}.` : ""}`;
}

function summarizeReview(payload = {}) {
  const alerts = Array.isArray(payload.alertas) ? payload.alertas.length : 0;
  const pending = Array.isArray(payload.pendientes_revision) ? payload.pendientes_revision.length : 0;
  return `Alertas: ${alerts}. Pendientes de revisión: ${pending}.`;
}

function updateButtons(refs) {
  const mergeReady = Boolean(state.cct.normalized && state.scale.normalized);
  const createReady = Boolean(state.merged);
  refs.mergeBtn.disabled = !mergeReady;
  refs.createBtn.disabled = !createReady;
  if (mergeReady && !state.merged) {
    setStatus(refs.statuses.merge, "Documentos listos. Presiona Fusionar CCT + Escala.");
    updateStep(refs.steps.merge, "Lista para fusion");
  }
}

function renderNormalized(kind, refs) {
  const block = state[kind];
  refs.outputs[kind].textContent = block.normalized ? JSON.stringify(block.normalized, null, 2) : "Sin datos normalizados.";
  const count = Array.isArray(block.normalized?.categorias) ? block.normalized.categorias.length : 0;

  if (block.normalized) {
    const diagnostics = block.diagnostics || block.normalized?.diagnostico_ia || {};
    const scales = Array.isArray(block.normalized?.escalas_salariales) ? block.normalized.escalas_salariales.length : 0;
    setStatus(
      refs.statuses[kind],
      `${kind === "cct" ? "CCT" : "Escala"} procesado con Gemini + Codex. Categorias: ${count}. Escalas: ${scales}. ${summarizeDiagnostics(diagnostics)} ${summarizeReview(block.normalized)}`
    );
    updateStep(refs.steps[kind], "Gemini completo");
  } else {
    setStatus(refs.statuses[kind], kind === "cct" ? "Esperando CCT..." : "Esperando escala...");
    updateStep(refs.steps[kind], kind === "cct" ? "Esperando PDF" : "Esperando PDF");
  }
}

function renderMerged(refs) {
  const payload = state.merged;
  refs.outputs.merge.textContent = payload ? JSON.stringify(payload, null, 2) : "Sin payload fusionado.";

  if (!payload) {
    refs.mergeConvenio.textContent = "Sin fusion";
    refs.mergeCategorias.textContent = "0";
    refs.mergeAdicionales.textContent = "0";
    refs.mergeNote.textContent = "Procesa ambos PDFs y luego ejecuta la fusión para revisar el payload final antes de publicar.";
    refs.preview.innerHTML = "";
    if (!state.cct.normalized || !state.scale.normalized) {
      setStatus(refs.statuses.merge, "Sin fusion.");
      updateStep(refs.steps.merge, "Sin fusion");
    }
    return;
  }

  refs.mergeConvenio.textContent = payload?.convenio?.nombre || "Convenio fusionado";
  refs.mergeCategorias.textContent = String(payload?.categorias?.length || 0);
  refs.mergeAdicionales.textContent = String(payload?.adicionales?.length || 0);
  const firstPending = payload?.pendientes_revision?.[0];
  refs.mergeNote.textContent = firstPending || "Payload final listo. Revisa vigencia, categorias y adicionales antes de publicar.";
  const diagnostics = state.diagnostics || payload?.diagnostico_ia || {};
  setStatus(refs.statuses.merge, `Payload final listo para publicar. ${summarizeDiagnostics(diagnostics)} ${summarizeReview(payload)}`);
  updateStep(refs.steps.merge, "Fusion completa");

  refs.preview.innerHTML = "";
  renderCalculator(refs.preview, payload);
}

function renderPublished(refs) {
  if (!state.published) {
    updateStep(refs.steps.publish, "Sin publicar");
    return;
  }
  updateStep(refs.steps.publish, "Calculadora publicada");
  setStatus(refs.statuses.merge, `Calculadora creada. URL: ${state.published.url}`);
}

function renderAll(refs) {
  renderNormalized("cct", refs);
  renderNormalized("scale", refs);
  renderMerged(refs);
  renderPublished(refs);
  updateButtons(refs);
}

function clearKind(kind, refs) {
  state[kind] = { normalized: null, fileName: "", diagnostics: null };
  state.merged = null;
  state.diagnostics = null;
  state.published = null;
  refs.files[kind].value = "";
  saveState();
  renderAll(refs);
}

async function processKind(kind, refs) {
  const file = refs.files[kind].files?.[0];
  const label = kind === "cct" ? "CCT" : "Escala";
  if (!file) {
    setStatus(refs.statuses[kind], `Carga un PDF para ${label}.`, true);
    return;
  }

  setStatus(refs.statuses[kind], `Procesando ${label} con Gemini + Codex. Extrayendo texto, limpiando y enviando chunks...`);

  try {
    const response = await postFile(kind === "cct" ? "/extract-cct-pdf" : "/extract-escala-pdf", file);
    state[kind] = {
      normalized: response.result,
      fileName: file.name,
      diagnostics: response.diagnostics || response.result?.diagnostico_ia || null,
    };
    state.merged = null;
    state.diagnostics = null;
    state.published = null;
    saveState();
    renderAll(refs);
  } catch (error) {
    setStatus(refs.statuses[kind], error?.message || `No pude procesar ${label}.`, true);
  }
}

async function mergeSources(refs) {
  if (!state.cct.normalized || !state.scale.normalized) return;
  setStatus(refs.statuses.merge, "Fusionando CCT y escala con Gemini + Codex...");
  try {
    const cctFile = refs.files.cct.files?.[0];
    const escalaFile = refs.files.scale.files?.[0];
    const response = cctFile && escalaFile
      ? await postFullFiles(cctFile, escalaFile)
      : await postJson("/merge-calculator-payload", {
          cct_json: state.cct.normalized,
          escala_json: state.scale.normalized,
        });
    if (response.documents?.cct?.result) {
      state.cct = {
        normalized: response.documents.cct.result,
        fileName: cctFile?.name || state.cct.fileName,
        diagnostics: response.documents.cct.diagnostics || null,
      };
    }
    if (response.documents?.escala?.result) {
      state.scale = {
        normalized: response.documents.escala.result,
        fileName: escalaFile?.name || state.scale.fileName,
        diagnostics: response.documents.escala.diagnostics || null,
      };
    }
    state.merged = response.result;
    state.diagnostics = response.diagnostics || null;
    state.published = null;
    saveState();
    renderAll(refs);
  } catch (error) {
    setStatus(refs.statuses.merge, error?.message || "No pude fusionar los documentos.", true);
  }
}

async function createCalculator(refs) {
  if (!state.merged) return;
  refs.createBtn.disabled = true;
  setStatus(refs.statuses.merge, "Publicando calculadora...");
  try {
    const result = await publishCalculator(state.merged);
    state.published = result;
    saveState();
    renderAll(refs);
    refs.mergeNote.innerHTML = `Calculadora publicada. <a href="${result.url}">Abrir HTML</a> · <a href="/">Ver dashboard</a>`;
  } catch (error) {
    setStatus(refs.statuses.merge, error?.message || "No pude crear la calculadora.", true);
  } finally {
    updateButtons(refs);
  }
}

function init() {
  state = loadState();
  injectStyles();
  const shell = createShell();

  const refs = {
    files: {
      cct: shell.querySelector('[data-file="cct"]'),
      scale: shell.querySelector('[data-file="scale"]'),
    },
    statuses: {
      cct: shell.querySelector('[data-status="cct"]'),
      scale: shell.querySelector('[data-status="scale"]'),
      merge: shell.querySelector('[data-status="merge"]'),
    },
    outputs: {
      cct: shell.querySelector('[data-output="cct"]'),
      scale: shell.querySelector('[data-output="scale"]'),
      merge: shell.querySelector('[data-output="merge"]'),
    },
    steps: {
      cct: shell.querySelector("[data-step-cct]"),
      scale: shell.querySelector("[data-step-scale]"),
      merge: shell.querySelector("[data-step-merge]"),
      publish: shell.querySelector("[data-step-publish]"),
    },
    mergeBtn: shell.querySelector("[data-merge]"),
    createBtn: shell.querySelector("[data-create]"),
    preview: shell.querySelector("[data-calculator-preview]"),
    mergeConvenio: shell.querySelector("[data-merge-convenio]"),
    mergeCategorias: shell.querySelector("[data-merge-categorias]"),
    mergeAdicionales: shell.querySelector("[data-merge-adicionales]"),
    mergeNote: shell.querySelector("[data-merge-note]"),
  };

  shell.querySelector('[data-process="cct"]').addEventListener("click", () => processKind("cct", refs));
  shell.querySelector('[data-process="scale"]').addEventListener("click", () => processKind("scale", refs));
  shell.querySelector('[data-clear="cct"]').addEventListener("click", () => clearKind("cct", refs));
  shell.querySelector('[data-clear="scale"]').addEventListener("click", () => clearKind("scale", refs));
  refs.mergeBtn.addEventListener("click", () => mergeSources(refs));
  refs.createBtn.addEventListener("click", () => createCalculator(refs));

  renderAll(refs);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
