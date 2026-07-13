# Evidencia de RFC-006

RFC-006 (`../../rfcs/RFC-006-provider-safe-routing.md`) afirma resultados medidos localmente: `pytest tests/test_egress.py` → 15 passed, `pytest tests/` → 126 passed / 1 failed pre-existente, PoC de cero bytes a DeepSeek en un proyecto `restricted`. Ese patch (`egress-gate.patch`, +512/−28) fue efímero: se aplicó, se probó y se descartó sin publicar rama ni guardar el patch ni el script `repro.py` en este repo. No hay artefactos que archivar todavía.

Este README es solo sobre RFC-006 en sí (el diseño original y su patch efímero). **La evidencia de la ejecución real de RFC-007 Parte II (los 13 commits, la tabla de trazabilidad I1-I15, la verificación adversarial) vive en `../RFC-007/README.md`** — RFC-006 es la fuente del diseño, RFC-007 es quien gobierna la reconstrucción contra código real, y un ID de evidencia debe corresponder al documento que hace la afirmación que se está verificando.

No pegar prompts, tareas ni contexto real de proyectos en esta carpeta — es evidencia pública del repo, y las mismas reglas de "el log registra la decisión, nunca el payload" (RFC-006 §6.2) aplican acá.
