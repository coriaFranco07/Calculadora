import { createGeminiClient } from "./gemini-client.js";

const CHAT_STATE = {
  open: false,
  busy: false,
  messages: [],
  documents: [],
  docsLoaded: false
};

const INTERNAL_DOCS_URL = "./data/base_documental.json";
const MAX_CONTEXT_CHUNKS = 6;

const SUGGESTED_PROMPTS = [
  "¿Por qué bloqueó la exportación?",
  "Explicame la Serie 990",
  "¿Qué dice el CCT sobre categorías?",
  "¿Qué dice la LCT sobre antigüedad?",
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

async function loadInternalDocuments() {
  if (CHAT_STATE.docsLoaded) return;
  try {
    const response = await fetch(INTERNAL_DOCS_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    CHAT_STATE.documents = (payload.records || []).map((record) => ({
      source: record.source || "Base documental interna",
      index: record.chunk || 0,
      text: record.text || ""
    }));
  } catch (error) {
    CHAT_STATE.documents = [];
    console.warn("No se pudo cargar base_documental.json", error);
  } finally {
    CHAT_STATE.docsLoaded = true;
  }
}

function rankDocumentChunks(question) {
  const terms = tokenize(question);
  if (!terms.length) return [];

  return CHAT_STATE.documents
    .map((chunk) => {
      const normalizedChunk = normalizeText(`${chunk.source} ${chunk.text}`);
      const score = terms.reduce((total, term) => total + (normalizedChunk.includes(term) ? 1 : 0), 0);
      return { ...chunk, score };
    })
    .filter((chunk) => chunk.score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, MAX_CONTEXT_CHUNKS)
    .map((chunk) => ({
      fuente: chunk.source,
      fragmento: chunk.index,
      texto: chunk.text
    }));
}

function isDocumentQuestion(question) {
  const normalized = normalizeText(question);
  return [
    "cct",
    "convenio",
    "lct",
    "ley",
    "categoria",
    "categorias",
    "antiguedad",
    "jornada",
    "registro",
    "registros",
    "contrato",
    "relacion laboral",
    "oficial",
    "operario"
  ].some((term) => normalized.includes(term));
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

function sourceLine(items) {
  const uniqueSources = [...new Set(items.map((item) => `${item.fuente} · fragmento ${item.fragmento}`))];
  return uniqueSources.length ? `\n\nFuentes internas: ${uniqueSources.join("; ")}.` : "";
}

function sentenceFromChunk(item) {
  return String(item.texto || "")
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
    .slice(0, 3)
    .join(" ");
}

function buildDocumentOnlyAnswer(question) {
  const matches = rankDocumentChunks(question);
  if (!matches.length) {
    return "No encontré una regla específica en la base interna para esa pregunta. Tengo cargado CCT 244/94 Alimentación y LCT 20.744 en versión resumida; probá con términos como categorías, antigüedad, registros, relación laboral, jornada, operario u oficial.";
  }

  const normalized = normalizeText(question);
  const intro = normalized.includes("categoria") || normalized.includes("categorias")
    ? "Según la base interna del CCT 244/94, las categorías se organizan por tipo de personal y por tarea efectiva."
    : normalized.includes("antiguedad")
      ? "Según la base interna, la antigüedad debe analizarse con el CCT aplicable y con las reglas generales de tiempo de servicio de la LCT."
      : "Según la base documental interna, esto es lo más relevante:";

  const bullets = matches.slice(0, 4).map((item) => `• ${sentenceFromChunk(item)}`);
  return `${intro}\n\n${bullets.join("\n")}${sourceLine(matches.slice(0, 4))}`;
}

function friendlyGeminiFallback(question) {
  return [
    buildDocumentOnlyAnswer(question),
    "",
    "La capa Gemini está configurada, pero en este momento no pudo responder por cuota, disponibilidad o saturación del servicio. La respuesta anterior usa el motor local y la base interna para no dejarte sin asistencia."
  ].join("\n");
}

function injectStyles() {
  if (document.querySelector("#ai-chat-box-styles")) return;
  const style = document.createElement("style");
  style.id = "ai-chat-box-styles";
  style.textContent = `
    .ai-chat-launcher { position: fixed; right: 22px; bottom: 22px; z-index: 120; display: inline-flex; align-items: center; gap: 10px; padding: 13px 18px; border: 0; border-radius: 999px; background: linear-gradient(135deg, var(--accent, #d06224), #e18a41); color: #fff; box-shadow: 0 18px 42px rgba(54, 40, 22, 0.28); font-weight: 800; cursor: pointer; }
    .ai-chat-panel { position: fixed; right: 22px; bottom: 84px; z-index: 121; width: min(460px, calc(100vw - 28px)); max-height: min(720px, calc(100vh - 112px)); display: none; grid-template-rows: auto auto 1fr auto; overflow: hidden; border-radius: 24px; border: 1px solid var(--line-strong, rgba(27, 35, 33, 0.16)); background: rgba(255, 253, 248, 0.98); box-shadow: 0 28px 80px rgba(15, 21, 19, 0.24); backdrop-filter: blur(16px); }
    .ai-chat-panel.is-open { display: grid; }
    .ai-chat-header { display: flex; justify-content: space-between; gap: 14px; padding: 18px 18px 14px; border-bottom: 1px solid var(--line, rgba(27, 35, 33, 0.08)); }
    .ai-chat-header strong { display: block; font-size: 1.05rem; }
    .ai-chat-header small, .ai-chat-docs small { color: var(--muted, #53615d); line-height: 1.35; }
    .ai-chat-close { width: 34px; height: 34px; border: 1px solid var(--line, rgba(27, 35, 33, 0.08)); border-radius: 50%; background: rgba(255, 255, 255, 0.78); cursor: pointer; font-weight: 900; }
    .ai-chat-docs { padding: 12px 16px; border-bottom: 1px solid var(--line, rgba(27, 35, 33, 0.08)); background: rgba(31, 106, 82, 0.06); }
    .ai-chat-messages { display: grid; align-content: start; gap: 12px; padding: 16px; overflow: auto; min-height: 260px; }
    .ai-chat-message { max-width: 92%; padding: 12px 14px; border-radius: 16px; border: 1px solid var(--line, rgba(27, 35, 33, 0.08)); line-height: 1.45; white-space: pre-wrap; font-size: 0.94rem; }
    .ai-chat-message.is-user { justify-self: end; background: rgba(208, 98, 36, 0.13); border-color: rgba(208, 98, 36, 0.24); }
    .ai-chat-message.is-assistant { justify-self: start; background: rgba(255, 255, 255, 0.84); }
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

function addMessage(role, text, refs) {
  CHAT_STATE.messages.push({ role, text });
  renderMessages(refs.messages);
}

async function askGemini(question) {
  await loadInternalDocuments();
  const context = getContext();
  const client = createGeminiClient("");
  try {
    const health = await client.health();
    if (!health.ai_enabled) {
      const hasAudit = Boolean(context.liquidacion || context.auditoria);
      const localParts = [];
      if (hasAudit && !isDocumentQuestion(question)) {
        localParts.push(`Resumen preventivo:\n${buildLocalSummary(context)}`);
      }
      localParts.push(buildDocumentOnlyAnswer(question));
      localParts.push("\nGemini no está configurado; esta respuesta usa búsqueda local sobre la base interna.");
      return localParts.join("\n\n");
    }
    const response = await client.audit(buildPayload(question, context));
    return response.text || friendlyGeminiFallback(question);
  } catch (error) {
    console.warn("Gemini no pudo responder; usando fallback local", error);
    return friendlyGeminiFallback(question);
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
        <small>Preguntá sobre liquidación, revista, Serie 990, AFIP, CCT 244/94 y LCT.</small>
      </div>
      <button type="button" class="ai-chat-close" aria-label="Cerrar chat">×</button>
    </header>
    <section class="ai-chat-docs">
      <strong>Base documental interna</strong><br>
      <small>CCT 244/94 Alimentación + Ley de Contrato de Trabajo 20.744 cargadas internamente.</small>
    </section>
    <div class="ai-chat-messages" role="log" aria-live="polite"></div>
    <div>
      <div class="ai-chat-suggestions">
        ${SUGGESTED_PROMPTS.map((prompt) => `<button type="button" class="ai-chat-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}
      </div>
      <form class="ai-chat-form">
        <textarea class="ai-chat-input" name="question" rows="1" placeholder="Ej: ¿qué dice el CCT sobre categorías?"></textarea>
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
    chips: Array.from(panel.querySelectorAll(".ai-chat-chip"))
  };
}

export function initPayrollChatBox() {
  if (document.querySelector(".ai-chat-launcher")) return;
  injectStyles();
  const refs = createChatDom();
  loadInternalDocuments();

  addMessage(
    "assistant",
    "Hola. Soy el copiloto preventivo. Ya tengo cargada una base interna con CCT 244/94 Alimentación y LCT 20.744. Puedo explicar hallazgos del auditor y responder sobre esas fuentes.",
    refs
  );

  const setOpen = (open) => {
    CHAT_STATE.open = open;
    refs.panel.classList.toggle("is-open", open);
    if (open) refs.input.focus();
  };

  refs.launcher.addEventListener("click", () => setOpen(!CHAT_STATE.open));
  refs.close.addEventListener("click", () => setOpen(false));

  async function submitQuestion(rawQuestion) {
    const question = String(rawQuestion || "").trim();
    if (!question || CHAT_STATE.busy) return;
    CHAT_STATE.busy = true;
    refs.send.disabled = true;
    refs.input.value = "";
    addMessage("user", question, refs);
    addMessage("assistant", "Analizando auditoría y base documental interna…", refs);

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
