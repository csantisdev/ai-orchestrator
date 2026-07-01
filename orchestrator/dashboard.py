"""Dashboard interactivo con SSE, sender de tareas y panel de detalle."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from orchestrator.dashboard_css import _build_css
from orchestrator.dashboard_js import _build_js


PROVIDER_COLORS = {
    "claude":   "#fb923c",
    "deepseek": "#22c55e",
    "openai":   "#818cf8",
}

PROVIDER_BG = {
    "claude":   "rgba(251,146,60,0.15)",
    "deepseek": "rgba(34,197,94,0.15)",
    "openai":   "rgba(129,140,248,0.15)",
}


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _escape(value: object) -> str:
    return html.escape(_text(value), quote=True)


def _fmt_ts(ts: object) -> str:
    value = _text(ts)
    try:
        dt = datetime.fromisoformat(value).astimezone()
        return dt.strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return value[:16]


def _fmt_ms(ms: object) -> str:
    value = _int_or_none(ms)
    if value is None:
        return "—"
    if value >= 3_600_000:
        return f"{value / 3_600_000:.1f}h"
    if value >= 60_000:
        return f"{value / 60_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}s"
    return f"{value}ms"


def _fmt_tokens(inp: object, out: object) -> str:
    input_tokens = _int_or_none(inp)
    output_tokens = _int_or_none(out)
    if input_tokens is None and output_tokens is None:
        return "—"
    total = (input_tokens or 0) + (output_tokens or 0)
    if total >= 1000:
        return f"{total // 1000}K"
    return str(total)


def _fmt_cost(cost: object) -> str:
    v = _float_or_none(cost)
    if v is None:
        return "—"
    if v > 0 and v < 0.0001:
        return "<0,0001 USD"
    formatted = f"{v:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} USD"


def _fmt_cache_pct(cr: object, inp: object) -> str:
    cache_read = _int_or_none(cr)
    input_tok = _int_or_none(inp) or 0
    if not cache_read:
        return "—"
    total = input_tok + cache_read
    pct = round(cache_read / total * 100)
    return f"{pct}%"


def _model_color(model: str) -> tuple[str, str]:
    ml = model.lower()
    if "claude" in ml:
        return PROVIDER_COLORS["claude"], PROVIDER_BG["claude"]
    if "deepseek" in ml:
        return PROVIDER_COLORS["deepseek"], PROVIDER_BG["deepseek"]
    if "gpt" in ml or "openai" in ml:
        return PROVIDER_COLORS["openai"], PROVIDER_BG["openai"]
    return "#71717a", "rgba(113,113,122,0.12)"


def _purpose_color(purpose: str) -> tuple[str, str]:
    pl = purpose.lower()
    if "claude" in pl:
        return PROVIDER_COLORS["claude"], PROVIDER_BG["claude"]
    if "deepseek" in pl:
        return PROVIDER_COLORS["deepseek"], PROVIDER_BG["deepseek"]
    if "openai" in pl or "gpt" in pl:
        return PROVIDER_COLORS["openai"], PROVIDER_BG["openai"]
    if "research" in pl:
        return "#c084fc", "rgba(192,132,252,0.12)"
    if "router" in pl:
        return "#38bdf8", "rgba(56,189,248,0.12)"
    return "#71717a", "rgba(113,113,122,0.12)"


def _purpose_bucket(reason: object, provider: object) -> str:
    rl = _text(reason).strip().lower()
    if "manual" in rl:
        return f"Manual · {_text(provider, '?')}"
    if "research" in rl:
        return "Research"
    if not rl or rl == "—":
        return "Sin razón"
    return "Router"


def _status_badge(status: object) -> str:
    s = _text(status, "done")
    if s == "running":
        return '<span class="badge badge-running">⟳ running</span>'
    if s == "pending":
        return '<span class="badge badge-pending">… pending</span>'
    if s == "failed":
        return '<span class="badge badge-failed">✗ failed</span>'
    return ""


_STEP_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "pending":     ("#71717a", "rgba(113,113,122,0.12)"),
    "in_progress": ("#38bdf8", "rgba(56,189,248,0.12)"),
    "completed":   ("#22c55e", "rgba(34,197,94,0.12)"),
    "blocked":     ("#f87171", "rgba(248,113,113,0.12)"),
    "skipped":     ("#52525b", "rgba(82,82,91,0.10)"),
}

_CTX_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "active":      ("#22c55e", "rgba(34,197,94,0.12)"),
    "programado":  ("#818cf8", "rgba(129,140,248,0.12)"),
    "completed":   ("#71717a", "rgba(113,113,122,0.12)"),
    "abandoned":   ("#f87171", "rgba(248,113,113,0.12)"),
}


def _build_contexts_section(contexts: list[dict]) -> str:
    if not contexts:
        return '<div id="contextsSection"></div>'

    cards = ""
    for ctx in contexts:
        ctx_id = ctx.get("id", "")
        ctx_status = _text(ctx.get("status"), "active")
        sc, sbg = _CTX_STATUS_STYLE.get(ctx_status, ("#6b7280", "#f3f4f6"))
        steps = ctx.get("steps", [])

        steps_html = ""
        for step in steps:
            st = _text(step.get("status"), "pending")
            fc, fbg = _STEP_STATUS_STYLE.get(st, ("#6b7280", "#f3f4f6"))
            provider = _text(step.get("provider"))
            is_active = st == "in_progress"
            left_border = "border-left:2px solid #38bdf8;" if is_active else "border-left:2px solid var(--border);"
            active_bg = "background:rgba(56,189,248,0.06);" if is_active else ""
            prov_html = ""
            if provider:
                pc = PROVIDER_COLORS.get(provider, "var(--text-muted)")
                pbg = PROVIDER_BG.get(provider, "rgba(113,113,122,0.12)")
                prov_html = f'<span style="font-size:10px;background:{pbg};color:{pc};padding:1px 7px;border-radius:20px;font-weight:600">{_escape(provider)}</span>'
            action_html = ""
            if is_active:
                sid = step.get("id", "")
                action_html = (
                    f'<button class="ctx-step-btn ctx-step-advance" onclick="advanceStep({sid},{ctx_id})" title="Completar y continuar">✓</button>'
                    f'<button class="ctx-step-btn ctx-step-skip" onclick="skipStep({sid},{ctx_id})" title="Omitir paso">↷</button>'
                )
            steps_html += (
                f'<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;{left_border}{active_bg}border-radius:6px;margin-bottom:2px">'
                f'<span class="step-idx">{step.get("order_idx","?")}</span>'
                f'<span class="step-title">{_escape(_text(step.get("title")))}</span>'
                f'{prov_html}'
                f'<span style="font-size:10px;background:{fbg};color:{fc};padding:1px 7px;border-radius:20px;font-weight:600">{_escape(st)}</span>'
                f'{action_html}'
                f'</div>'
            )

        desc_html = ""
        if ctx.get("description"):
            desc_html = f'<p class="ctx-desc">{_escape(_text(ctx.get("description")))}</p>'

        body_html = steps_html if steps_html else '<p class="ctx-desc" style="padding:8px 0">Sin pasos definidos.</p>'

        # Texto de tarea para el botón play: paso in_progress o título del contexto
        active_step = next((s for s in steps if _text(s.get("status")) == "in_progress"), None)
        run_task = _text(active_step.get("title") if active_step else ctx.get("title"))
        run_project = _text(ctx.get("project"))

        play_btn = ""
        if ctx_status == "active":
            play_btn = (
                f'<button class="ctx-step-btn ctx-play-btn" '
                f'data-project="{_escape(run_project)}" data-task="{_escape(run_task)}" '
                f'onclick="runContext(this)" '
                f'title="Ejecutar paso activo como nuevo run">▶ Ejecutar</button>'
            )

        ctx_title_escaped = _escape(_text(ctx.get("title"), "(sin título)"))
        delete_btn = (
            f'<button class="ctx-step-btn ctx-delete-btn" '
            f'onclick="deleteContext({ctx_id},\'{ctx_title_escaped}\')" '
            f'title="Eliminar contexto">✕</button>'
        )

        cards += (
            f'<div class="ctx-card">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
            f'<span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1">{ctx_title_escaped}</span>'
            f'<span style="font-size:11px;color:var(--text-faint);font-family:\'JetBrains Mono\',monospace">{_escape(_text(ctx.get("project")))}</span>'
            f'<span style="font-size:10px;background:{sbg};color:{sc};padding:2px 8px;border-radius:20px;font-weight:600">{_escape(ctx_status)}</span>'
            f'{play_btn}'
            f'<button onclick="openContextDetail({ctx_id})" class="ctx-step-btn" style="font-size:10px;padding:2px 8px;border-radius:20px">→ Detalle</button>'
            f'{delete_btn}'
            f'</div>'
            f'{desc_html}'
            f'<div>{body_html}</div>'
            f'</div>'
        )

    return (
        f'<div id="contextsSection"><div class="panel" style="margin-bottom:20px">'
        f'<h2>Contextos <span style="font-weight:400;text-transform:none;font-size:11px;color:var(--text-faint);letter-spacing:0">({len(contexts)})</span></h2>'
        f'{cards}'
        f'</div></div>'
    )



def build_html(runs: list[dict], selected_project: str = "", projects_extra: list[str] | None = None) -> str:
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
    runs_json = _json.dumps(
        [{"id": r.get("id"), "ts": _text(r.get("ts")), "project": _text(r.get("project")),
          "provider": _text(r.get("provider")), "model": _text(r.get("model")),
          "status": _text(r.get("status","done")), "duration_ms": r.get("duration_ms"),
          "input_tokens": r.get("input_tokens"), "output_tokens": r.get("output_tokens"),
          "cost_usd": r.get("cost_usd"), "cache_read_tokens": r.get("cache_read_tokens"),
          "task_preview": _text(r.get("task_preview") or r.get("task","")),
          "routing_reason": _text(r.get("routing_reason",""))}
         for r in _runs_for_js],
        ensure_ascii=False, default=str
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
    _today = now_dt.date().isoformat()
    cost_today = sum(
        (_float_or_none(r.get("cost_usd")) or 0)
        for r in filtered
        if _text(r.get("ts", "")).startswith(_today)
    )
    if cost_today <= 0:
        cost_display = "—"
    elif cost_today >= 1:
        cost_display = f"${cost_today:.2f}"
    else:
        cost_display = f"${cost_today:.4f}"
    cache_display = f"{cache_pct}%" if cache_pct else "—"
    now = now_dt.strftime("%d/%m/%Y %H:%M ") + now_dt.strftime("%Z")

    _css = _build_css()
    _js = _build_js()
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
  <style>{_css}</style>
</head>
<body>

<div class="header">
  <h1><img src="/static/img/logo.png" alt="Orchestrator" style="height:28px;vertical-align:middle;margin-right:4px"></h1>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <form method="get" style="display:flex;align-items:center;gap:8px">
      <label style="font-size:12px;color:var(--text-muted);font-weight:500">Proyecto</label>
      <select name="project" onchange="this.form.submit()">{project_options}</select>
    </form>
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

<div class="tabnav">
  <div class="tabnav-inner">
    <button class="tab-btn tab-active" id="tab-btn-actividad" onclick="switchTab('actividad')">Actividad</button>
    <button class="tab-btn" id="tab-btn-flujos" onclick="switchTab('flujos')">Flujos</button>
    <button class="tab-btn" id="tab-btn-proyectos" onclick="switchTab('proyectos')">Proyectos</button>
    <button class="tab-btn" id="tab-btn-metrics" onclick="switchTab('metrics')">Métricas</button>
    <button class="tab-btn" id="tab-btn-datos" onclick="switchTab('datos')">Datos</button>
    <button class="tab-btn" id="tab-btn-config" onclick="switchTab('config')">Configuración</button>
  </div>
</div>

<div id="tab-actividad">
<div class="container">

  <div class="sender-panel" id="senderPanel">
    <h2 style="font-size:13px;font-weight:700;color:var(--text-muted);margin-bottom:14px;text-transform:uppercase;letter-spacing:.4px">Enviar tarea</h2>
    <div class="sender-form">
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Proyecto</label>
        <select id="senderProject" style="width:100%">{project_options_form}</select>
      </div>
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Modelo (opcional)</label>
        <select id="senderModel" style="width:100%">
          <option value="">Router automático</option>
          <option value="claude">Claude</option>
          <option value="openai">OpenAI</option>
          <option value="deepseek">DeepSeek</option>
        </select>
      </div>
      <div class="full">
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Tarea</label>
        <textarea id="senderTask" placeholder="Describí la tarea que querés resolver..."></textarea>
      </div>
      <div class="full" style="display:flex;gap:8px;align-items:center">
        <button class="btn btn-primary" onclick="submitTask()">Enviar</button>
        <span id="senderStatus" class="text-muted" style="font-size:12px"></span>
      </div>
    </div>
  </div>

  <div class="cards">
    <div class="card">
      <div class="label">Total Runs</div>
      <div class="value" id="card-total">{total}</div>
    </div>
    <div class="card">
      <div class="label">Costo Hoy</div>
      <div class="value" id="card-cost">{cost_display}</div>
      <div class="sub">dólares estadounidenses (USD)</div>
    </div>
    <div class="card">
      <div class="label">Tokens Usados</div>
      <div class="value">{tokens_display}</div>
    </div>
    <div class="card">
      <div class="label">Ahorro en Caché</div>
      <div class="value">{cache_display}</div>
      <div class="sub">de tokens vía caché</div>
    </div>
    <div class="card">
      <div class="label">Duración Prom.</div>
      <div class="value">{_fmt_ms(avg_dur)}</div>
    </div>
  </div>

  <div id="budgetSection"></div>

  <div class="grid-charts">
    <div class="panel"><h2>Por Proveedor</h2>{provider_bars}</div>
    <div class="panel"><h2>Por Modelo</h2>{model_bars}</div>
    <div class="panel"><h2>Por Propósito</h2>{purpose_bars}</div>
  </div>

  <div class="panel" style="margin-bottom:20px;overflow-x:auto">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px">
      <h2 style="margin-bottom:0">Runs <span id="runs-count" style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)"></span></h2>
      <div style="display:flex;align-items:center;gap:6px;margin-left:auto;flex-wrap:wrap">
        <label style="font-size:11px;color:var(--text-muted)">Proyecto</label>
        <select id="filterProject" onchange="applyRunFilters()" style="font-size:12px;padding:4px 8px">{filter_project_opts}</select>
        <label style="font-size:11px;color:var(--text-muted)">Modelo</label>
        <select id="filterModel" onchange="applyRunFilters()" style="font-size:12px;padding:4px 8px">{filter_model_opts}</select>
        <button class="btn btn-secondary" onclick="exportCSV()" style="font-size:12px;padding:5px 12px">↓ CSV</button>
      </div>
    </div>
    <table id="runs-table" style="display:none"><thead><tr><th>Fecha</th><th>Proyecto</th><th>Proveedor</th><th>Modelo</th><th style="text-align:right">Dur.</th><th style="text-align:right">Tokens</th><th style="text-align:right">Costo (USD)</th><th style="text-align:center">Cache</th><th>Tarea</th><th>Estado</th></tr></thead><tbody id="runs-body"></tbody></table>
    <p class="empty" id="empty-msg" style="display:none">No hay runs aún. Usá el botón <strong>+ Nueva tarea</strong> para enviar una.</p>
    <div id="runs-pagination"></div>
  </div>

</div>
</div>

<div id="tab-flujos" style="display:none">
<div class="container">

  <div class="panel" style="margin-bottom:16px">
    <h2>Nuevo flujo</h2>
    <div class="sender-form">
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Proyecto</label>
        <select id="ctxProject" style="width:100%">{project_options_form}</select>
      </div>
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Título</label>
        <input id="ctxTitle" type="text" placeholder="Objetivo del contexto..." style="width:100%">
      </div>
      <div class="full">
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Descripción (opcional)</label>
        <input id="ctxDesc" type="text" placeholder="Detalle adicional..." style="width:100%">
      </div>
      <div class="full">
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Pasos</label>
        <div id="ctxSteps"></div>
        <button class="btn btn-secondary" onclick="addCtxStep()" style="margin-top:8px;font-size:12px;padding:5px 12px">+ Paso</button>
      </div>
      <div class="full" style="display:flex;gap:8px;align-items:center">
        <button class="btn btn-primary" onclick="submitContext()">Crear flujo</button>
        <span id="ctxStatus" class="text-muted" style="font-size:12px"></span>
      </div>
    </div>
  </div>

  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px">
    <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted)">Estado</span>
    <button class="pg-btn pg-btn-active ctx-filter-btn" id="ctx-filter-all" onclick="setCtxFilter('all')">Todos</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-active" onclick="setCtxFilter('active')">Activo</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-programado" onclick="setCtxFilter('programado')">Programado</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-completed" onclick="setCtxFilter('completed')">Completado</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-abandoned" onclick="setCtxFilter('abandoned')">Abandonado</button>
  </div>

  <div id="contextsSection"></div>

</div>
</div>

<div id="tab-proyectos" style="display:none">
<div class="container">
  <div id="proyectos-content" style="padding-top:4px">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
  </div>
</div>
</div>

<div id="tab-metrics" style="display:none">
<div class="container">
  <div id="metrics-content" style="padding-top:4px">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
  </div>
</div>
</div>

<div id="tab-datos" style="display:none">
<div class="container" style="padding-top:20px">
  <div id="datos-content">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
  </div>
</div>
</div>

<div id="tab-config" style="display:none">
<div class="container" style="padding-top:20px">
  <div id="config-content">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
  </div>
</div>
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

<script>
window.__runsData = {runs_json};
</script>
<script>
try {{
{_js}
}} catch(e) {{
  console.error("JS init error:", e);
  document.body.insertAdjacentHTML("afterbegin",
    "<div style='position:fixed;top:0;left:0;right:0;background:#ef4444;color:#fff;font-size:13px;padding:8px 16px;z-index:9999;font-family:monospace'>" +
    "Error JS al cargar: " + e.message + " — " + (e.stack||"").split("\\n")[0] + "</div>"
  );
}}
</script>
<script>
_runsFilterProject = {_json.dumps(selected_project)};
_runsFilterModel   = "";
if (typeof renderRunsTable === "function") renderRunsTable();
else console.error("renderRunsTable no definida — revisar errores de script anteriores");
</script>

</body>
</html>"""
