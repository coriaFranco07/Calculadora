# Motor de Auditoria Preventiva Laboral y AFIP

## Objetivo

Transformar la calculadora CCT 244/94 en una plataforma de auditoria preventiva con:

- UI desacoplada
- motor local deterministico
- datos versionados
- backend seguro para Gemini

## Estructura

```text
backend/
  app.py
  requirements.txt
js/
  calculadora.js
  auditor.js
  reglas.js
  gemini-client.js
  ui.js
data/
  conceptos.json
  reglas.json
  mapeo_afip.json
  formulas.json
  convenio_244_94.json
  sample_auditoria.json
docs/
  ARQUITECTURA_AUDITORIA_PREVENTIVA.md
Calculadora_CCT_244_94_Alimentacion.html
package.json
```

## Criterios de diseno

1. El HTML conserva solo la UI y monta `js/ui.js` como shell liviano.
2. `js/calculadora.js` resuelve la liquidacion y devuelve un objeto terminado.
3. `js/auditor.js` recibe siempre la liquidacion final y ejecuta reglas deterministicas.
4. `js/reglas.js` concentra severidades, score, validadores y trazabilidad.
5. `js/gemini-client.js` solo habla con el backend local y nunca calcula montos.
6. Las reglas, conceptos, formulas y mapeos AFIP se versionan en `data/*.json`.

## Integracion actual

- La auditoria preventiva corre automaticamente en cada liquidacion.
- El pipeline operativo es: `inputs -> calculateLiquidation() -> ejecutarAuditoria() -> render UI -> Gemini opcional`.
- El resultado se muestra embebido en el panel principal de la calculadora.
- La trazabilidad visual expone revista, serie 990, checklist y snapshot auditado.

## Flujo

```text
PDF / convenio / AFIP / planillas
-> ETL / normalizacion a JSON versionado
-> motor de liquidacion
-> objeto liquidacion final
-> motor local de auditoria preventiva
-> resultado auditable con score y severidades
-> Gemini opcional sobre resumen de auditoria
```

## Migracion gradual

1. El calculo y la auditoria ya quedaron extraidos a modulos ESM en `js/`.
2. El HTML ya no contiene logica de calculo ni logica de auditoria inline.
3. La carpeta `src/audit/` puede conservarse solo como legado tecnico hasta su retiro definitivo.

## Reglas bloqueantes iniciales

- revista que no cierra en el periodo
- revista con huecos o superposiciones
- mas de 3 tramos de revista
- situacion general distinta al ultimo tramo
- dias y horas F931 informados al mismo tiempo
- ecuacion 996 != (993 + 994 + 997) - 995
- diferencias entre totalizadores y suma de conceptos
- conceptos impresos sin tanque
- tipo AFIP incompatible con la serie

## Uso de Gemini

- endpoint: `POST /audit`
- input esperado: resumen de totalizadores, revista y hallazgos
- la API key vive solo en el backend via variable de entorno
- no se envian PDFs ni tablas masivas al modelo

## Puesta en marcha

### Sin dependencias extra

```powershell
python -m backend.serve_local --host 127.0.0.1 --port 8000
```

O bien:

```powershell
.\backend\start_local.ps1
```

### Backend target con FastAPI

```powershell
pip install -r backend\requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```
