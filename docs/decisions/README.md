# docs/decisions/

Registro de decisiones técnicas de `ai-orchestrator`: qué se decidió, qué se propuso y no se cerró, y qué evidencia respalda cada cosa.

## Regla de identidad

**Un ID resuelve a exactamente un documento canónico.** `ADR-002` es la decisión, punto — nunca un mapa de implementación, un análisis o una nota. Material subordinado que no es en sí mismo normativo (mapas de implementación, notas de apoyo) vive en `support/<DOC-ID>/`, nunca comparte el nombre de archivo del documento que aterriza. Es el mismo patrón que `evidence/<DOC-ID>/` para artefactos crudos — ambas carpetas indexan por el ID del documento que respaldan, no inventan su propia numeración.

## Taxonomía

| Carpeta | Contenido | Cuándo usarla | Se edita después de cerrada |
|---|---|---|---|
| `rfcs/` | Propuestas multi-ronda que todavía requieren validación, diseño o discusión antes (o durante) de escribir código. Numeración `RFC-NNN`, secuencial, nunca se reutiliza un número. | Cambios de arquitectura no triviales, con riesgo o reversibilidad baja, que se benefician de una ronda de revisión adversarial antes de implementar. | Sí — mientras esté `Draft`. Cambios de versión van en el propio changelog del documento, no en el nombre del archivo. |
| `adrs/` | Decisiones ya tomadas y aceptadas, con contexto/decisión/consecuencias. Numeración `ADR-NNN`. | Decisiones puntuales, ya cerradas o en implementación, que no necesitan una serie de rondas. | El contenido normativo (Contexto/Decisión/Consecuencias) no — un cambio de decisión exige un ADR nuevo que la referencia vía `supersedes`. Sí se permite corregir typos, reparar links, y actualizar `status`/`implementation_status`/`updated` en el front matter a medida que el código avanza — ver "Regla de inmutabilidad" abajo. |
| `analyses/` | Análisis técnicos independientes que no son en sí mismos una decisión (benchmarks, auditorías, comparativas). Numeración `ANL-NNN`. | Investigación que informa una decisión futura pero no la fija. | Sí, mientras siga siendo la versión vigente del análisis. |
| `support/<DOC-ID>/` | Material subordinado no normativo de un RFC o ADR puntual: mapas de implementación, notas de planificación. | Cuando un documento necesita desglose operativo que ensuciaría el documento normativo, pero no es él mismo una decisión. | Sí, mientras el documento que aterriza siga vigente. |
| `evidence/<DOC-ID>/` | Artefactos crudos que respaldan un RFC o ADR puntual: logs de test, patches aplicados localmente, scripts de reproducción, capturas de CI. | Cuando un documento afirma un resultado medido ("15 tests passed", "cero bytes a DeepSeek") y ese resultado debe poder auditarse después. | No — es evidencia, se agrega, no se reescribe. |
| `templates/` | Plantillas para arrancar un RFC o ADR nuevo sin reinventar la estructura cada vez. | Al crear un documento nuevo en `rfcs/` o `adrs/`. | Sí, cuando la convención misma cambia. |
| `archive/` | Documentos superseded: siguen siendo legibles y citables por su valor histórico, pero ningún trabajo activo depende de ellos como fuente de verdad. | Cuando un RFC nuevo reemplaza a uno viejo, o una ronda de revisión adversarial produce una versión siguiente. | No. |

## Convenciones de numeración

- **RFC-NNN**: 3 dígitos, secuencial por orden de creación — no se reutiliza un número aunque el documento se archive. **Regla hacia adelante:** una propuesta conserva su ID durante toda su evolución; la versión vive en metadata/changelog, no en un número de RFC nuevo. Un RFC-NNN nuevo se crea solo cuando cambia la pregunta o la unidad de decisión, no por cada ronda de revisión.
- **Excepción legada, documentada, no repetible:** RFC-001 a RFC-006 son 6 rondas de revisión adversarial de la misma propuesta (el egress gate), cada una con su propio número. Eso predata esta regla y no se renumera retroactivamente — cada ronda es en sí misma un artefacto citable (ver el "qué aportó / qué no vio" de la Apéndice D de RFC-006), así que archivarlas por separado en vez de colapsarlas conserva ese historial. El archivo vigente de esa línea es `rfcs/RFC-006-provider-safe-routing.md`; RFC-001 a RFC-005 son lectura histórica en `archive/`.
- **ADR-NNN**: 3 dígitos, secuencial, un número por decisión. Material de apoyo no normativo va en `support/ADR-NNN/`, nunca comparte nombre de archivo con el ADR.
- Los nombres de archivo **no llevan número de versión** en `rfcs/`/`adrs/` vigentes (nada de `-v0.3`, `-v0.9`). La versión vive en el header del documento (`**Versión:** 0.9`) y en su propio changelog interno. Cuando una versión nueva reemplaza a la anterior de forma sustancial, la anterior se mueve completa a `archive/` con un sufijo de versión que la distinga (`RFC-007-ai-control-plane-v0.3.md`) — ahí sí importa, porque conviven dos archivos con el mismo número de RFC.
- Los RFC y ADR nuevos arrancan desde `templates/RFC-TEMPLATE.md` / `templates/ADR-TEMPLATE.md`. El front matter va **literalmente al principio del archivo, delimitado por `---`, antes del H1** — un bloque \`\`\`yaml\`\`\` dentro del cuerpo no es front matter, ningún parser lo procesa. Campos: `id`, `type`, `title`, `status`, `created`, `updated`, `supersedes`, `superseded_by`, `related`; los ADR agregan `implementation_status` (dimensión separada de `status`: una decisión puede estar `accepted` con `implementation_status: not-started`), `support`, `evidence`. Los documentos vigentes anteriores a esta convención (RFC-006/007/008, ADR-001/002) todavía no tienen front matter real — se agrega cuando se editen por otra razón, no como un pase de reformateo aparte.

## Regla de inmutabilidad

"No se edita después de cerrada" no significa "no se toca nunca". Se distingue:

- **Contenido normativo** (qué se decidió, por qué, sus consecuencias): no se reescribe. Un cambio de decisión es un documento nuevo que referencia al anterior vía `supersedes`/`superseded_by`.
- **Correcciones no normativas** (typos, links rotos, alineación de header con el ID de archivo): sí se permiten, siempre en un commit propio y explicable.
- **Metadata operativa** (`status`, `implementation_status`, `updated`, rutas en `support`/`evidence`): sí se actualiza a medida que el código avanza — de lo contrario el documento miente sobre el estado real apenas el código cambia. Es exactamente lo que le pasó a ADR-002 (ver abajo).

## Estado actual (2026-07-12)

**Vigentes** (`rfcs/`): RFC-006 (diseño validado del egress gate — fuente de verdad de invariantes), RFC-007 (documento rector del Control Plane + plan de implementación ejecutable), RFC-008 (acceso MCP gobernado).

**Archivadas** (`archive/`): RFC-001 a RFC-005 (rondas previas del egress gate, cada una superseded por la siguiente), RFC-007 v0.3 (superseded por la versión vigente).

**Decisiones** (`adrs/`): ADR-001 (chunking RAG, aceptada). ADR-002 (catálogo versionado de precios, **aceptada, `implementation_status: implemented`**, cerrada 2026-07-07 — el propio archivo decía "propuesta" hasta que se corrigió en este reorg, quedó desactualizado desde que se cerró). Las entregas reales de ADR-002 están etiquetadas en git como `etapa 1, 2, 3, 5, 6` — **no existe un commit `etapa 4`**; ver la tabla de trazabilidad en `support/ADR-002/implementation-map.md` para el detalle verificado contra `git log`, no contra lo que el mapa planeaba originalmente.

**Sin contenido todavía:** `analyses/`. `evidence/RFC-006/` y `evidence/RFC-007/` solo tienen el README de qué se espera — separadas porque RFC-006 es el diseño histórico (I1-I14, patch efímero nunca publicado) y RFC-007 es quien gobierna la reconstrucción real contra código (los 13 commits, I1-I15, el Draft PR). Ver `evidence/RFC-007/README.md` para la tabla de trazabilidad.

**Pendiente, no bloqueante:** un validador (`scripts/validate_decision_docs.py`) que chequee en CI nombres de archivo, unicidad de ID, coincidencia carpeta/tipo, front matter bien formado y ubicado, vocabulario de `status` válido, y links locales resolubles — hoy esa disciplina es manual.
