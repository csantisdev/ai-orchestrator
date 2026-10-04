# Frontend del dashboard

Módulos ES servidos sin build desde `/static/dashboard/<hash>/` (D1a; ver
`docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md`). Este archivo no se sirve: solo
se sirven las extensiones de `MEDIA_TYPES` en `orchestrator/static_assets.py`.

| Ruta | Qué es |
|---|---|
| `shell.js` | Shell (§23.4): navegación, breadcrumb, Inspector y montaje de vistas. |
| `core/store.js`, `core/router.js` | Estado de la UI y su espejo en la URL. |
| `core/sections.js` | Secciones y pestañas; cada una declara `module`, `legacy` o `empty`. |
| `core/api.js` | Único cliente de `/api/v1/` para las vistas. |
| `core/dom.js` | `h()` para construir DOM sin HTML ni handlers en línea. |
| `core/mount.js` | Monta y desmonta las vistas de `views/`. |
| `views/*.js` | Una vista migrada por sección (olas 3 a 6). |
| `legacy/` | Dashboard anterior, cubierto por la instantánea dorada. No se amplía. |

## Contrato de una vista

Migrar una sección es agregar `module: "./views/<id>.js"` en `core/sections.js`. Desde ese
momento el shell deja de mostrar su vista heredada (`legacy`) y monta el módulo:

```js
import { h } from "../core/dom.js";

export async function mount(root, { store, api, state, signal }) {
  const data = await api.get("/api/v1/work", { params: { project: state.project }, signal });
  root.replaceChildren(h("ul", { class: "work-list" }, data.items.map((item) =>
    h("li", { data: { sel: `context:${item.id}` } }, item.title))));
  return {
    update(next) { /* cambió la URL (pestaña, selección…) con la vista visible */ },
    unmount() { /* quitar listeners globales, timers, suscripciones */ },
  };
}
```

- `root` es un contenedor propio de ese montaje. Si la vista se reemplaza mientras todavía
  carga, lo que dibuje después queda fuera del documento.
- `signal` se aborta al salir de la vista; pasalo a cada `api.get`/`api.post`.
- `update(state)` recibe cada cambio del router mientras la vista sigue visible, incluidos
  los que llegan durante el montaje. `update` y `unmount` son opcionales.
- La selección se cambia con `store.set({ sel: "context:7" })`; la URL y el Inspector se
  actualizan solos.
- Un error de `mount` muestra un aviso en lugar de la vista. Un `ApiError` trae `status` y
  `reason`; `session_expired` significa que el servidor se reinició y hay que recargar.

## Reglas (RFC-009 C7 y línea base)

- Todo texto variable entra como nodo de texto (`h()` o `textContent`); nunca `innerHTML`.
- Sin handlers en línea, estilos en línea ni `style` por JS: clases de
  `components.css` y tokens de `tokens.css`. `tests/test_dashboard_linebase.py` lo verifica.
- Eventos por delegación con atributos `data-*`.
- Las vistas no llaman a `fetch`: usan `api`, que limita las rutas a `/api/v1/` y agrega la
  cabecera de sesión en los POST.

## Tests

`node --test tests/js/*.test.mjs` para los módulos puros (`core/`) y
`python -m pytest tests/` para el resto.
