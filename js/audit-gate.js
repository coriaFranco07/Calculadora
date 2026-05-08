const PROTECTED_STEPS = new Set(["result", "gemini"]);
const PROTECTED_SELECTORS = [
  "#print-button",
  "#print-result-button",
  "[data-export]",
  "[data-action='export']",
  "[data-action='print']",
  ".export-button",
  ".print-button"
];
const CONTINUE_TO_RESULT_SELECTORS = [
  "[data-wizard-step='result']",
  "[data-wizard-step='gemini']",
  "[data-wizard-next='result']",
  "[data-wizard-next='gemini']",
  "#section-audit [data-wizard-next]",
  "#section-audit .wizard-next",
  "#section-audit .next-button",
  "#section-audit button"
];

function getAudit() {
  if (typeof window.getPayrollAuditContext !== "function") return null;
  return window.getPayrollAuditContext()?.auditoria || null;
}

function normalize(value) {
  return String(value || "").toLowerCase();
}

function isAuditBlocking(audit = getAudit()) {
  if (!audit) return false;

  const statusText = normalize(audit.estado || audit.status || audit.summary?.status);
  const counters = audit.counters || audit.summary?.counters || {};
  const findings = audit.findings || audit.hallazgos || [];

  const hasBlockingStatus =
    statusText.includes("bloquear") ||
    statusText.includes("block") ||
    statusText.includes("no apto");

  const hasBlockingCounters =
    Number(counters.blocker || 0) > 0 ||
    Number(counters.blockers || 0) > 0 ||
    Number(counters.critical || 0) > 0 ||
    Number(counters.criticals || 0) > 0;

  const hasBlockingFindings = findings.some((item) => {
    const level = normalize(item.severity || item.type || item.level || item.nivel || item.status);
    return (
      level.includes("block") ||
      level.includes("bloque") ||
      level.includes("critical") ||
      level.includes("critico") ||
      level.includes("error")
    );
  });

  return hasBlockingStatus || hasBlockingCounters || hasBlockingFindings;
}

function getAuditSummary(audit = getAudit()) {
  if (!audit) return "La auditoría preventiva todavía no está calculada.";
  const counters = audit.counters || audit.summary?.counters || {};
  const findings = audit.findings || audit.hallazgos || [];
  const firstFinding = findings.find((item) => {
    const level = normalize(item.severity || item.type || item.level || item.nivel || item.status);
    return level.includes("block") || level.includes("critical") || level.includes("error") || level.includes("bloque");
  });
  const totals = [
    Number(counters.blocker || counters.blockers || 0) ? `${Number(counters.blocker || counters.blockers || 0)} bloqueante(s)` : "",
    Number(counters.critical || counters.criticals || 0) ? `${Number(counters.critical || counters.criticals || 0)} crítico(s)` : ""
  ].filter(Boolean).join(" · ");
  const title = firstFinding?.title || firstFinding?.titulo || firstFinding?.code || firstFinding?.codigo || "hallazgos bloqueantes";
  return `${totals || "Hay hallazgos bloqueantes"}. Principal: ${title}.`;
}

function showGateToast(message) {
  let stack = document.querySelector("#toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toast-stack";
    stack.style.position = "fixed";
    stack.style.right = "18px";
    stack.style.top = "18px";
    stack.style.zIndex = "9999";
    document.body.append(stack);
  }

  const node = document.createElement("article");
  node.className = "toast-card is-error audit-gate-toast";
  node.innerHTML = `<strong>Exportación bloqueada</strong><small>${escapeHtml(message)}</small>`;
  stack.append(node);
  window.setTimeout(() => node.remove(), 4200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function goToAuditStep() {
  const auditButton = document.querySelector("[data-wizard-step='audit']");
  if (auditButton) {
    auditButton.click();
    return;
  }
  const auditPane = document.querySelector("#section-audit");
  if (auditPane) auditPane.scrollIntoView({ behavior: "smooth", block: "start" });
}

function blockProtectedAction(event) {
  const audit = getAudit();
  if (!isAuditBlocking(audit)) return false;

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation?.();
  showGateToast(`La auditoría preventiva detectó errores. ${getAuditSummary(audit)} Corregí los datos antes de avanzar.`);
  goToAuditStep();
  updateAuditGateUi();
  return true;
}

function isProtectedWizardTarget(target) {
  const button = target.closest?.("[data-wizard-step], [data-wizard-next]");
  if (!button) return false;

  const explicitStep = button.dataset.wizardStep || button.dataset.wizardNext;
  if (explicitStep && PROTECTED_STEPS.has(explicitStep)) return true;

  const activePane = document.querySelector(".section-pane.is-active");
  if (!activePane) return false;
  const activeId = activePane.id || "";
  if (activeId.includes("section-audit") && button.hasAttribute("data-wizard-next")) return true;
  return false;
}

function isProtectedActionTarget(target) {
  return PROTECTED_SELECTORS.some((selector) => target.closest?.(selector));
}

function getProtectedStepButtons() {
  return Array.from(document.querySelectorAll("[data-wizard-step='result'], [data-wizard-step='gemini'], [data-wizard-next='result'], [data-wizard-next='gemini']"));
}

function getContinueToResultButtons() {
  const candidates = new Set();
  CONTINUE_TO_RESULT_SELECTORS.forEach((selector) => {
    document.querySelectorAll(selector).forEach((button) => candidates.add(button));
  });

  getProtectedStepButtons().forEach((button) => candidates.add(button));

  return [...candidates].filter((button) => {
    if (!(button instanceof HTMLElement)) return false;
    const text = normalize(button.textContent);
    const step = button.dataset?.wizardStep || button.dataset?.wizardNext || "";
    return (
      PROTECTED_STEPS.has(step) ||
      text.includes("resultado final") ||
      text.includes("continuar a resultado") ||
      text.includes("ver resultado") ||
      text.includes("resultado") ||
      text.includes("revision gemini") ||
      text.includes("revisión gemini")
    );
  });
}

function ensureBlockedContinueNotice(blocked) {
  let notice = document.querySelector("#audit-gate-continue-notice");
  const auditPane = document.querySelector("#section-audit");
  if (!blocked) {
    notice?.remove();
    return;
  }
  if (!auditPane) return;

  if (!notice) {
    notice = document.createElement("article");
    notice.id = "audit-gate-continue-notice";
    notice.className = "audit-gate-continue-notice";
    auditPane.append(notice);
  }
  notice.innerHTML = `<strong>Resultado final no disponible</strong><p>${escapeHtml(getAuditSummary())} El botón para continuar se habilitará automáticamente cuando la auditoría quede sin bloqueantes.</p>`;
}

function updateContinueButtons(blocked) {
  getContinueToResultButtons().forEach((button) => {
    button.classList.toggle("audit-gate-hidden", blocked);
    button.setAttribute("aria-hidden", blocked ? "true" : "false");
    button.disabled = blocked;
    button.tabIndex = blocked ? -1 : 0;
  });
  ensureBlockedContinueNotice(blocked);
}

function updateAuditGateUi() {
  const blocked = isAuditBlocking();
  document.documentElement.classList.toggle("audit-gate-blocked", blocked);

  PROTECTED_SELECTORS.forEach((selector) => {
    document.querySelectorAll(selector).forEach((button) => {
      button.disabled = blocked;
      button.classList.toggle("is-disabled", blocked);
      button.setAttribute("aria-disabled", blocked ? "true" : "false");
      button.title = blocked ? "Bloqueado por auditoría preventiva" : "";
    });
  });

  updateContinueButtons(blocked);

  const exportCard = document.querySelector("#audit-export-card");
  if (exportCard) exportCard.classList.toggle("audit-gate-hard-block", blocked);

  let banner = document.querySelector("#audit-gate-banner");
  if (blocked) {
    if (!banner) {
      banner = document.createElement("article");
      banner.id = "audit-gate-banner";
      banner.className = "audit-gate-banner";
      const auditBox = document.querySelector("#auto-audit-box") || document.querySelector("#section-audit") || document.querySelector("main");
      auditBox?.prepend(banner);
    }
    banner.innerHTML = `<strong>Exportación bloqueada por auditoría preventiva</strong><p>${escapeHtml(getAuditSummary())} Corregí los datos bloqueantes para habilitar resultado, impresión o exportación.</p>`;
  } else if (banner) {
    banner.remove();
  }
}

function injectAuditGateStyles() {
  if (document.querySelector("#audit-gate-styles")) return;
  const style = document.createElement("style");
  style.id = "audit-gate-styles";
  style.textContent = `
    .audit-gate-banner,
    .audit-gate-continue-notice {
      margin: 0 0 16px;
      padding: 16px 18px;
      border: 1px solid rgba(160, 43, 43, .22);
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(160, 43, 43, .10), rgba(208, 98, 36, .10));
      color: #4a1f1f;
      box-shadow: 0 12px 28px rgba(160, 43, 43, .08);
    }
    .audit-gate-continue-notice {
      margin-top: 16px;
    }
    .audit-gate-banner strong,
    .audit-gate-continue-notice strong { display: block; font-size: 1rem; margin-bottom: 5px; }
    .audit-gate-banner p,
    .audit-gate-continue-notice p { margin: 0; color: #6d3530; line-height: 1.45; }
    .audit-gate-hard-block {
      outline: 2px solid rgba(160, 43, 43, .22);
      box-shadow: 0 0 0 5px rgba(160, 43, 43, .06);
    }
    .audit-gate-hidden {
      display: none !important;
      visibility: hidden !important;
      pointer-events: none !important;
    }
    button.is-disabled, .is-disabled {
      opacity: .52 !important;
      cursor: not-allowed !important;
      filter: grayscale(.18);
    }
  `;
  document.head.append(style);
}

function installAuditGate() {
  injectAuditGateStyles();
  updateAuditGateUi();

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (isProtectedWizardTarget(target) || isProtectedActionTarget(target)) {
      blockProtectedAction(event);
    }
  }, true);

  window.addEventListener("beforeprint", (event) => {
    if (isAuditBlocking()) blockProtectedAction(event);
  });

  window.setInterval(updateAuditGateUi, 250);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", installAuditGate);
} else {
  installAuditGate();
}

export { isAuditBlocking, updateAuditGateUi };
