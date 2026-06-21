"""Dashboard interactivo con SSE, sender de tareas y panel de detalle."""

from __future__ import annotations

import html
from datetime import datetime, timezone


PROVIDER_COLORS = {
    "claude":   "#c45c1a",
    "deepseek": "#1e7d4f",
    "openai":   "#6366f1",
}

PROVIDER_BG = {
    "claude":   "#fff3ed",
    "deepseek": "#f0fdf4",
    "openai":   "#eef2ff",
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
    if v < 0.0001:
        return "<$0.0001"
    return f"${v:.4f}"


def _fmt_cache_pct(cr: object, inp: object) -> str:
    cache_read = _int_or_none(cr)
    input_tok = _int_or_none(inp)
    if not cache_read or not input_tok:
        return "—"
    pct = round(cache_read / input_tok * 100)
    return f"{pct}%"


def _model_color(model: str) -> tuple[str, str]:
    ml = model.lower()
    if "claude" in ml:
        return PROVIDER_COLORS["claude"], PROVIDER_BG["claude"]
    if "deepseek" in ml:
        return PROVIDER_COLORS["deepseek"], PROVIDER_BG["deepseek"]
    if "gpt" in ml or "openai" in ml:
        return PROVIDER_COLORS["openai"], PROVIDER_BG["openai"]
    return "#6b7280", "#f9fafb"


def _purpose_color(purpose: str) -> tuple[str, str]:
    pl = purpose.lower()
    if "claude" in pl:
        return PROVIDER_COLORS["claude"], PROVIDER_BG["claude"]
    if "deepseek" in pl:
        return PROVIDER_COLORS["deepseek"], PROVIDER_BG["deepseek"]
    if "openai" in pl or "gpt" in pl:
        return PROVIDER_COLORS["openai"], PROVIDER_BG["openai"]
    if "research" in pl:
        return "#6b3fa0", "#f3effe"
    if "router" in pl:
        return "#0f766e", "#f0fdfa"
    return "#6b7280", "#f9fafb"


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
    "pending":     ("#6b7280", "#f3f4f6"),
    "in_progress": ("#1d4ed8", "#dbeafe"),
    "completed":   ("#065f46", "#d1fae5"),
    "blocked":     ("#991b1b", "#fee2e2"),
    "skipped":     ("#9ca3af", "#f9fafb"),
}

_CTX_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "active":    ("#065f46", "#d1fae5"),
    "completed": ("#6b7280", "#f3f4f6"),
    "abandoned": ("#991b1b", "#fee2e2"),
}


def _build_contexts_section(contexts: list[dict]) -> str:
    if not contexts:
        return ""

    cards = ""
    for ctx in contexts:
        ctx_status = _text(ctx.get("status"), "active")
        sc, sbg = _CTX_STATUS_STYLE.get(ctx_status, ("#6b7280", "#f3f4f6"))
        steps = ctx.get("steps", [])

        steps_html = ""
        for step in steps:
            st = _text(step.get("status"), "pending")
            fc, fbg = _STEP_STATUS_STYLE.get(st, ("#6b7280", "#f3f4f6"))
            provider = _text(step.get("provider"))
            is_active = st == "in_progress"
            left_border = "border-left:3px solid #1d4ed8;" if is_active else "border-left:3px solid #e5e7eb;"
            active_bg = "background:#eff6ff;" if is_active else ""
            prov_html = ""
            if provider:
                pc = PROVIDER_COLORS.get(provider, "#6b7280")
                prov_html = f'<span style="font-size:10px;background:{pc};color:#fff;padding:1px 6px;border-radius:8px">{_escape(provider)}</span>'
            steps_html += (
                f'<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;{left_border}{active_bg}border-radius:4px;margin-bottom:2px">'
                f'<span style="font-size:11px;font-weight:700;color:#9ca3af;min-width:18px;text-align:center">{step.get("order_idx","?")}</span>'
                f'<span style="font-size:12px;color:#374151;flex:1">{_escape(_text(step.get("title")))}</span>'
                f'{prov_html}'
                f'<span style="font-size:10px;background:{fbg};color:{fc};padding:1px 6px;border-radius:8px;font-weight:600">{_escape(st)}</span>'
                f'</div>'
            )

        desc_html = ""
        if ctx.get("description"):
            desc_html = f'<p style="font-size:12px;color:#6b7280;margin-bottom:8px">{_escape(_text(ctx.get("description")))}</p>'

        body_html = steps_html if steps_html else '<p style="font-size:12px;color:#9ca3af">Sin pasos definidos.</p>'

        cards += (
            f'<div style="background:#fafafa;border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin-bottom:10px">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
            f'<span style="font-size:14px;font-weight:700;color:#1f2937;flex:1">{_escape(_text(ctx.get("title"), "(sin título)"))}</span>'
            f'<span style="font-size:11px;color:#6b7280">{_escape(_text(ctx.get("project")))}</span>'
            f'<span style="font-size:11px;background:{sbg};color:{sc};padding:2px 8px;border-radius:10px;font-weight:600">{_escape(ctx_status)}</span>'
            f'</div>'
            f'{desc_html}'
            f'<div>{body_html}</div>'
            f'</div>'
        )

    return (
        f'<div class="panel" style="margin-bottom:20px">'
        f'<h2>Contextos <span style="font-weight:400;text-transform:none;font-size:12px;color:#9ca3af">({len(contexts)})</span></h2>'
        f'{cards}'
        f'</div>'
    )


def build_html(runs: list[dict], selected_project: str = "", projects_extra: list[str] | None = None, contexts: list[dict] | None = None) -> str:
    selected_project = _text(selected_project)
    all_projects = sorted({_text(r.get("project")) for r in runs if _text(r.get("project"))})
    if projects_extra:
        all_projects = sorted(set(all_projects) | set(projects_extra))

    filtered = runs if not selected_project else [r for r in runs if _text(r.get("project")) == selected_project]
    filtered_rev = list(reversed(filtered))

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
    cache_pct = round(total_cache_read / total_input_tok * 100) if total_input_tok else 0

    def _chart_bars(data: dict, max_val: int, color_fn) -> str:
        bars = ""
        for key, count in sorted(data.items(), key=lambda x: -x[1]):
            color, bg = color_fn(key)
            pct = round(count / max_val * 100)
            safe_key = _escape(key[:40])
            bars += f"""
        <div style="margin-bottom:10px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
            <span style="font-size:12px;font-weight:600;color:{color};background:{bg};padding:2px 8px;border-radius:12px">{safe_key}</span>
            <span style="font-size:12px;color:#555">{count}</span>
          </div>
          <div style="height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden">
            <div style="height:100%;width:{pct}%;background:{color};border-radius:4px"></div>
          </div>
        </div>"""
        return bars or '<p style="color:#9ca3af;font-size:13px">Sin datos</p>'

    provider_bars = _chart_bars(by_provider, max_prov, lambda p: (PROVIDER_COLORS.get(p, "#888"), PROVIDER_BG.get(p, "#f8f8f8")))
    model_bars    = _chart_bars(by_model, max_model, _model_color)
    purpose_bars  = _chart_bars(by_purpose, max_purpose, _purpose_color)
    contexts_section = _build_contexts_section(contexts or [])

    rows = ""
    for r in filtered_rev[:100]:
        prov  = _text(r.get("provider"), "?")
        color = PROVIDER_COLORS.get(prov, "#888")
        bg    = PROVIDER_BG.get(prov, "#f9fafb")
        badge = f'<span style="background:{bg};color:{color};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap">{_escape(prov)}</span>'
        model = _text(r.get("model"), "—")
        model_short = model.split("/")[-1] if "/" in model else model
        task_value = _text(r.get("task_preview") or r.get("task", ""))
        task = task_value[:80] + ("…" if len(task_value) > 80 else "")
        reason = _text(r.get("routing_reason"), "—")
        status_html = _status_badge(r.get("status", "done"))
        run_id = r.get("id", "")
        rows += f"""<tr data-run-id="{_escape(run_id)}" onclick="openDetail({_escape(run_id) if run_id else '0'})" style="cursor:pointer">
          <td style="padding:8px 10px;color:#6b7280;font-size:12px;white-space:nowrap">{_fmt_ts(r.get('ts',''))}</td>
          <td style="padding:8px 10px;font-weight:600;font-size:13px;color:#1f2937">{_escape(_text(r.get('project'), '—'))}</td>
          <td style="padding:8px 10px">{badge}</td>
          <td style="padding:8px 10px;font-size:12px;color:#6b7280">{_escape(model_short)}</td>
          <td style="padding:8px 10px;font-size:12px;color:#374151;text-align:right">{_fmt_ms(r.get('duration_ms'))}</td>
          <td style="padding:8px 10px;font-size:12px;color:#374151;text-align:right">{_fmt_tokens(r.get('input_tokens'), r.get('output_tokens'))}</td>
          <td style="padding:8px 10px;font-size:12px;color:#374151;text-align:right">{_fmt_cost(r.get('cost_usd'))}</td>
          <td style="padding:8px 10px;font-size:12px;color:#374151;text-align:center">{_fmt_cache_pct(r.get('cache_read_tokens'), r.get('input_tokens'))}</td>
          <td style="padding:8px 10px;font-size:12px;color:#6b7280;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{_escape(task_value)}">{_escape(task)}</td>
          <td style="padding:8px 10px;font-size:11px;color:#9ca3af">{status_html}</td>
        </tr>"""

    project_options = '<option value="">Todos los proyectos</option>'
    for p in all_projects:
        sel = 'selected' if p == selected_project else ''
        safe_project = _escape(p)
        project_options += f'<option value="{safe_project}" {sel}>{safe_project}</option>'

    project_options_form = '<option value="">-- elegir proyecto --</option>'
    for p in all_projects:
        project_options_form += f'<option value="{_escape(p)}">{_escape(p)}</option>'

    tokens_display = f"{total_tokens // 1000}K" if total_tokens >= 1000 else str(total_tokens)
    cost_display = f"${total_cost:.4f}" if total_cost > 0 else "—"
    cache_display = f"{cache_pct}%" if cache_pct else "—"
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Orchestrator Dashboard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;color:#111827}}
    .header{{background:#1f2937;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}
    .header h1{{font-size:18px;font-weight:700;letter-spacing:-.3px}}
    .header .meta{{font-size:11px;color:#9ca3af}}
    .container{{max-width:1500px;margin:0 auto;padding:20px 16px}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}}
    .card{{background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:16px}}
    .card .label{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#6b7280;font-weight:600;margin-bottom:6px}}
    .card .value{{font-size:26px;font-weight:700;color:#111827;line-height:1}}
    .card .sub{{font-size:11px;color:#9ca3af;margin-top:4px}}
    .grid-charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:20px}}
    .panel{{background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:16px}}
    .panel h2{{font-size:13px;font-weight:700;color:#374151;margin-bottom:14px;text-transform:uppercase;letter-spacing:.4px}}
    .toolbar{{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}}
    select,input,textarea{{border:1px solid #d1d5db;border-radius:6px;padding:6px 10px;font-size:13px;background:#fff;color:#374151}}
    textarea{{width:100%;min-height:80px;resize:vertical;font-family:inherit}}
    .btn{{padding:7px 16px;border-radius:6px;border:none;font-size:13px;font-weight:600;cursor:pointer}}
    .btn-primary{{background:#1f2937;color:#fff}}
    .btn-primary:hover{{background:#374151}}
    .btn-secondary{{background:#f3f4f6;color:#374151;border:1px solid #d1d5db}}
    table{{width:100%;border-collapse:collapse}}
    thead tr{{background:#f9fafb;border-bottom:2px solid #e5e7eb}}
    th{{padding:8px 10px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#6b7280;font-weight:600;white-space:nowrap}}
    tbody tr{{border-bottom:1px solid #f3f4f6;transition:background .1s}}
    tbody tr:hover{{background:#f9fafb}}
    .empty{{text-align:center;padding:40px;color:#9ca3af;font-size:14px}}
    .badge{{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600}}
    .badge-running{{background:#dbeafe;color:#1d4ed8;animation:pulse 1.5s ease-in-out infinite}}
    .badge-pending{{background:#fef3c7;color:#92400e}}
    .badge-failed{{background:#fee2e2;color:#991b1b}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
    .sender-panel{{background:#fff;border-radius:10px;border:1px solid #d1d5db;padding:16px;margin-bottom:20px;display:none}}
    .sender-panel.open{{display:block}}
    .sender-form{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
    @media(max-width:700px){{.sender-form{{grid-template-columns:1fr}}}}
    .sender-form .full{{grid-column:1/-1}}
    .detail-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:100}}
    .detail-overlay.open{{display:flex;align-items:flex-start;justify-content:flex-end}}
    .detail-panel{{background:#fff;width:min(640px,95vw);height:100vh;overflow-y:auto;padding:24px;box-shadow:-4px 0 24px rgba(0,0,0,.15)}}
    .detail-panel h3{{font-size:16px;font-weight:700;margin-bottom:16px;color:#1f2937}}
    .detail-section{{margin-bottom:16px}}
    .detail-section label{{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:#6b7280;margin-bottom:6px}}
    .detail-section pre{{background:#f8f9fa;border:1px solid #e5e7eb;border-radius:6px;padding:12px;font-size:12px;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow-y:auto;font-family:'Cascadia Code','Consolas',monospace}}
    .budget-bar{{height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden;margin-top:6px}}
    .budget-fill{{height:100%;border-radius:4px;transition:width .4s}}
    .close-btn{{float:right;background:none;border:none;font-size:20px;cursor:pointer;color:#6b7280;padding:0 4px}}
    .spinner{{display:inline-block;width:14px;height:14px;border:2px solid #e5e7eb;border-top-color:#1d4ed8;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    #toast{{position:fixed;bottom:20px;right:20px;background:#1f2937;color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;display:none;z-index:200}}
  </style>
</head>
<body>

<div class="header">
  <h1>&#11041; Orchestrator Dashboard</h1>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <form method="get" style="display:flex;align-items:center;gap:8px">
      <label style="font-size:13px;color:#9ca3af;font-weight:600">Proyecto:</label>
      <select name="project" onchange="this.form.submit()">{project_options}</select>
    </form>
    <button class="btn btn-secondary" onclick="toggleSender()" style="font-size:13px">+ Nueva tarea</button>
    <span class="meta">{now}</span>
  </div>
</div>

<div class="container">

  <div class="sender-panel" id="senderPanel">
    <h2 style="font-size:13px;font-weight:700;color:#374151;margin-bottom:14px;text-transform:uppercase;letter-spacing:.4px">Enviar tarea</h2>
    <div class="sender-form">
      <div>
        <label style="display:block;font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px">Proyecto</label>
        <select id="senderProject" style="width:100%">{project_options_form}</select>
      </div>
      <div>
        <label style="display:block;font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px">Modelo (opcional)</label>
        <select id="senderModel" style="width:100%">
          <option value="">Router automático</option>
          <option value="claude">Claude</option>
          <option value="openai">OpenAI</option>
          <option value="deepseek">DeepSeek</option>
        </select>
      </div>
      <div class="full">
        <label style="display:block;font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px">Tarea</label>
        <textarea id="senderTask" placeholder="Describí la tarea que querés resolver..."></textarea>
      </div>
      <div class="full" style="display:flex;gap:8px;align-items:center">
        <button class="btn btn-primary" onclick="submitTask()">Enviar</button>
        <span id="senderStatus" style="font-size:12px;color:#6b7280"></span>
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
    </div>
    <div class="card">
      <div class="label">Tokens Usados</div>
      <div class="value">{tokens_display}</div>
    </div>
    <div class="card">
      <div class="label">Cache Savings</div>
      <div class="value">{cache_display}</div>
      <div class="sub">de input via cache</div>
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

  {contexts_section}

  <div class="panel" style="margin-bottom:20px;overflow-x:auto">
    <h2>Runs <span id="runs-count" style="font-weight:400;text-transform:none;letter-spacing:0;font-size:12px;color:#9ca3af">({len(filtered_rev[:100])} de {total})</span></h2>
    {'<table id="runs-table"><thead><tr><th>Fecha</th><th>Proyecto</th><th>Proveedor</th><th>Modelo</th><th style="text-align:right">Dur.</th><th style="text-align:right">Tokens</th><th style="text-align:right">Costo</th><th style="text-align:center">Cache</th><th>Tarea</th><th>Estado</th></tr></thead><tbody id="runs-body">' + rows + '</tbody></table>' if rows else '<table id="runs-table" style="display:none"><thead><tr><th>Fecha</th><th>Proyecto</th><th>Proveedor</th><th>Modelo</th><th style="text-align:right">Dur.</th><th style="text-align:right">Tokens</th><th style="text-align:right">Costo</th><th style="text-align:center">Cache</th><th>Tarea</th><th>Estado</th></tr></thead><tbody id="runs-body"></tbody></table><p class="empty" id="empty-msg">No hay runs aún. Usá el botón <strong>+ Nueva tarea</strong> para enviar una.</p>'}
  </div>

</div>

<div class="detail-overlay" id="detailOverlay" onclick="closeDetail(event)">
  <div class="detail-panel" id="detailPanel">
    <button class="close-btn" onclick="closeDetail()">&#x2715;</button>
    <h3>Detalle del run</h3>
    <div id="detailContent"><p style="color:#9ca3af;font-size:13px">Cargando...</p></div>
  </div>
</div>

<div id="toast"></div>

<script>
const evtSource = new EventSource("/events");
evtSource.addEventListener("run_started", e => {{
  const d = JSON.parse(e.data);
  prependPendingRow(d);
}});
evtSource.addEventListener("run_done", e => {{
  const d = JSON.parse(e.data);
  updateRow(d);
  showToast("Run #" + d.run_id + " completado — " + (d.provider || "?") + " " + (d.cost_usd ? "$" + d.cost_usd.toFixed(4) : ""));
}});
evtSource.addEventListener("run_failed", e => {{
  const d = JSON.parse(e.data);
  markFailed(d);
  showToast("Run #" + d.run_id + " falló: " + d.error, true);
}});
evtSource.addEventListener("budget_warning", e => {{
  const d = JSON.parse(e.data);
  updateBudgetGauge(d);
}});

function prependPendingRow(d) {{
  const tbody = document.getElementById("runs-body");
  const empty = document.getElementById("empty-msg");
  if (empty) empty.style.display = "none";
  const table = document.getElementById("runs-table");
  if (table) table.style.display = "";
  const tr = document.createElement("tr");
  tr.dataset.runId = d.run_id;
  tr.style.cursor = "pointer";
  tr.onclick = () => openDetail(d.run_id);
  tr.innerHTML = `
    <td style="padding:8px 10px;color:#6b7280;font-size:12px;white-space:nowrap">ahora</td>
    <td style="padding:8px 10px;font-weight:600;font-size:13px;color:#1f2937">${{escHtml(d.project)}}</td>
    <td style="padding:8px 10px"><span class="badge badge-pending">… pending</span></td>
    <td colspan="7" style="padding:8px 10px;font-size:12px;color:#9ca3af"><span class="spinner"></span> esperando respuesta...</td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);
}}

function updateRow(d) {{
  const tr = document.querySelector(`tr[data-run-id="${{d.run_id}}"]`);
  if (!tr) return;
  tr.cells[2].innerHTML = '<span style="background:#f0fdf4;color:#15803d;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">done</span>';
  if (tr.cells[3]) {{
    tr.cells[3].colSpan = 1;
    tr.cells[3].textContent = d.model ? d.model.split("/").pop() : "?";
    for (let i = 4; i < 10; i++) {{
      if (!tr.cells[i]) {{
        const td = tr.insertCell(i);
        td.style.padding = "8px 10px";
        td.style.fontSize = "12px";
        td.style.textAlign = i < 7 ? "right" : "left";
      }}
    }}
    tr.cells[4].textContent = d.duration_ms ? (d.duration_ms >= 1000 ? (d.duration_ms/1000).toFixed(1)+"s" : d.duration_ms+"ms") : "—";
    tr.cells[6].textContent = d.cost_usd ? "$" + parseFloat(d.cost_usd).toFixed(4) : "—";
  }}
}}

function markFailed(d) {{
  const tr = document.querySelector(`tr[data-run-id="${{d.run_id}}"]`);
  if (!tr) return;
  tr.cells[2].innerHTML = '<span class="badge badge-failed">✗ failed</span>';
  if (tr.cells[3]) tr.cells[3].textContent = d.error || "error";
}}

function updateBudgetGauge(d) {{
  const sec = document.getElementById("budgetSection");
  const pct = Math.min(d.pct * 100, 100).toFixed(0);
  const color = d.pct >= 1.0 ? "#ef4444" : d.pct >= 0.8 ? "#f59e0b" : "#22c55e";
  sec.innerHTML = `<div class="panel" style="margin-bottom:20px">
    <h2>Presupuesto diario — ${{escHtml(d.project)}}</h2>
    <div style="display:flex;justify-content:space-between;font-size:12px;color:#6b7280;margin-bottom:4px">
      <span>Gastado: <strong>$${{parseFloat(d.spent_usd).toFixed(4)}}</strong></span>
      <span>Límite: <strong>$${{parseFloat(d.limit_usd).toFixed(2)}}</strong></span>
      <span style="color:${{color}};font-weight:700">${{pct}}%</span>
    </div>
    <div class="budget-bar"><div class="budget-fill" style="width:${{pct}}%;background:${{color}}"></div></div>
  </div>`;
}}

function openDetail(runId) {{
  if (!runId) return;
  const overlay = document.getElementById("detailOverlay");
  const content = document.getElementById("detailContent");
  overlay.classList.add("open");
  content.innerHTML = '<p style="color:#9ca3af;font-size:13px"><span class="spinner"></span> Cargando...</p>';
  fetch("/run/" + runId)
    .then(r => r.json())
    .then(data => {{
      const provColor = {{"claude":"#c45c1a","deepseek":"#1e7d4f","openai":"#6366f1"}}[data.provider] || "#555";
      content.innerHTML = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
          <span style="background:#f3f4f6;color:#374151;padding:3px 10px;border-radius:10px;font-size:12px"><strong>ID:</strong> ${{data.id}}</span>
          <span style="color:${{provColor}};padding:3px 10px;border-radius:10px;font-size:12px;font-weight:600">${{escHtml(data.provider)}}</span>
          <span style="background:#f3f4f6;color:#374151;padding:3px 10px;border-radius:10px;font-size:12px">${{escHtml(data.model)}}</span>
          <span style="background:#f3f4f6;color:#374151;padding:3px 10px;border-radius:10px;font-size:12px">${{data.duration_ms ? (data.duration_ms/1000).toFixed(1)+"s" : "—"}}</span>
          ${{data.cost_usd ? `<span style="background:#f0fdf4;color:#15803d;padding:3px 10px;border-radius:10px;font-size:12px;font-weight:600">$${{parseFloat(data.cost_usd).toFixed(4)}}</span>` : ''}}
        </div>
        <div class="detail-section">
          <label>Tarea enviada</label>
          <pre>${{escHtml(data.task || data.task_preview || "(sin texto)")}}</pre>
        </div>
        <div class="detail-section">
          <label>Respuesta del modelo</label>
          <pre>${{escHtml(data.response || "(sin respuesta aún)")}}</pre>
        </div>
        <div class="detail-section">
          <label>Razón de ruteo</label>
          <p style="font-size:13px;color:#374151">${{escHtml(data.routing_reason || "—")}}</p>
        </div>
        ${{data.cache_read_tokens ? `<div class="detail-section">
          <label>Cache Claude</label>
          <p style="font-size:13px;color:#374151">
            Leídos del cache: <strong>${{data.cache_read_tokens}}</strong> tokens
            ${{data.cache_creation_tokens ? ` · Escritos al cache: <strong>${{data.cache_creation_tokens}}</strong>` : ''}}
          </p>
        </div>` : ''}}
      `;
    }})
    .catch(() => {{ content.innerHTML = '<p style="color:#ef4444;font-size:13px">Error al cargar detalle.</p>'; }});
}}

function closeDetail(e) {{
  if (e && e.target !== document.getElementById("detailOverlay")) return;
  document.getElementById("detailOverlay").classList.remove("open");
}}

function toggleSender() {{
  document.getElementById("senderPanel").classList.toggle("open");
}}

function submitTask() {{
  const project = document.getElementById("senderProject").value;
  const task    = document.getElementById("senderTask").value.trim();
  const model   = document.getElementById("senderModel").value;
  const status  = document.getElementById("senderStatus");
  if (!project) {{ status.textContent = "Seleccioná un proyecto."; return; }}
  if (!task)    {{ status.textContent = "La tarea no puede estar vacía."; return; }}
  status.innerHTML = '<span class="spinner"></span> Enviando...';
  fetch("/run", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{project, task, model: model || undefined}}),
  }})
  .then(r => r.json())
  .then(d => {{
    status.textContent = "Run #" + d.run_id + " enviado.";
    document.getElementById("senderTask").value = "";
  }})
  .catch(() => {{ status.textContent = "Error al enviar."; }});
}}

function showToast(msg, isError) {{
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.background = isError ? "#ef4444" : "#1f2937";
  t.style.display = "block";
  setTimeout(() => {{ t.style.display = "none"; }}, 4000);
}}

function escHtml(s) {{
  if (s == null) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}
</script>

</body>
</html>"""
