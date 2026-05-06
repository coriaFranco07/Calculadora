const CCT_STORAGE_KEY = "cct_calculator_draft_v1";

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

function extractCategories(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  const categoryHints = ["operario", "oficial", "administrativo", "categoria", "categoría", "chofer", "cadete", "medio oficial"];
  return lines
    .filter((line) => categoryHints.some((hint) => normalizeText(line).includes(normalizeText(hint))))
    .slice(0, 18)
    .map((line, index) => ({ id: `cat_${index + 1}`, nombre: line.slice(0, 120), fuente: "texto_cct" }));
}

function extractPercentages(text) {
  const matches = [...String(text || "").matchAll(/(.{0,55})(\d{1,2}(?:[,.]\d{1,2})?)\s*%(.{0,55})/g)];
  return matches.slice(0, 18).map((match, index) => ({
    id: `adicional_${index + 1}`,
    descripcion: `${match[1]}${match[2]}%${match[3]}`.replace(/\s+/g, " ").trim(),
    porcentaje: Number(String(match[2]).replace(",", ".")),
  }));
}

function buildCctJson(rawText) {
  const text = String(rawText || "").trim();
  const categories = extractCategories(text);
  const percentages = extractPercentages(text);
  return {
    version: new Date().toISOString().slice(0, 10),
    estado: text ? "borrador_generado" : "sin_texto",
    convenio: {
      nombre: "CCT cargado por usuario",
      fuente: "texto_pegado",
      observaciones: "Borrador estructurado localmente. Revisar escalas, vigencias y artículos antes de usar en producción."
    },
    categorias: categories,
    adicionales_detectados: percentages,
    jornada: {
      mensual_horas: null,
      mensual_dias: null,
      pendiente_revision: true
    },
    pendientes: [
      "Confirmar vigencia salarial",
      "Cargar escalas remunerativas por categoría",
      "Validar reglas de antigüedad",
      "Validar adicionales convencionales",
      "Revisar jornada y proporcionalidad"
    ]
  };
}

function saveDraft(payload) {
  try {
    localStorage.setItem(CCT_STORAGE_KEY, JSON.stringify(payload));
  } catch (_error) {
    // Local storage can be unavailable in private contexts.
  }
}

function injectStyles() {
  if (document.querySelector("#cct-loader-styles")) return;
  const style = document.createElement("style");
  style.id = "cct-loader-styles";
  style.textContent = `
    .cct-loader-shell {
      margin: 22px auto;
      max-width: 1180px;
      border: 1px solid rgba(31,106,82,.14);
      border-radius: 28px;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(255,253,248,.98), rgba(255,248,237,.96));
      box-shadow: 0 22px 70px rgba(15,21,19,.10);
    }
    .cct-loader-hero {
      padding: 28px;
      background: radial-gradient(circle at 15% 10%, rgba(208,98,36,.18), transparent 34%), linear-gradient(135deg, rgba(31,106,82,.14), rgba(208,98,36,.10));
      display: grid;
      gap: 12px;
    }
    .cct-loader-hero small { color: #53615d; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }
    .cct-loader-hero h2 { margin: 0; font-size: clamp(1.8rem, 3vw, 3rem); color: #1b2321; letter-spacing: -.04em; }
    .cct-loader-hero p { margin: 0; max-width: 760px; color: #53615d; line-height: 1.55; }
    .cct-loader-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, .85fr); gap: 18px; padding: 22px; }
    .cct-loader-card { border: 1px solid rgba(27,35,33,.08); border-radius: 22px; background: rgba(255,255,255,.78); padding: 18px; }
    .cct-loader-card h3 { margin: 0 0 10px; color: #1b2321; }
    .cct-loader-textarea { width: 100%; min-height: 330px; resize: vertical; border: 1px solid rgba(27,35,33,.13); border-radius: 18px; padding: 14px; font: inherit; background: #fffdf8; color: #1b2321; outline: none; }
    .cct-loader-textarea:focus { border-color: rgba(31,106,82,.38); box-shadow: 0 0 0 4px rgba(31,106,82,.08); }
    .cct-loader-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
    .cct-loader-button { border: 0; border-radius: 14px; padding: 12px 15px; background: linear-gradient(135deg, #1f6a52, #d06224); color: white; font-weight: 900; cursor: pointer; }
    .cct-loader-button.secondary { background: rgba(31,106,82,.10); color: #1f6a52; }
    .cct-loader-output { white-space: pre-wrap; overflow: auto; max-height: 430px; padding: 14px; border-radius: 16px; background: #1b2321; color: #f7efe2; font-size: .86rem; line-height: 1.45; }
    .cct-loader-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .cct-loader-pill { border-radius: 999px; padding: 7px 10px; background: rgba(31,106,82,.10); color: #1f6a52; font-size: .82rem; font-weight: 800; }
    @media (max-width: 900px) { .cct-loader-grid { grid-template-columns: 1fr; } }
  `;
  document.head.append(style);
}

function createShell() {
  const existing = document.querySelector("#cct-loader-shell");
  if (existing) return existing;

  const shell = document.createElement("section");
  shell.id = "cct-loader-shell";
  shell.className = "cct-loader-shell";
  shell.innerHTML = `
    <div class="cct-loader-hero">
      <small>Nuevo enfoque del producto</small>
      <h2>CCT → Calculadora</h2>
      <p>Pegá el texto de un convenio colectivo o acuerdo salarial. Esta página genera un primer JSON estructurado para alimentar la calculadora: categorías, adicionales detectados, jornada pendiente y reglas a revisar.</p>
    </div>
    <div class="cct-loader-grid">
      <article class="cct-loader-card">
        <h3>1. Pegar CCT o acuerdo</h3>
        <textarea class="cct-loader-textarea" placeholder="Pegá acá el texto del CCT, acuerdo salarial, escala o artículo relevante..."></textarea>
        <div class="cct-loader-actions">
          <button type="button" class="cct-loader-button" data-cct-generate>Generar JSON preliminar</button>
          <button type="button" class="cct-loader-button secondary" data-cct-example>Cargar ejemplo</button>
        </div>
      </article>
      <article class="cct-loader-card">
        <h3>2. JSON para la calculadora</h3>
        <pre class="cct-loader-output">Esperando texto del CCT...</pre>
        <div class="cct-loader-pills">
          <span class="cct-loader-pill">Extractor local inicial</span>
          <span class="cct-loader-pill">Preparado para Gemini</span>
          <span class="cct-loader-pill">Revisión humana requerida</span>
        </div>
      </article>
    </div>
  `;

  const main = document.querySelector("main") || document.body;
  main.prepend(shell);
  return shell;
}

function initCctLoader() {
  injectStyles();
  const shell = createShell();
  const textarea = shell.querySelector(".cct-loader-textarea");
  const output = shell.querySelector(".cct-loader-output");
  const generate = shell.querySelector("[data-cct-generate]");
  const example = shell.querySelector("[data-cct-example]");

  generate.addEventListener("click", () => {
    const payload = buildCctJson(textarea.value);
    saveDraft(payload);
    output.textContent = JSON.stringify(payload, null, 2);
  });

  example.addEventListener("click", () => {
    textarea.value = `CCT ejemplo Alimentación\nCategoría Operario: tareas generales.\nCategoría Operario Calificado: responsabilidad en elaboración.\nCategoría Administrativo I: trabajos simples.\nAdicional zona desfavorable 20%.\nAntigüedad 1% por año.\nJornada mensual 200 horas.`;
    generate.click();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initCctLoader);
} else {
  initCctLoader();
}

export { buildCctJson };
