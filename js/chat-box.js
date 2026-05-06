import { createGeminiClient } from "./gemini-client.js";

const CHAT_STATE = {
  open: false,
  busy: false,
  messages: [],
  documents: []
};

const STORAGE_KEY = "cct244_chat_documents_v1";
const MAX_CONTEXT_CHUNKS = 5;
const MAX_CHUNK_LENGTH = 1400;
<<<<<<< HEAD
const PDFJS_VERSION = "4.3.136";
const PDFJS_SCRIPT =
  "/node_modules/pdfjs-dist/build/pdf.min.mjs";
const PDFJS_WORKER =
  "/node_modules/pdfjs-dist/build/pdf.worker.min.mjs";
=======
const PDFJS_MODULE = "/node_modules/pdfjs-dist/build/pdf.mjs";
const PDFJS_WORKER = "/node_modules/pdfjs-dist/build/pdf.worker.mjs";
>>>>>>> 85ea56885623af1650df5881cd82e55b2bc486de

let pdfJsLoadingPromise = null;

const SUGGESTED_PROMPTS = [
  "¿Por qué bloqueó la exportación?",
  "Explicame la Serie 990",
  "¿Qué falta en la revista?",
  "¿Qué dice el PDF sobre esto?",
  "¿Qué debería corregir primero?"
];

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function tokenize(value) {
  return normalizeText(value)
    .split(/[^a-z0-9ñ]+/i)
    .map((item) => item.trim())
    .filter((item) => item.length >= 4);
}

function getContext() {
  if (typeof window.getPayrollAuditContext === "function") {
    return window.getPayrollAuditContext() || {};
  }
  return {};
}

function getAuditSummary(context) {
  const audit = context.auditoria || context.audit || null;
  return audit?.resumenIA || audit?.geminiPayload || null;
}

function safeLocalStorage() {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch (_error) {
    return null;
  }
}

function persistDocuments() {
  const storage = safeLocalStorage();
  if (!storage) return;
  const lightweight = CHAT_STATE.documents.map((doc) => ({
    id: doc.id,
    name: doc.name,
    addedAt: doc.addedAt,
    chunks: doc.chunks
  }));
  storage.setItem(STORAGE_KEY, JSON.stringify(lightweight));
}

function restoreDocuments() {
  const storage = safeLocalStorage();
  if (!storage) return;
  try {
    const raw = storage.getItem(STORAGE_KEY);
    CHAT_STATE.documents = raw ? JSON.parse(raw) : [];
  } catch (_error) {
    CHAT_STATE.documents = [];
  }
}

function makeChunks(text, sourceName) {
  const cleanText = String(text || "").replace(/\s+/g, " ").trim();
  if (!cleanText) return [];

  const chunks = [];
  for (let index = 0; index < cleanText.length; index += MAX_CHUNK_LENGTH) {
    chunks.push({
      source: sourceName,
      index: chunks.length + 1,
      text: cleanText.slice(index, index + MAX_CHUNK_LENGTH)
    });
  }
  return chunks.slice(0, 80);
}

function rankDocumentChunks(question) {
  const terms = tokenize(question);
  if (!terms.length) return [];

  return CHAT_STATE.documents
    .flatMap((doc) => doc.chunks.map((chunk) => ({ ...chunk, documentName: doc.name })))
    .map((chunk) => {
      const normalizedChunk = normalizeText(chunk.text);
      const score = terms.reduce((total, term) => total + (normalizedChunk.includes(term) ? 1 : 0), 0);
      return { ...chunk, score };
    })
    .filter((chunk) => chunk.score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, MAX_CONTEXT_CHUNKS)
    .map((chunk) => ({
      fuente: chunk.documentName || chunk.source,
      fragmento: chunk.index,
      texto: chunk.text
    }));
}

function buildLocalSummary(context) {
  const audit = context.auditoria || context.audit;
  if (!audit) return "Todavía no hay auditoría preventiva calculada.";

  const status = audit.estado || audit.status || audit.summary?.status || "sin estado";
  const score = audit.score ?? audit.summary?.score ?? "s/d";
  const counters = audit.counters || {};
  const findings = audit.findings || [];
  const topFindings = findings.slice(0, 5).map((item) => `• ${item.code || item.codigo || "ALERTA"}: ${item.message || item.mensaje || item.title || "Sin detalle"}`);

  return [
    `Estado: ${status}`,
    `Score preventivo: ${score}/100`,
    `Blockers: ${counters.blockers ?? counters.error ?? 0} · Critical: ${counters.critical ?? 0} · Warnings: ${counters.warning ?? 0}`,
    topFindings.length ? `Hallazgos principales:\n${topFindings.join("\n")}` : "Sin hallazgos determinísticos relevantes."
  ].join("\n");
}

function buildPayload(question, context) {
  const summary = getAuditSummary(context) || {};
  return {
    periodo: summary.periodo || context.liquidacion?.metadata?.input?.liquidationDate?.slice(0, 7) || "",
    resumen_totalizadores: summary.resumen_totalizadores || {},
    resumen_revista: summary.resumen_revista || {},
    errores_detectados: summary.errores_detectados || [],
    pregunta_usuario: question,
    contexto_documental: rankDocumentChunks(question)
  };
}

async function ensurePdfJs() {
  if (!pdfJsLoadingPromise) {
    pdfJsLoadingPromise = import(PDFJS_MODULE)
      .then((pdfjs) => {
        pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        return pdfjs;
      })
      .catch((error) => {
        throw new Error(`No se pudo cargar PDF.js local. Ejecutá npm install y verificá node_modules. Detalle: ${error.message || error}`);
      });
  }
  return pdfJsLoadingPromise;
}

function injectStyles() {
  if (document.querySelector("#ai-chat-box-styles")) return;
  const style = document.createElement("style");
  style.id = "ai-chat-box-styles";
  style.textContent = `
    .ai-chat-launcher {
      position: fixed; right: 22px; bottom: 22px; z-index: 120; display: inline-flex; align-items: center; gap: 10px;
      padding: 13px 18px; border: 0; border-radius: 999px; background: linear-gradient(135deg, var(--accent, #d06224), #e18a41);
      color: #fff; box-shadow: 0 18px 42px rgba(54, 40, 22, 0.28); font-weight: 800; cursor: pointer;
    }
    .ai-chat-panel {
      position: fixed; right: 22px; bottom: 84px; z-index: 121; width: min(460px, calc(100vw - 28px)); max-height: min(760px, calc(100vh - 112px));
      display: none; grid-template-rows: auto 1fr auto; overflow: hidden; border-radius: 24px; border: 1px solid var(--line-strong, rgba(27, 35, 33, 0.16));
      background: rgba(255, 253, 248, 0.98); box-shadow: 0 28px 80px rgba(15, 21, 19, 0.24); backdrop-filter: blur(16px);
    }
    .ai-chat-panel.is-open { display: grid; }
    .ai-chat-header { display: flex; justify-content: space-between; gap: 14px; padding: 18px 18px 14px; border-bottom: 1px solid var(--line, rgba(27, 35, 33, 0.08)); }
    .ai-chat-header strong { display: block; font-size: 1.05rem; }
    .ai-chat-header small, .ai-chat-docs small { color: var(--muted, #53615d); line-height: 1.35; }
    .ai-chat-close { width: 34px; height: 34px; border: 1px solid var(--line, rgba(27, 35, 33, 0.08)); border-radius: 50%; background: rgba(255, 255, 255, 0.78); cursor: pointer; font-weight: 900; }
    .ai-chat-messages { display: grid; align-content: start; gap: 12px; padding: 16px; overflow: auto; min-height: 260px; }
    .ai-chat-message { max-width: 92%; padding: 12px 14px; border-radius: 16px; border: 1px solid var(--line, rgba(27, 35, 33, 0.08)); line-height: 1.45; white-space: pre-wrap; font-size: 0.94rem; }
    .ai-chat-message.is-user { justify-self: end; background: rgba(208, 98, 36, 0.13); border-color: rgba(208, 98, 36, 0.24); }
    .ai-chat-message.is-assistant { justify-self: start; background: rgba(255, 255, 255, 0.84); }
    .ai-chat-docs { padding: 12px 16px; border-bottom: 1px solid var(--line, rgba(27, 35, 33, 0.08)); background: rgba(31, 106, 82, 0.06); }
    .ai-chat-doc-row { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 8px; }
    .ai-chat-doc-upload { display: inline-flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 999px; border: 1px solid var(--line, rgba(27, 35, 33, 0.08)); background: rgba(255,255,255,.82); cursor: pointer; font-weight: 800; font-size: .84rem; }
    .ai-chat-doc-upload input { display: none; }
    .ai-chat-doc-list { display: grid; gap: 6px; margin-top: 8px; }
    .ai-chat-doc-item { display: flex; justify-content: space-between; gap: 8px; padding: 7px 9px; border-radius: 10px; background: rgba(255,255,255,.74); border: 1px solid var(--line, rgba(27,35,33,.08)); font-size: .82rem; }
    .ai-chat-doc-clear { border: 0; background: transparent; color: var(--accent-deep, #a54516); font-weight: 800; cursor: pointer; }
    .ai-chat-suggestions { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 16px 12px; }
    .ai-chat-chip { border: 1px solid var(--line, rgba(27, 35, 33, 0.08)); border-radius: 999px; padding: 8px 10px; background: rgba(255, 255, 255, 0.78); color: var(--muted, #53615d); font-size: 0.82rem; cursor: pointer; }
    .ai-chat-form { display: grid; grid-template-columns: 1fr auto; gap: 10px; padding: 14px 16px 16px; border-top: 1px solid var(--line, rgba(27, 35, 33, 0.08)); }
    .ai-chat-input { width: 100%; min-height: 44px; max-height: 120px; resize: vertical; border-radius: 14px; border: 1px solid var(--line, rgba(27, 35, 33, 0.08)); padding: 11px 12px; background: #fffdf8; color: var(--text, #1b2321); font: inherit; }
    .ai-chat-send { align-self: end; border: 0; border-radius: 14px; padding: 12px 14px; background: var(--green, #1f6a52); color: #fff; font-weight: 800; cursor: pointer; }
    .ai-chat-send[disabled] { opacity: 0.55; cursor: not-allowed; }
    @media (max-width: 560px) { .ai-chat-launcher { right: 14px; bottom: 14px; } .ai-chat-panel { right: 14px; bottom: 74px; } }
  `;
  document.head.append(style);
}

function renderMessages(container) {
  container.innerHTML = CHAT_STATE.messages
    .map((message) => `<article class="ai-chat-message is-${message.role}">${escapeHtml(message.text)}</article>`)
    .join("");
  container.scrollTop = container.scrollHeight;
}

function renderDocuments(refs) {
  if (!refs.docList || !refs.docStatus) return;
  refs.docStatus.textContent = CHAT_STATE.documents.length
    ? `${CHAT_STATE.documents.length} documento(s) cargado(s). El chat usará fragmentos relevantes.`
    : "Sin PDFs cargados. Podés cargar CCT, LCT, acuerdos o manuales AFIP.";
  refs.docList.innerHTML = CHAT_STATE.documents
    .map((doc) => `<div class="ai-chat-doc-item"><span>${escapeHtml(doc.name)}</span><small>${doc.chunks.length} fragmentos</small></div>`)
    .join("");
}

function addMessage(role, text, refs) {
  CHAT_STATE.messages.push({ role, text });
  renderMessages(refs.messages);
}

async function extractPdfText(file) {
  const pdfjs = await ensurePdfJs();
  const buffer = await file.arrayBuffer();
  const pdf = await pdfjs.getDocument({ data: buffer }).promise;
  const pages = [];
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    const text = content.items.map((item) => item.str).join(" ");
    pages.push(`Página ${pageNumber}: ${text}`);
  }
  return pages.join("\n\n");
}

async function handleDocumentUpload(files, refs) {
  const selectedFiles = Array.from(files || []).filter((file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
  if (!selectedFiles.length) {
    addMessage("assistant", "Seleccioná uno o más archivos PDF para cargar como referencia.", refs);
    return;
  }

  for (const file of selectedFiles) {
    addMessage("assistant", `Leyendo PDF: ${file.name}…`, refs);
    const text = await extractPdfText(file);
    CHAT_STATE.documents.push({
      id: `${Date.now()}-${file.name}`,
      name: file.name,
      addedAt: new Date().toISOString(),
      chunks: makeChunks(text, file.name)
    });
  }
  persistDocuments();
  renderDocuments(refs);
  addMessage("assistant", "PDF cargado. Ya podés preguntarme usando ese documento como referencia.", refs);
}

async function askGemini(question) {
  const context = getContext();
  const hasDocuments = CHAT_STATE.documents.length > 0;
  if (!context.liquidacion && !context.auditoria && !hasDocuments) {
    return "Primero calculá una liquidación o cargá un PDF de referencia para que pueda analizar contexto.";
  }

  const client = createGeminiClient("");
  try {
    const health = await client.health();
    if (!health.ai_enabled) {
      const docMatches = rankDocumentChunks(question);
      const docText = docMatches.length
        ? `\n\nFragmentos documentales encontrados:\n${docMatches.map((item) => `• ${item.fuente} · fragmento ${item.fragmento}: ${item.texto.slice(0, 350)}...`).join("\n")}`
        : "";
      return `Gemini no está configurado todavía.\n\nResumen determinístico disponible:\n${buildLocalSummary(context)}${docText}`;
    }
    const response = await client.audit(buildPayload(question, context));
    return response.text || "Gemini no devolvió una respuesta útil.";
  } catch (error) {
    return `No pude consultar Gemini.\n\nResumen determinístico disponible:\n${buildLocalSummary(context)}\n\nDetalle técnico: ${error.message || error}`;
  }
}

function createChatDom() {
  const launcher = document.createElement("button");
  launcher.type = "button";
  launcher.className = "ai-chat-launcher";
  launcher.innerHTML = "💬 Asistente IA";

  const panel = document.createElement("section");
  panel.className = "ai-chat-panel";
  panel.setAttribute("aria-label", "Copiloto preventivo");
  panel.innerHTML = `
    <header class="ai-chat-header">
      <div>
        <strong>Copiloto preventivo</strong>
        <small>Preguntá sobre liquidación, revista, Serie 990, AFIP y PDFs cargados.</small>
      </div>
      <button type="button" class="ai-chat-close" aria-label="Cerrar chat">×</button>
    </header>
    <section class="ai-chat-docs">
      <div class="ai-chat-doc-row">
        <div><strong>Base documental PDF</strong><br><small class="ai-chat-doc-status"></small></div>
        <label class="ai-chat-doc-upload">+ PDF<input type="file" accept="application/pdf" multiple></label>
      </div>
      <div class="ai-chat-doc-list"></div>
      <button type="button" class="ai-chat-doc-clear">Limpiar PDFs cargados</button>
    </section>
    <div class="ai-chat-messages" role="log" aria-live="polite"></div>
    <div>
      <div class="ai-chat-suggestions">
        ${SUGGESTED_PROMPTS.map((prompt) => `<button type="button" class="ai-chat-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}
      </div>
      <form class="ai-chat-form">
        <textarea class="ai-chat-input" name="question" rows="1" placeholder="Ej: ¿qué dice el CCT sobre esto?"></textarea>
        <button type="submit" class="ai-chat-send">Enviar</button>
      </form>
    </div>
  `;

  document.body.append(panel, launcher);
  return {
    launcher,
    panel,
    close: panel.querySelector(".ai-chat-close"),
    messages: panel.querySelector(".ai-chat-messages"),
    form: panel.querySelector(".ai-chat-form"),
    input: panel.querySelector(".ai-chat-input"),
    send: panel.querySelector(".ai-chat-send"),
    chips: Array.from(panel.querySelectorAll(".ai-chat-chip")),
    docInput: panel.querySelector(".ai-chat-doc-upload input"),
    docStatus: panel.querySelector(".ai-chat-doc-status"),
    docList: panel.querySelector(".ai-chat-doc-list"),
    docClear: panel.querySelector(".ai-chat-doc-clear")
  };
}

export function initPayrollChatBox() {
  if (document.querySelector(".ai-chat-launcher")) return;
  restoreDocuments();
  injectStyles();
  const refs = createChatDom();
  renderDocuments(refs);

  addMessage(
    "assistant",
    "Hola. Soy el copiloto preventivo. Puedo explicar hallazgos del auditor y responder usando PDFs cargados como CCT, LCT, acuerdos o manuales AFIP.",
    refs
  );

  const setOpen = (open) => {
    CHAT_STATE.open = open;
    refs.panel.classList.toggle("is-open", open);
    if (open) refs.input.focus();
  };

  refs.launcher.addEventListener("click", () => setOpen(!CHAT_STATE.open));
  refs.close.addEventListener("click", () => setOpen(false));
  refs.docInput.addEventListener("change", async () => {
    try {
      await handleDocumentUpload(refs.docInput.files, refs);
    } catch (error) {
      addMessage("assistant", `No pude leer el PDF: ${error.message || error}`, refs);
    } finally {
      refs.docInput.value = "";
    }
  });
  refs.docClear.addEventListener("click", () => {
    CHAT_STATE.documents = [];
    persistDocuments();
    renderDocuments(refs);
    addMessage("assistant", "Base documental local limpiada.", refs);
  });

  async function submitQuestion(rawQuestion) {
    const question = String(rawQuestion || "").trim();
    if (!question || CHAT_STATE.busy) return;
    CHAT_STATE.busy = true;
    refs.send.disabled = true;
    refs.input.value = "";
    addMessage("user", question, refs);
    addMessage("assistant", "Analizando contexto preventivo y documentos cargados…", refs);

    const loadingIndex = CHAT_STATE.messages.length - 1;
    const answer = await askGemini(question);
    CHAT_STATE.messages[loadingIndex] = { role: "assistant", text: answer };
    renderMessages(refs.messages);

    CHAT_STATE.busy = false;
    refs.send.disabled = false;
    refs.input.focus();
  }

  refs.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitQuestion(refs.input.value);
  });

  refs.chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      setOpen(true);
      submitQuestion(chip.dataset.prompt);
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPayrollChatBox);
} else {
  initPayrollChatBox();
}
