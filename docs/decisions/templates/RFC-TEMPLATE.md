---
id: RFC-NNN
type: rfc
title: Título corto
status: draft   # draft | in-review | accepted | rejected | withdrawn | superseded
created: AAAA-MM-DD
updated: AAAA-MM-DD
supersedes: []          # IDs que este documento reemplaza, ej. [RFC-005]
superseded_by: null     # ID que reemplazó a este; null mientras esté vigente
related: []              # IDs relacionados que no son ni ancestro ni sucesor, ej. [RFC-008]
---

# RFC-NNN — Título corto

**Estado:** Draft | Draft para validación final | Draft para ejecución (Codex) | Aceptado | Superseded
**Versión:** 0.1
**Fecha:** AAAA-MM-DD
**Repo de referencia:** `owner/repo@branch` = `<sha completo>` (verificado AAAA-MM-DD)
**Relación con la serie:** ¿a qué RFC sucede o complementa? ¿Qué queda fuera de alcance porque lo cubre otro documento?

*El front matter (`status`/`supersedes`/`superseded_by`) es la fuente de verdad para lectura automática (índices, agentes) y debe ir literalmente al principio del archivo, delimitado por `---`, antes del H1 — un bloque \`\`\`yaml\`\`\` dentro del cuerpo NO es front matter, ningún parser lo lee. `**Estado:**` en prosa es solo para lectura humana y debe usar el mismo vocabulario que `status:` (draft/in-review/accepted/...), nunca una palabra distinta para el mismo hecho. Si divergen, el front matter gana — actualizalo primero.*

*Todo ejemplo, PoC o fixture en este documento usa datos sintéticos — nunca el nombre, dominio, descripción operativa o endpoint real de un proyecto o cliente del usuario, ni siquiera como "solo un ejemplo". Ver "Regla de anonimización" en `../README.md`.*

---

## Changelog

Solo si esta no es la v0.1. Tabla `Área | versión anterior | esta versión`, con una fila por cambio sustantivo. Cada fila debe poder responder "¿por qué cambió esto?" sin ir a buscar el historial de git.

---

## 0. Resumen ejecutivo

Qué se propone, en un párrafo. Qué NO se afirma — la lista de lo que este documento explícitamente no reclama es tan importante como la propuesta misma.

## 1. El problema

Reproducido, no argumentado. Si hay un bug, un script o comando que lo demuestra contra el código real, con archivo y línea. Severidad, vector, alcance.

## 2. Estado verificado del código

Tabla `Componente | implementation_status ∈ {implemented, partial, designed, absent} | evidence_status ∈ {verifiable, local-only, none} | detalle con archivo:línea`. No describir el código de memoria — releerlo antes de escribir esta tabla.

## 3. Diseño propuesto

La solución. Con pseudocódigo o diffs conceptuales donde ayude, referenciando archivos reales del repo, no nombres inventados.

## 4. Invariantes / Requisitos falsables

Numeradas (`I1`, `I2`, ...), cada una con un enunciado verificable y, si existe, el test que la prueba. Nunca dejar un número sin enunciado — si no se sabe todavía, no se numera.

## 5. Alcance

Qué está dentro, qué está fuera pero auditado (con el issue o RFC que lo cubre), qué está fuera y no se discute en esta ronda.

## 6. Riesgos

Tabla `Riesgo | Severidad | Estado/Mitigación`.

## 7. Plan de implementación (si el RFC ya pasó la fase de validación)

PR por PR: objetivo, archivos a tocar, cambios, tests a agregar, criterio de aceptación, prompt para el agente que lo va a ejecutar. Ver `RFC-007-ai-control-plane.md` (`../rfcs/`) como referencia de formato extenso, o `RFC-006-provider-safe-routing.md` para el formato de orden de commits.

## 8. Criterios de merge

Checklist. Separar "a rama" de "a producción" de "para afirmar valor de producto" si aplica — no mezclar evidencia de que el código corre con evidencia de que el código sirve.

---

## Apéndice A — Referencias

Solo fuentes verificadas contra su origen. Marcar aparte las citadas pero no verificadas.
