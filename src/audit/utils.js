export function normalizeText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

export function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function roundMoney(value) {
  return Math.round((toNumber(value) + Number.EPSILON) * 100) / 100;
}

export function moneyDiff(left, right) {
  return roundMoney(toNumber(left) - toNumber(right));
}

export function nearlyEqual(left, right, tolerance = 0.01) {
  return Math.abs(toNumber(left) - toNumber(right)) <= tolerance;
}

export function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

export function bySeverity(left, right) {
  const weight = { error: 0, warning: 1, info: 2 };
  return (weight[left.severity] ?? 9) - (weight[right.severity] ?? 9);
}

export function unique(values) {
  return [...new Set(values)];
}

export function sum(values) {
  return roundMoney((values || []).reduce((accumulator, item) => accumulator + toNumber(item), 0));
}

export function formatCurrency(value, formatter) {
  if (formatter) return formatter(roundMoney(value));
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 2
  }).format(roundMoney(value));
}

export function hasHttpRuntime() {
  return typeof window !== "undefined" && /^https?:$/i.test(window.location.protocol);
}
