---
id: ANL-002
type: analysis
title: Protocolo de auditoria cruzada Codex y Claude
status: active
created: 2026-09-25
updated: 2026-09-26
related: [ANL-001, RFC-006, RFC-007, RFC-008]
---

# ANL-002 - Protocolo de auditoria cruzada Codex y Claude

**Estado de ejecución (nota operativa, 2026-09-26):** el protocolo no se ejecutó todavía; `evidence/ANL-002/` no existe. El SHA de la sección Baseline es el de su redacción: al ejecutarlo se fija el SHA vigente de `production` en los tres prompts. La auditoría por cambio que se aplica a cada PR no trivial está descrita en ANL-003.

## Objetivo

Auditar de forma independiente el estado de seguridad, privacidad,
idempotencia y medición local de `ai-orchestrator`. Codex produce primero
evidencia verificable sobre el código; Claude realiza una pasada ciega propia
antes de leer ese informe y recién después intenta refutar sus hallazgos.
Ningún auditor modifica código, configuración, base local ni datos de
proveedores.

## Formato y método de comunicación

Se usa un paquete Markdown versionado, no una conversación libre:

1. Fijar el checkout en el SHA de `production` auditado.
2. Entregar el prompt de Codex de este documento.
3. Guardar su resultado sanitizado como
   `docs/decisions/evidence/ANL-002/codex-findings.md`.
4. Entregar a Claude el mismo SHA y este documento, **sin** el informe de
   Codex. Claude ejecuta la fase A (pasada ciega) del prompt.
5. Guardar ese resultado como
   `docs/decisions/evidence/ANL-002/claude-blind-pass.md` y commitearlo antes
   de continuar, para que el orden quede demostrado por el historial git.
6. Entregar a Claude el informe de Codex **y** el `claude-blind-pass.md` ya
   commiteado, y ejecutar la fase B (refutación). La fase B puede correr en una
   sesión nueva: no se asume que Claude conserve el contexto de la fase A.
7. Guardar su resultado como
   `docs/decisions/evidence/ANL-002/claude-verification.md`.
8. Un responsable humano clasifica los hallazgos confirmados en:
   `accepted`, `false-positive`, `needs-reproduction` o `deferred`.

La restricción de solo lectura aplica al checkout auditado. Los auditores
entregan su informe como texto; el responsable humano es quien lo guarda y
commitea bajo `docs/decisions/evidence/ANL-002/`. Si un auditor escribe el
archivo directamente, solo puede tocar ese directorio y en una rama distinta
del SHA auditado.

Markdown es el formato canónico porque permite citar archivo/línea, comandos,
salidas agregadas y decisiones humanas sin serializar payloads. Cada hallazgo
debe seguir exactamente esta tabla:

| ID | Severidad | Afirmación | Evidencia archivo:línea | Reproducción | Impacto | Corrección mínima | Confianza | Estado |
|---|---|---|---|---|---|---|---|---|

No se aceptan hallazgos sin evidencia reproducible ni recomendaciones que
requieran secretos, prompts, respuestas, nombres de proyectos o contenido de
`config.yaml`.

## Baseline

- **Commit auditado:** `4815fc1c75f94c7c37ddc58d97314390167bc850`
- **Rama:** `production`
- **Cambios relevantes recientes:** evaluación local/benchmark, controles de
  egress, gobernanza MCP, idempotencia transaccional y eliminación de payloads
  de `mcp_invocations`.

Antes de auditar, confirmar:

```text
git fetch origin
git checkout --detach 4815fc1c75f94c7c37ddc58d97314390167bc850
python -m pytest tests -q
python scripts/validate_decision_docs.py
```

Si un comando no está disponible, registrarlo como limitación; no inferir que
la prueba pasó.

## Prompt para Codex

```text
Actuá como auditor técnico de solo lectura. Auditá ai-orchestrator en el SHA
4815fc1c75f94c7c37ddc58d97314390167bc850. No modifiques archivos, no llames
proveedores externos, no leas ni imprimas config.yaml, prompts, respuestas,
datos de proyectos, claves ni registros sin sanitizar.

Ejecutá solamente pruebas locales seguras y guardá los comandos/resultados
agregados. Auditá estas superficies:

1. MCP: orchestrator/mcp.py, mcp_governance.py, db.py, migrate.py y
   tests/test_mcp.py/test_db.py.
   - autorización por perfil/capacidad/proyecto;
   - pertenencia context_id/step_id;
   - request_id explícito, replay y rechazo de reuso;
   - atomicidad SQLite y recuperación de migración;
   - ausencia de payloads, hashes deterministas de salida y filtraciones en
     receipts/logs.
2. Egress: orchestrator/egress.py, router.py, providers/base.py, background.py
   y pruebas relacionadas.
   - no bypass de provider/router/streaming;
   - scope por proyecto, policy lifecycle, retries y secretos reconocidos.
3. Evaluación de modelos: benchmark.py, eval.py, catalog.py y ANL-001.
   - asignación reproducible, mutaciones, agregación sin payload y gates de
     precio/cobertura.
4. Ingesta: watcher.py, codex_watcher.py, git_scanner.py y sus pruebas.
   - cursores corruptos, idempotencia de importación y datos no facturables.

Entregá un informe Markdown con la tabla fija de ANL-002. Para cada hallazgo:
incluí archivo:línea real, reproducción mínima local, severidad, impacto,
corrección mínima y confianza. Diferenciá defecto confirmado, gap de evidencia
y observación de diseño. Si no hay hallazgos en una superficie, indicá qué
revisaste y por qué no encontraste uno. No incluyas payloads ni datos locales.
```

## Prompt para Claude

El prompt tiene dos fases. La fase A se entrega sola; la fase B solo después
de que el resultado de la fase A esté commiteado.

### Fase A - pasada ciega

```text
Actuá como auditor adversarial de solo lectura. Auditá ai-orchestrator en el
SHA 4815fc1c75f94c7c37ddc58d97314390167bc850. Todavía no recibís ningún otro
informe y no debés buscarlo. No modifiques el checkout, no llames servicios
externos y no leas/imprimas configuración, prompts, respuestas ni datos de
proyectos.

Revisá las mismas cuatro superficies del prompt de Codex de ANL-002 (MCP,
egress, evaluación de modelos, ingesta) y reportá hasta seis defectos de alta
confianza, priorizando: bypass de autorización/egress, corrupción
cross-project, idempotencia bajo crash/retry, payload retention, migraciones
SQLite y métricas de modelo que puedan inducir decisiones falsas.

Usá la tabla de ANL-002 con IDs `CLA-A-n`, archivo:línea y reproducción
mínima. Si una superficie no tiene hallazgos, indicá qué revisaste.
No afirmes que un test/CI pasó sin ejecutar o citar una evidencia concreta.
```

### Fase B - refutación

```text
Ahora recibís el informe de Codex generado bajo ANL-002 para el mismo SHA
4815fc1c75f94c7c37ddc58d97314390167bc850 y tu propio informe de la fase A
(`claude-blind-pass.md`, ya commiteado). Usá ese archivo como fuente de tus
hallazgos `CLA-A-n`; no los reconstruyas de memoria. Mantené las mismas
restricciones de solo lectura y privacidad de la fase A.

Tu objetivo NO es resumir ni aceptar el informe: intentá falsar cada hallazgo
de Codex contra código y pruebas reales. Para cada ID clasificá:
- confirmed: reproducible y correctamente severizado;
- false-positive: contradicho por código/prueba;
- needs-reproduction: evidencia insuficiente;
- incomplete: el hallazgo es real, pero falta vector, invariante o impacto.

Después cruzá tus hallazgos `CLA-A-n` con los de Codex: marcá cuáles coinciden
(misma causa raíz) y cuáles solo encontró uno de los dos. No agregues
hallazgos nuevos en esta fase salvo que la refutación revele uno; en ese caso
usá IDs `CLA-B-n` y explicá qué hallazgo de Codex te llevó a él.

Usá la misma tabla de ANL-002 e incluí archivo:línea y reproducción mínima.
No afirmes que un test/CI pasó sin ejecutar o citar una evidencia concreta.
```

## Criterio de cierre

La auditoría cruzada queda cerrada solo si:

- los tres informes citan el mismo SHA;
- `claude-blind-pass.md` fue commiteado antes que `claude-verification.md`;
- todos los hallazgos tienen clasificación humana;
- ningún hallazgo queda en `needs-reproduction` ni en `incomplete`: cada
  `needs-reproduction` se reproduce y pasa a `accepted`, o se reclasifica como
  `false-positive` o `deferred`; cada `incomplete` se completa (vector,
  invariante o impacto) y pasa a `accepted`, o se reclasifica como
  `false-positive` o `deferred`. Toda reclasificación lleva justificación
  escrita;
- cada `accepted` crea una tarea/issue con prueba de regresión esperada;
- el informe no contiene payloads, identificadores de proyectos ni secretos;
- los cambios correctivos pasan `pytest tests -q` y el validador documental.
