import { createGeminiClient } from "./gemini-client.js";

const CHAT_STATE = {
  open: false,
  busy: false,
  messages: []
};

const SUGGESTED_PROMPTS = [
  "¿Por qué bloqueó la exportación?",
  "Explicame la Serie 990",
  "¿Qué falta en la revista?",
  "¿Qué riesgo AFIP tiene?",
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
    pregunta_usuario: question
  };
}

function injectStyles() {
  if (document.querySelector("#ai-chat-box-styles")) return;
  const style = document.createElement("style");
  style.id = "ai-chat-box-styles";
  style.textContent = `
    .ai-chat-launcher {
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 120;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 13px 18px;
      border: 0;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent, #d06224), #e18a41);
      color: #fff;
      box-shadow: 0 18px 42px rgba(54, 40, 22, 0.28);
      font-weight: 800;
      cursor: pointer;
    }

    .ai-chat-panel {
      position: fixed;
      right: 22px;
      bottom: 84px;
      z-index: 121;
      width: min(420px, calc(100vw - 28px));
      max-height: min(680px, calc(100vh - 112px));
      display: none;
      grid-template-rows: auto 1fr auto;
      overflow: hidden;
      border-radius: 24px;
      border: 1px solid var(--line-strong, rgba(27, 35, 33, 0.16));
      background: rgba(255, 253, 248, 0.98);
      box-shadow: 0 28px 80px rgba(15, 21, 19, 0.24);
      backdrop-filter: blur(16px);
    }

    .ai-chat-panel.is-open { display: grid; }

    .ai-chat-header {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      padding: 18px 18px 14px;
      border-bottom: 1px solid var(--line, rgba(27, 35, 33, 0.08));
    }

    .ai-chat-header strong { display: block; font-size: 1.05rem; }
    .ai-chat-header small { color: var(--muted, #53615d); line-height: 1.35; }

    .ai-chat-close {
      width: 34px;
      height: 34px;
      border: 1px solid var(--line, rgba(27, 35, 33, 0.08));
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.78);
      cursor: pointer;
      font-weight: 900;
    }

    .ai-chat-messages {
      display: grid;
      align-content: start;
      gap: 12px;
      padding: 16px;
      overflow: auto;
      min-height: 260px;
    }

    .ai-chat-message {
      max-width: 92%;
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid var(--line, rgba(27, 35, 33, 0.08));
      line-height: 1.45;
      white-space: pre-wrap;
      font-size: 0.94rem;
    }

    .ai-chat-message.is-user {
      justify-self: end;
      background: rgba(208, 98, 36, 0.13);
      border-color: rgba(208, 98, 36, 0.24);
    }

    .ai-chat-message.is-assistant {
      justify-self: start;
      background: rgba(255, 255, 255, 0.84);
    }

    .ai-chat-suggestions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 0 16px 12px;
    }

    .ai-chat-chip {
      border: 1px solid var(--line, rgba(27, 35, 33, 0.08));
      border-radius: 999px;
      padding: 8px 10px;
      background: rgba(255, 255, 255, 0.78);
      color: var(--muted, #53615d);
      font-size: 0.82rem;
      cursor: pointer;
    }

    .ai-chat-form {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      padding: 14px 16px 16px;
      border-top: 1px solid var(--line, rgba(27, 35, 33, 0.08));
    }

    .ai-chat-input {
      width: 100%;
      min-height: 44px;
      max-height: 120px;
      resize: vertical;
      border-radius: 14px;
      border: 1px solid var(--line, rgba(27, 35, 33, 0.08));
      padding: 11px 12px;
      background: #fffdf8;
      color: var(--text, #1b2321);
      font: inherit;
    }

    .ai-chat-send {
      align-self: end;
      border: 0;
      border-radius: 14px;
      padding: 12px 14px;
      background: var(--green, #1f6a52);
      color: #fff;
      font-weight: 800;
      cursor: pointer;
    }

    .ai-chat-send[disabled] { opacity: 0.55; cursor: not-allowed; }

    @media (max-width: 560px) {
      .ai-chat-launcher { right: 14px; bottom: 14px; }
      .ai-chat-panel { right: 14px; bottom: 74px; }
    }
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

async function askGemini(question, refs) {
  const context = getContext();
  if (!context.liquidacion && !context.auditoria) {
    return "Primero calculá una liquidación para que pueda analizar el contexto.";
  }

  const client = createGeminiClient("");
  try {
    const health = await client.health();
    if (!health.ai_enabled) {
      return `Gemini no está configurado todavía.\n\nResumen determinístico disponible:\n${buildLocalSummary(context)}`;
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
        <small>Preguntá sobre liquidación, revista, Serie 990, AFIP y riesgos.</small>
      </div>
      <button type="button" class="ai-chat-close" aria-label="Cerrar chat">×</button>
    </header>
    <div class="ai-chat-messages" role="log" aria-live="polite"></div>
    <div>
      <div class="ai-chat-suggestions">
        ${SUGGESTED_PROMPTS.map((prompt) => `<button type="button" class="ai-chat-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}
      </div>
      <form class="ai-chat-form">
        <textarea class="ai-chat-input" name="question" rows="1" placeholder="Ej: ¿qué debería corregir primero?"></textarea>
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

  addMessage(
    "assistant",
    "Hola. Soy el copiloto preventivo. Puedo explicar los hallazgos del auditor, la Serie 990, la revista y riesgos AFIP. Primero calculá una liquidación para darme contexto.",
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
    addMessage("assistant", "Analizando el contexto preventivo…", refs);

    const loadingIndex = CHAT_STATE.messages.length - 1;
    const answer = await askGemini(question, refs);
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
