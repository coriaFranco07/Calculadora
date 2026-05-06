import { loadAuditCatalogs } from "./dataLoader.js";
import { mountAuditorUI } from "./ui.js";

let booted = false;

async function boot() {
  if (booted) return;
  const context = window.__cct244CalculatorContext;
  if (!context) return;

  booted = true;

  try {
    const catalogs = await loadAuditCatalogs();

    mountAuditorUI({
      context,
      catalogs
    });
  } catch (error) {
    const findings = document.querySelector("#audit-findings");
    if (findings) {
      findings.innerHTML = `
        <article class="audit-empty">
          <strong>No se pudo inicializar el motor externo.</strong>
          <p>${error.message}. Servi la app desde el backend local o un servidor estatico para cargar /data y /src.</p>
        </article>
      `;
    }
  }
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  if (window.__cct244CalculatorContext) {
    boot();
  } else {
    document.addEventListener("cct244:ready", boot, { once: true });
  }
}
