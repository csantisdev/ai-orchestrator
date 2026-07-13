# Evidencia de RFC-006

RFC-006 (`../../rfcs/RFC-006-provider-safe-routing.md`) afirma resultados medidos localmente: `pytest tests/test_egress.py` → 15 passed, `pytest tests/` → 126 passed / 1 failed pre-existente, PoC de cero bytes a DeepSeek en un proyecto `restricted`. Ese patch (`egress-gate.patch`, +512/−28) fue efímero: se aplicó, se probó y se descartó sin publicar rama ni guardar el patch ni el script `repro.py` en este repo. No hay artefactos que archivar todavía.

Cuando RFC-007 Parte II (Fase 0-1) se ejecute contra este checkout, esta carpeta debe recibir:

- Log completo de `pytest tests/ -v` antes y después de cada PR de Fase 1.
- Log de `pytest tests/test_egress.py -v` una vez completa la Fase 1.
- El resultado del PoC de RFC-006 §4.2 (`restricted-project.example` restricted → deepseek bloqueado → claude permitido) reproducido contra el código real, no contra el patch viejo.
- El run de CI (`tests.yml`, RFC-007 Fase 0 PR 0.1) que confirma lo anterior en un entorno limpio, no solo local.

No pegar prompts, tareas ni contexto real de proyectos en esta carpeta — es evidencia pública del repo, y las mismas reglas de "el log registra la decisión, nunca el payload" (RFC-006 §6.2) aplican acá.
