import { renderCalculator } from './calculator-renderer.js';

async function loadPayload() {
  const script = document.querySelector('#calculator-payload');
  if (!script) throw new Error('No se encontró el JSON de la calculadora.');
  return JSON.parse(script.textContent || '{}');
}

function init() {
  const root = document.querySelector('[data-generated-calculator-root]');
  const status = document.querySelector('[data-generated-calculator-status]');
  if (!root) return;

  try {
    const payload = JSON.parse(document.querySelector('#calculator-payload')?.textContent || '{}');
    renderCalculator(root, payload);
    if (status) status.textContent = 'Calculadora lista para usar.';
  } catch (error) {
    if (status) status.textContent = error?.message || 'No pude cargar la calculadora.';
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
