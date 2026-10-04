"""Dashboard interactivo con SSE, sender de tareas y panel de detalle."""

from __future__ import annotations

import html
import json
import urllib.parse
from datetime import datetime
from orchestrator.dashboard_js import _JS_FILES
from orchestrator.static_assets import StaticBundle, build_bundle
from orchestrator.timeutil import local_date_from_ts as _local_date_from_ts
from orchestrator.legacy_dashboard import actividad, config, datos, flujos, proyectos
from orchestrator.legacy_dashboard.common import (  # noqa: F401  (API usada por cli, server y tests)
    PROVIDER_COLORS,
    PROVIDER_BG,
    _text,
    _int_or_none,
    _float_or_none,
    _escape,
    _json_for_script,
    _fmt_ts,
    _fmt_ms,
    _fmt_tokens,
    _fmt_cost,
    _fmt_cache_pct,
    _model_color,
    _purpose_color,
    _purpose_bucket,
    _status_badge,
    _STEP_STATUS_STYLE,
    _CTX_STATUS_STYLE,
)
from orchestrator.legacy_dashboard.flujos import _build_contexts_section  # noqa: F401


NAV_SECTIONS = (
    ("Proyecto", (("inicio", "Inicio"), ("trabajo", "Trabajo"), ("ejecuciones", "Ejecuciones"), ("gobernanza", "Gobernanza"))),
    ("Control", (("proveedores", "Proveedores"), ("politicas", "Políticas"), ("ajustes", "Ajustes"))),
)
STYLESHEETS = ("tokens.css", "base.css", "components.css", "legacy/legacy.css")


def _shell_navigation(selected_project: str = "") -> str:
    """Navegación 4 + 3 (spec §23.3); los enlaces conservan el proyecto y funcionan sin JS.

    Con JS, el shell los intercepta y cambia la sección sin recargar.
    """
    parts = []
    for group, sections in NAV_SECTIONS:
        parts.append(f'    <p class="shell-nav-group">{group}</p>\n')
        for view, label in sections:
            query = {"project": selected_project, "view": view} if selected_project else {"view": view}
            href = _escape("/?" + urllib.parse.urlencode(query))
            parts.append(f'    <a class="shell-nav-link" href="{href}" data-view="{view}">{label}</a>\n')
    return "".join(parts)


def build_html(runs: list[dict], selected_project: str = "", projects_extra: list[str] | None = None,
               session_token: str = "", static_bundle: StaticBundle | None = None) -> str:
    selected_project = _text(selected_project)
    all_projects = sorted({_text(r.get("project")) for r in runs if _text(r.get("project"))})
    if projects_extra:
        all_projects = sorted(set(all_projects) | set(projects_extra))

    filtered = runs if not selected_project else [r for r in runs if _text(r.get("project")) == selected_project]

    total = len(filtered)
    by_provider: dict[str, int] = {}
    by_model: dict[str, int] = {}
    by_purpose: dict[str, int] = {}
    total_tokens = 0
    total_dur = 0
    dur_count = 0
    total_cost = 0.0
    total_cache_read = 0
    total_input_tok = 0

    for r in filtered:
        p = _text(r.get("provider"), "?")
        by_provider[p] = by_provider.get(p, 0) + 1

        m = _text(r.get("model"), "?")
        m_short = m.split("/")[-1] if "/" in m else m
        by_model[m_short] = by_model.get(m_short, 0) + 1

        purpose = _purpose_bucket(r.get("routing_reason"), p)
        by_purpose[purpose] = by_purpose.get(purpose, 0) + 1

        in_t = _int_or_none(r.get("input_tokens")) or 0
        out_t = _int_or_none(r.get("output_tokens")) or 0
        total_tokens += in_t + out_t
        total_input_tok += in_t
        total_cache_read += _int_or_none(r.get("cache_read_tokens")) or 0

        cost_v = _float_or_none(r.get("cost_usd"))
        if cost_v:
            total_cost += cost_v

        duration = _int_or_none(r.get("duration_ms"))
        if duration is not None:
            total_dur += duration
            dur_count += 1

    avg_dur = total_dur // dur_count if dur_count else None
    max_prov = max(by_provider.values(), default=1)
    max_model = max(by_model.values(), default=1)
    max_purpose = max(by_purpose.values(), default=1)
    _cache_denominator = total_input_tok + total_cache_read
    cache_pct = round(total_cache_read / _cache_denominator * 100) if _cache_denominator else 0

    def _chart_bars(data: dict, max_val: int, color_fn) -> str:
        bars = ""
        for key, count in sorted(data.items(), key=lambda x: -x[1]):
            color, bg = color_fn(key)
            pct = round(count / max_val * 100)
            safe_key = _escape(key[:40])
            bars += f"""
        <div style="margin-bottom:10px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px">
            <span style="font-size:12px;font-weight:600;color:{color};background:{bg};padding:2px 9px;border-radius:20px">{safe_key}</span>
            <span class="text-muted" style="font-size:12px;font-variant-numeric:tabular-nums">{count}</span>
          </div>
          <div style="height:5px;background:var(--border);border-radius:3px;overflow:hidden">
            <div style="height:100%;width:{pct}%;background:{color};border-radius:3px;opacity:.85"></div>
          </div>
        </div>"""
        return bars or '<p class="text-muted" style="font-size:13px">Sin datos</p>'

    provider_bars = _chart_bars(by_provider, max_prov, lambda p: (PROVIDER_COLORS.get(p, "#888"), PROVIDER_BG.get(p, "#f8f8f8")))
    model_bars    = _chart_bars(by_model, max_model, _model_color)
    purpose_bars  = _chart_bars(by_purpose, max_purpose, _purpose_color)

    import json as _json
    all_models = sorted(by_model.keys())
    # Si hay proyecto seleccionado enviar solo sus runs; si no, todos (para filtro client-side)
    _runs_for_js = filtered if selected_project else runs
    runs_json = _json_for_script(
        [{"id": r.get("id"), "ts": _text(r.get("ts")), "project": _text(r.get("project")),
          "provider": _text(r.get("provider")), "model": _text(r.get("model")),
          "status": _text(r.get("status","done")), "duration_ms": r.get("duration_ms"),
          "input_tokens": r.get("input_tokens"), "output_tokens": r.get("output_tokens"),
          "cost_usd": r.get("cost_usd"), "cache_read_tokens": r.get("cache_read_tokens"),
          "task_preview": _text(r.get("task_preview") or r.get("task","")),
          "routing_reason": _text(r.get("routing_reason",""))}
         for r in _runs_for_js]
    )

    project_options = '<option value="">Todos los proyectos</option>'
    for p in all_projects:
        sel = 'selected' if p == selected_project else ''
        safe_project = _escape(p)
        project_options += f'<option value="{safe_project}" {sel}>{safe_project}</option>'

    project_options_form = '<option value="">-- elegir proyecto --</option>'
    for p in all_projects:
        project_options_form += f'<option value="{_escape(p)}">{_escape(p)}</option>'

    filter_project_opts = '<option value="">Todos</option>'
    for p in all_projects:
        sel2 = 'selected' if p == selected_project else ''
        filter_project_opts += f'<option value="{_escape(p)}" {sel2}>{_escape(p)}</option>'

    filter_model_opts = '<option value="">Todos</option>'
    for m in all_models:
        filter_model_opts += f'<option value="{_escape(m)}">{_escape(m)}</option>'

    if total_tokens >= 1_000_000:
        tokens_display = f"{total_tokens / 1_000_000:.1f}M"
    elif total_tokens >= 1_000:
        tokens_display = f"{total_tokens // 1_000}K"
    else:
        tokens_display = str(total_tokens)
    now_dt = datetime.now().astimezone()
    _today = now_dt.date()
    cost_today = sum(
        (_float_or_none(r.get("cost_usd")) or 0)
        for r in filtered
        if _local_date_from_ts(_text(r.get("ts", ""))) == _today
    )
    if cost_today <= 0:
        cost_display = "—"
    elif cost_today >= 1:
        cost_display = f"${cost_today:.2f}"
    else:
        cost_display = f"${cost_today:.4f}"
    cache_display = f"{cache_pct}%" if cache_pct else "—"
    now = now_dt.strftime("%d/%m/%Y %H:%M ") + now_dt.strftime("%Z")

    _panel_actividad = actividad.panel(project_options_form=project_options_form, total=total, cost_display=cost_display, tokens_display=tokens_display, cache_display=cache_display, avg_dur=avg_dur, provider_bars=provider_bars, model_bars=model_bars, purpose_bars=purpose_bars, filter_project_opts=filter_project_opts, filter_model_opts=filter_model_opts)
    _panel_flujos = flujos.panel(project_options_form=project_options_form)
    _panel_proyectos = proyectos.panel()
    _panel_datos = datos.panel()
    _panel_config = config.panel()
    # El servidor pasa su instantánea de estáticos: el HTML y lo servido comparten versión.
    bundle = static_bundle or build_bundle()
    _stylesheets = "".join(f'  <link rel="stylesheet" href="{bundle.url(name)}">\n' for name in STYLESHEETS)
    # Los scripts heredados son clásicos y van en orden (comparten el ámbito global como
    # antes dentro del único bloque). Diferencia deliberada con el `try` anterior: un error
    # en un archivo detiene solo ese archivo; los demás siguen cargando, así una vista rota
    # no deja sin funcionar al resto. El aviso de error de carga se muestra igual.
    _legacy_scripts = "".join(f'<script src="{bundle.url(f"legacy/{name}.js")}"></script>\n' for name in _JS_FILES)
    _shell_script = bundle.url("shell.js")
    _navigation = _shell_navigation(selected_project)
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Orchestrator Dashboard</title>
  <script>try{{const _t=localStorage.getItem("theme");if(_t&&_t!=="dark")document.documentElement.setAttribute("data-theme",_t)}}catch(e){{}}</script>
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="icon" type="image/png" sizes="32x32" href="/static/img/favicons/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/static/img/favicons/favicon-16x16.png">
  <link rel="apple-touch-icon" href="/static/img/favicons/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
{_stylesheets}</head>
<body>

<div class="header">
  <h1><img src="/static/img/logo.png" alt="Orchestrator" style="height:28px;vertical-align:middle;margin-right:4px"></h1>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <form method="get" style="display:flex;align-items:center;gap:8px">
      <label style="font-size:12px;color:var(--text-muted);font-weight:500">Proyecto</label>
      <select name="project" onchange="this.form.submit()">{project_options}</select>
      <input type="hidden" name="view" id="shell-view-input" value="">
    </form>
    <span class="shell-status" id="shell-status" data-state="connecting" role="status">Conectando…</span>
    <button class="btn btn-secondary" onclick="toggleSender()">+ Nueva tarea</button>
    <button class="btn btn-secondary" onclick="toggleContextForm()">+ Nuevo flujo</button>
    <a href="/docs" class="theme-btn" style="text-decoration:none">Docs</a>
    <a href="/mcp" class="theme-btn" style="text-decoration:none">MCP</a>
    <a href="/security" class="theme-btn" style="text-decoration:none">Seguridad</a>
    <select id="themeSelect" class="theme-btn" onchange="setTheme(this.value)" title="Cambiar tema">
      <option value="dark">Dark</option>
      <option value="light">Light</option>
      <option value="midnight">Midnight</option>
      <option value="nord">Nord</option>
      <option value="espresso">Espresso</option>
      <option value="a11y">Alto contraste</option>
    </select>
    <span class="meta">{now}</span>
  </div>
</div>

<div class="tabnav" hidden>
  <div class="tabnav-inner">
    <button class="tab-btn tab-active" id="tab-btn-actividad" onclick="switchTab('actividad')">Actividad</button>
    <button class="tab-btn" id="tab-btn-flujos" onclick="switchTab('flujos')">Flujos</button>
    <button class="tab-btn" id="tab-btn-proyectos" onclick="switchTab('proyectos')">Proyectos</button>
    <button class="tab-btn" id="tab-btn-datos" onclick="switchTab('datos')">Datos</button>
    <button class="tab-btn" id="tab-btn-config" onclick="switchTab('config')">Configuración</button>
  </div>
</div>

<div class="shell">
  <nav class="shell-nav" aria-label="Secciones">
{_navigation}  </nav>

  <main class="shell-main" id="shell-main">
    <nav class="shell-breadcrumb" id="shell-breadcrumb" aria-label="Ubicación"></nav>
    <h1 class="shell-title" id="shell-title"></h1>
    <p class="shell-note" id="shell-note" hidden></p>
    <div class="shell-tabs" id="shell-tabs" role="tablist" hidden></div>
    <section class="shell-empty" id="shell-empty" hidden>
      <h2 id="shell-empty-title"></h2>
      <p id="shell-empty-body"></p>
    </section>
    <div class="shell-view-root" id="view-root" hidden></div>
    <div id="legacy-views">
{_panel_actividad}{_panel_flujos}{_panel_proyectos}{_panel_datos}{_panel_config}    </div>
  </main>

  <aside class="shell-inspector" id="shell-inspector" aria-label="Inspector" data-open="false">
    <p class="inspector-heading">Inspector</p>
    <div class="inspector-empty" id="inspector-empty">
      <p>Seleccioná un contexto, paso, run o commit para ver su detalle acá.</p>
    </div>
    <div class="inspector-selection" id="inspector-selection" hidden>
      <p class="inspector-kind" id="inspector-kind"></p>
      <p class="inspector-id" id="inspector-id"></p>
      <button type="button" class="shell-button" data-action="clear-selection">Limpiar selección</button>
    </div>
  </aside>
</div>

<div class="detail-overlay" id="confirmModal" onclick="_confirmModalBackdrop(event)" style="align-items:center;justify-content:center">
  <div style="background:var(--bg-surface);border:1px solid var(--border);border-radius:12px;padding:28px 24px 20px;width:min(440px,92vw);box-shadow:var(--shadow-panel)">
    <h3 id="confirmModalTitle" style="margin:0 0 10px;font-size:15px;font-weight:700"></h3>
    <div id="confirmModalBody" style="font-size:13px;color:var(--text-secondary);line-height:1.6;margin-bottom:20px"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button class="btn btn-secondary" onclick="closeConfirmModal()">Cancelar</button>
      <button id="confirmModalOk" class="btn btn-primary" onclick="_confirmModalOk()">Confirmar</button>
    </div>
  </div>
</div>

<div class="detail-overlay" id="detailOverlay" onclick="closeDetail(event)">
  <div class="detail-panel" id="detailPanel">
    <button class="close-btn" onclick="closeDetail()">&#x2715;</button>
    <h3>Detalle del run</h3>
    <div id="detailContent"><p class="text-muted" style="font-size:13px">Cargando...</p></div>
  </div>
</div>

<div class="detail-overlay" id="ctxDetailOverlay" onclick="closeCtxDetail(event)">
  <div class="detail-panel" id="ctxDetailPanel">
    <button class="close-btn" onclick="document.getElementById('ctxDetailOverlay').classList.remove('open')">&#x2715;</button>
    <h3>Detalle del flujo</h3>
    <div id="ctxDetailContent"><p class="text-muted" style="font-size:13px">Cargando...</p></div>
  </div>
</div>

<div id="toast"></div>

<div class="activity-bar">
  <div class="activity-hdr">
    <div class="act-left" onclick="toggleActivity()">
      <span class="act-dot" id="act-dot"></span>
      <span class="act-title">Actividad</span>
      <span class="act-summary" id="act-summary">sin eventos</span>
    </div>
    <div class="act-actions" onclick="event.stopPropagation()">
      <button class="act-btn" id="actBtnDoctor" onclick="runDoctor(this)" title="Diagnosticar configuración (doctor)">doctor</button>
      <div class="act-btn-wrap">
        <button class="act-btn act-btn-split" id="actBtnFix" onclick="runFix(this,{{}})" title="Aplicar correcciones automáticas (fix)">fix</button><button class="act-btn act-btn-arr" onclick="toggleFixMenu(event)" title="Opciones de fix">▾</button>
        <div id="fixMenu" class="act-dropdown">
          <button onclick="runFix(document.getElementById('actBtnFix'),{{global_mcp:true}})">＋ MCP global</button>
          <button onclick="runFix(document.getElementById('actBtnFix'),{{sync:true}})">＋ sync CC / Git</button>
          <button onclick="runFix(document.getElementById('actBtnFix'),{{index:true}})">＋ index RAG</button>
          <button onclick="runFix(document.getElementById('actBtnFix'),{{all:true}})">— todo (--all)</button>
        </div>
      </div>
      <button class="act-btn" id="actBtnSync" onclick="runSync(this)" title="Importar sesiones Claude Code + commits Git (sync-cc / sync-git)">sync</button>
      <button class="act-btn" id="actBtnIndex" onclick="runIndexDocs(this)" title="Indexar proyecto seleccionado en ChromaDB (index-docs)">index</button>
    </div>
    <span class="act-toggle" id="act-toggle" onclick="toggleActivity()">▼</span>
  </div>
  <div id="activity-log" style="display:none"></div>
</div>

<meta name="orchestrator-session" content="{_escape(session_token)}">
<script>
window.__runsData = {runs_json};
</script>
<script>
window.addEventListener("error", function (event) {{
  if (document.readyState === "complete" || document.getElementById("js-init-error")) return;
  console.error("JS init error:", event.error || event.message);
  var box = document.createElement("div");
  box.id = "js-init-error";
  box.className = "js-init-error";
  box.textContent = "Error JS al cargar: " + event.message;
  document.body.prepend(box);
}});
</script>
{_legacy_scripts}<script>
_runsFilterProject = {_json_for_script(selected_project)};
_runsFilterModel   = "";
if (typeof renderRunsTable === "function") renderRunsTable();
else console.error("renderRunsTable no definida — revisar errores de script anteriores");
</script>
<script type="module" src="{_shell_script}"></script>

</body>
</html>"""
