const NO_INFO = "No cuento con esa informacion en esta calculadora.";

const state = {
  open: false,
  busy: false,
  messages: [],
};

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

function getCalculatorData() {
  const raw = window.CCT_CHAT_DATA || {};
  return raw.calculator || raw.payload || raw;
}

function getConvenioLabel(calculator) {
  const convenio = calculator?.convenio || {};
  return convenio.nombre || convenio.actividad || convenio.cct_numero || document.title || "esta calculadora";
}

function tokens(value) {
  const stop = new Set(["para", "pero", "como", "cual", "cuales", "sobre", "esta", "este", "datos", "info", "informacion"]);
  const result = [];
  const seen = new Set();
  normalizeText(value)
    .split(/[^a-z0-9]+/)
    .forEach((token) => {
      if (token.length < 3 || stop.has(token)) return;
      const variants = [token];
      if (token.endsWith("es") && token.length > 5) variants.push(token.slice(0, -2));
      if (token.endsWith("s") && token.length > 4) variants.push(token.slice(0, -1));
      variants.forEach((variant) => {
        if (!seen.has(variant) && !stop.has(variant)) {
          seen.add(variant);
          result.push(variant);
        }
      });
    });
  return result;
}

function localRecords(calculator) {
  const records = [];
  const convenio = calculator?.convenio || {};
  if (Object.keys(convenio).length) {
    records.push(`Convenio: ${Object.entries(convenio).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(". ")}`);
  }

  for (const category of calculator?.categorias || []) {
    records.push(`Categoria: ${category.nombre || category.categoria || category.id || ""}. Rama: ${category.rama || category.sector || ""}. Basico mensual: ${category.basico_mensual || category.sueldo_mensual || category.basico || ""}. Valor hora: ${category.valor_hora || ""}.`);
  }

  for (const scale of calculator?.escalas_salariales || []) {
    records.push(`Escala: ${scale.categoria || scale.nombre || ""}. Rama: ${scale.rama || ""}. Periodo: ${scale.periodo || scale.vigencia || ""}. Basico mensual: ${scale.basico_mensual || scale.sueldo_mensual || scale.valor || ""}. Valor hora: ${scale.valor_hora || ""}. Articulo 11: ${scale.articulo_11 || ""}. Multifuncionalidad: ${scale.multifuncionalidad || ""}.`);
  }

  for (const key of ["adicionales", "subsidios", "deducciones", "conceptos_liquidables"]) {
    for (const item of calculator?.[key] || []) {
      records.push(`${key}: ${item.nombre || item.concepto || ""}. Valor: ${item.valor || item.monto || item.importe || ""}. Formula: ${item.formula || ""}.`);
    }
  }

  if (calculator?.reglas_liquidacion) {
    records.push(`Reglas de liquidacion: ${JSON.stringify(calculator.reglas_liquidacion)}`);
  }

  return records.filter((record) => record.replace(/[^a-z0-9]/gi, "").length > 8);
}

function localAnswer(question, calculator) {
  const questionTokens = tokens(question);
  if (!questionTokens.length) return NO_INFO;

  const ranked = localRecords(calculator)
    .map((record) => {
      const normalized = normalizeText(record);
      const score = questionTokens.reduce((total, token) => total + (normalized.includes(token) ? 1 : 0), 0);
      return { record, score };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);

  if (!ranked.length) return NO_INFO;
  return `Con la informacion cargada en esta calculadora:\n${ranked.map((item) => `- ${item.record}`).join("\n")}`;
}

function injectStyles() {
  if (document.querySelector("#cct-chatbot-styles")) return;
  const style = document.createElement("style");
  style.id = "cct-chatbot-styles";
  style.textContent = `
    .cct-chat-launcher {
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 2000;
      border: 0;
      border-radius: 999px;
      padding: 13px 18px;
      background: linear-gradient(135deg, #041f4a, #0b5ed7);
      color: #fff;
      box-shadow: 0 18px 46px rgba(11, 94, 215, .32);
      font: 800 14px/1 var(--font, "Plus Jakarta Sans", sans-serif);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 9px;
    }
    .cct-chat-launcher:hover { transform: translateY(-1px); }
    .cct-chat-dot { width: 9px; height: 9px; border-radius: 50%; background: #7db2ff; box-shadow: 0 0 0 5px rgba(125, 178, 255, .2); }
    .cct-chat-panel {
      position: fixed;
      right: 22px;
      bottom: 82px;
      z-index: 2001;
      width: min(440px, calc(100vw - 28px));
      max-height: min(720px, calc(100vh - 110px));
      display: none;
      grid-template-rows: auto 1fr auto;
      overflow: hidden;
      border: 1px solid rgba(188, 215, 255, .9);
      border-radius: 24px;
      background: rgba(255, 255, 255, .98);
      box-shadow: 0 28px 80px rgba(15, 43, 84, .24);
    }
    .cct-chat-panel.is-open { display: grid; }
    .cct-chat-header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 17px 18px;
      background: linear-gradient(135deg, #eaf2ff, #ffffff);
      border-bottom: 1px solid #dde8f8;
    }
    .cct-chat-title strong { display: block; color: #102033; font-size: 15px; }
    .cct-chat-title small { display: block; color: #63738a; margin-top: 4px; line-height: 1.35; }
    .cct-chat-close { width: 34px; height: 34px; border-radius: 50%; border: 1px solid #dde8f8; background: #fff; color: #63738a; cursor: pointer; font-weight: 900; }
    .cct-chat-messages { display: grid; align-content: start; gap: 12px; min-height: 260px; overflow: auto; padding: 16px; background: #f7faff; }
    .cct-chat-message { max-width: 92%; white-space: pre-wrap; border-radius: 16px; padding: 12px 14px; font-size: 13px; line-height: 1.5; }
    .cct-chat-message.user { justify-self: end; color: #fff; background: #0b5ed7; border-bottom-right-radius: 6px; }
    .cct-chat-message.assistant { justify-self: start; color: #102033; background: #fff; border: 1px solid #dde8f8; border-bottom-left-radius: 6px; }
    .cct-chat-tools { padding: 12px 14px 14px; border-top: 1px solid #dde8f8; background: #fff; }
    .cct-chat-suggestions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
    .cct-chat-chip { border: 1px solid #bcd7ff; background: #eaf2ff; color: #0b5ed7; border-radius: 999px; padding: 7px 10px; font: 700 12px/1 var(--font, sans-serif); cursor: pointer; }
    .cct-chat-form { display: grid; grid-template-columns: 1fr auto; gap: 9px; }
    .cct-chat-input { min-height: 44px; max-height: 120px; resize: vertical; border: 1.5px solid #dde8f8; border-radius: 14px; padding: 11px 12px; font: inherit; outline: none; }
    .cct-chat-input:focus { border-color: #0b5ed7; box-shadow: 0 0 0 3px rgba(11, 94, 215, .1); }
    .cct-chat-send { border: 0; border-radius: 14px; padding: 0 15px; background: #0b5ed7; color: #fff; font-weight: 800; cursor: pointer; }
    .cct-chat-send[disabled] { opacity: .55; cursor: not-allowed; }
    @media (max-width: 560px) {
      .cct-chat-launcher { right: 14px; bottom: 14px; }
      .cct-chat-panel { right: 14px; bottom: 72px; width: calc(100vw - 28px); }
    }
  `;
  document.head.append(style);
}

function renderMessages(container) {
  container.innerHTML = state.messages
    .map((message) => `<article class="cct-chat-message ${message.role}">${escapeHtml(message.text)}</article>`)
    .join("");
  container.scrollTop = container.scrollHeight;
}

function pushMessage(role, text, refs) {
  state.messages.push({ role, text });
  renderMessages(refs.messages);
}

async function ask(question) {
  const calculator = getCalculatorData();
  try {
    const response = await fetch("/calculator-chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        calculator,
        page: window.location.pathname,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    return payload.answer || NO_INFO;
  } catch (error) {
    console.warn("Chat CCT: usando respuesta local", error);
    return localAnswer(question, calculator);
  }
}

function buildSuggestions(calculator) {
  const suggestions = ["Que categorias tiene?", "Cual es la escala salarial?", "Como calcula antiguedad?"];
  const text = normalizeText(JSON.stringify(calculator || {}));
  if (text.includes("zona")) suggestions.push("Hay zona desfavorable?");
  if (text.includes("subsid")) suggestions.push("Que subsidios contiene?");
  return suggestions.slice(0, 5);
}

function createDom(calculator) {
  const launcher = document.createElement("button");
  launcher.type = "button";
  launcher.className = "cct-chat-launcher";
  launcher.innerHTML = `<span class="cct-chat-dot"></span><span>Chat CCT</span>`;

  const panel = document.createElement("section");
  panel.className = "cct-chat-panel";
  panel.setAttribute("aria-label", "Chat de convenio y escalas");
  const suggestions = buildSuggestions(calculator);
  panel.innerHTML = `
    <header class="cct-chat-header">
      <div class="cct-chat-title">
        <strong>Asistente de convenio</strong>
        <small>Responde solo con datos de ${escapeHtml(getConvenioLabel(calculator))}. Si no esta cargado, te lo dice.</small>
      </div>
      <button type="button" class="cct-chat-close" aria-label="Cerrar">x</button>
    </header>
    <div class="cct-chat-messages" role="log" aria-live="polite"></div>
    <div class="cct-chat-tools">
      <div class="cct-chat-suggestions">
        ${suggestions.map((item) => `<button type="button" class="cct-chat-chip" data-prompt="${escapeHtml(item)}">${escapeHtml(item)}</button>`).join("")}
      </div>
      <form class="cct-chat-form">
        <textarea class="cct-chat-input" rows="1" placeholder="Pregunta por categorias, escalas, adicionales..."></textarea>
        <button type="submit" class="cct-chat-send">Enviar</button>
      </form>
    </div>
  `;
  document.body.append(panel, launcher);
  return {
    launcher,
    panel,
    close: panel.querySelector(".cct-chat-close"),
    messages: panel.querySelector(".cct-chat-messages"),
    form: panel.querySelector(".cct-chat-form"),
    input: panel.querySelector(".cct-chat-input"),
    send: panel.querySelector(".cct-chat-send"),
    chips: Array.from(panel.querySelectorAll(".cct-chat-chip")),
  };
}

export function initCctChatbot() {
  if (document.querySelector(".cct-chat-launcher")) return;
  const calculator = getCalculatorData();
  injectStyles();
  const refs = createDom(calculator);

  pushMessage("assistant", `Hola. Tengo cargada la informacion de ${getConvenioLabel(calculator)} disponible en esta calculadora. Si me preguntas algo que no esta en estos datos, voy a responder: "${NO_INFO}"`, refs);

  const setOpen = (open) => {
    state.open = open;
    refs.panel.classList.toggle("is-open", open);
    if (open) refs.input.focus();
  };

  refs.launcher.addEventListener("click", () => setOpen(!state.open));
  refs.close.addEventListener("click", () => setOpen(false));

  async function submit(rawQuestion) {
    const question = String(rawQuestion || "").trim();
    if (!question || state.busy) return;
    state.busy = true;
    refs.send.disabled = true;
    refs.input.value = "";
    pushMessage("user", question, refs);
    pushMessage("assistant", "Buscando en el CCT y escalas de esta calculadora...", refs);
    const loadingIndex = state.messages.length - 1;
    state.messages[loadingIndex] = { role: "assistant", text: await ask(question) };
    renderMessages(refs.messages);
    state.busy = false;
    refs.send.disabled = false;
    refs.input.focus();
  }

  refs.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(refs.input.value);
  });

  refs.chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      setOpen(true);
      submit(chip.dataset.prompt);
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initCctChatbot);
} else {
  initCctChatbot();
}
