import { buildCalculatorFromFormX } from './formx-adapter.js';
import { renderCalculator } from './calculator-renderer.js';

const STORAGE_KEY = 'cct_calculator_draft_v2';
let currentPayload = null;

function saveDraft(payload) {
  currentPayload = payload;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch (_e) {}
}

function injectStyles() {
  if (document.querySelector('#cct-loader-styles')) return;
  const style = document.createElement('style');
  style.id = 'cct-loader-styles';
  style.textContent = `
    .cct-shell{max-width:1200px;margin:24px auto;padding:24px;border-radius:28px;background:#fff7f0;border:1px solid rgba(0,0,0,.08);display:grid;gap:18px}
    .cct-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
    .cct-card{background:white;border-radius:22px;padding:18px;border:1px solid rgba(0,0,0,.08)}
    .cct-output{background:#1b2321;color:#f5efe2;padding:16px;border-radius:18px;overflow:auto;max-height:500px;white-space:pre-wrap}
    textarea{width:100%;min-height:220px;border-radius:18px;padding:14px;box-sizing:border-box}
    .cct-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
    .cct-btn{border:0;border-radius:14px;padding:12px 16px;background:#1f6a52;color:white;font-weight:700;cursor:pointer}
    .cct-btn.secondary{background:#ece7df;color:#1b2321}
    .cct-status{padding:12px 14px;border-radius:14px;background:#eef7f3;color:#1f6a52;font-weight:700}
    @media(max-width:900px){.cct-grid{grid-template-columns:1fr}}
  `;
  document.head.appendChild(style);
}

function createShell() {
  const shell = document.createElement('section');
  shell.className = 'cct-shell';
  shell.innerHTML = `
    <div>
      <small>FORMX.AI + CALCULADORA</small>
      <h2>Creá calculadoras automáticas desde CCT</h2>
      <p>Pegá el JSON exportado por FormX.ai y generá automáticamente una calculadora salarial dinámica.</p>
    </div>

    <div class="cct-grid">
      <div class="cct-card">
        <h3>JSON de FormX.ai</h3>
        <textarea data-json-input placeholder='Pegá el JSON completo de FormX.ai'></textarea>

        <div class="cct-actions">
          <button class="cct-btn" data-import>Importar JSON</button>
          <button class="cct-btn secondary" data-clear>Limpiar</button>
          <button class="cct-btn" data-create disabled>Crear calculadora</button>
        </div>

        <div class="cct-status" data-status>Esperando JSON de FormX.ai...</div>
        <div data-calculator></div>
      </div>

      <div class="cct-card">
        <h3>JSON normalizado</h3>
        <pre class="cct-output" data-output>Esperando importación...</pre>
      </div>
    </div>
  `;

  document.body.prepend(shell);
  return shell;
}

function init() {
  injectStyles();
  const shell = createShell();

  const refs = {
    input: shell.querySelector('[data-json-input]'),
    importBtn: shell.querySelector('[data-import]'),
    clearBtn: shell.querySelector('[data-clear]'),
    createBtn: shell.querySelector('[data-create]'),
    status: shell.querySelector('[data-status]'),
    output: shell.querySelector('[data-output]'),
    calculator: shell.querySelector('[data-calculator]')
  };

  refs.importBtn.addEventListener('click', () => {
    try {
      const payload = buildCalculatorFromFormX(refs.input.value);
      saveDraft(payload);
      refs.output.textContent = JSON.stringify(payload, null, 2);
      refs.createBtn.disabled = false;
      refs.status.textContent = `JSON importado correctamente. Categorías detectadas: ${payload.categorias?.length || 0}`;
    } catch (error) {
      refs.status.textContent = error?.message || 'No pude importar el JSON';
    }
  });

  refs.clearBtn.addEventListener('click', () => {
    refs.input.value = '';
    refs.output.textContent = 'Esperando importación...';
    refs.calculator.innerHTML = '';
    refs.createBtn.disabled = true;
    refs.status.textContent = 'Esperando JSON de FormX.ai...';
  });

  refs.createBtn.addEventListener('click', () => {
    if (!currentPayload) return;
    renderCalculator(refs.calculator, currentPayload);
    refs.status.textContent = 'Calculadora creada correctamente.';
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
