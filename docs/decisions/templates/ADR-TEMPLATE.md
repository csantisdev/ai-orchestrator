---
id: ADR-NNN
type: adr
title: título de la decisión
status: proposed              # proposed | accepted | rejected | superseded | deprecated
implementation_status: not-started   # not-started | in-progress | implemented | verified | abandoned
created: AAAA-MM-DD
updated: AAAA-MM-DD
supersedes: []
superseded_by: null
related: []
support: []                    # rutas relativas a support/ADR-NNN/, si existen
evidence: []                   # rutas relativas a evidence/ADR-NNN/, si existen
---

# ADR-NNN: título de la decisión

Fecha: AAAA-MM-DD

Estado: propuesta | aceptada | rechazada | superseded | deprecated

*El front matter debe ir literalmente al principio del archivo, delimitado por `---`, antes del H1 — un bloque \`\`\`yaml\`\`\` en el cuerpo no es front matter. `status` (decisión documental) y `implementation_status` (código) son dimensiones separadas a propósito: una decisión puede estar `accepted` con `implementation_status: not-started`, o `accepted` con `implementation_status: implemented`. No uses `status` para describir si el código existe. `Estado:` en prosa usa el mismo vocabulario que `status:` — nunca una palabra distinta para el mismo hecho ("cerrada" no es un valor válido; es "accepted" con `implementation_status: implemented`), y si tu decisión ya se implementó, actualizá `implementation_status` en el momento en que cierre, no cuando alguien lo note meses después — es exactamente el error que se corrigió en ADR-002 durante el reorg de 2026-07-12: decía `status: proposed` con el código ya cerrado desde hacía días.*

*Todo ejemplo o caso de uso en este documento usa datos sintéticos — nunca el nombre, dominio, descripción operativa o endpoint real de un proyecto o cliente del usuario. Ver "Regla de anonimización" en `../README.md`.*

## Contexto

Qué situación obliga a decidir. Qué límites tiene la solución actual (si existe), con referencia a los archivos reales involucrados — no describir el código de memoria, releerlo antes de escribir.

## Decisión

Qué se decidió, en términos concretos y verificables. Si la decisión afecta una función o módulo existente, nombrarlo con su path real.

## Consecuencias

- Qué mejora.
- Qué se vuelve más difícil o más caro.
- Qué migración o cambio de comportamiento le exige al usuario o a otro código del repo.
