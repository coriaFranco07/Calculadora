# Tests E2E - Selenium

## Objetivo

Estos tests validan comportamiento real del sistema en navegador:

- auditoría preventiva
- bloqueo de resultado final
- wizard
- exportación
- chat IA
- integración visual

## Instalación

```powershell
pip install -r requirements-dev.txt
```

## Levantar backend local

```powershell
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

## Ejecutar Selenium

```powershell
pytest tests/e2e -v
```

## Test actual

### test_audit_gate.py

Verifica:

- carga días trabajados = 28
- calcula liquidación
- auditoría preventiva detecta bloqueo
- desaparece botón “Continuar a resultado final”

Este test protege el flujo crítico AFIP:

> una liquidación observada no puede avanzar a resultado/exportación.
