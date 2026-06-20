"""Genera el HTML del dashboard a partir de los runs persistidos."""

from __future__ import annotations

import json
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


def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts).astimezone()
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return ts[:16]


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms >= 60_000:
        return f"{ms / 60_000:.1f}m"
    if ms >= 1_000:
        return f"{ms / 1_000:.1f}s"
    return f"{ms}ms"


def _fmt_tokens(inp: int | None, out: int | None) -> str:
    if inp is None and out is None:
        return "—"
    total = (inp or 0) + (out or 0)
    if total >= 1000:
        return f"{total // 1000}K"
    return str(total)


def build_html(runs: list[dict], selected_project: str = "") -> str:
    projects = sorted({r.get("project", "") for r in runs if r.get("project")})

    filtered = runs if not selected_project else [r for r in runs if r.get("project") == selected_project]
    filtered_rev = list(reversed(filtered))

    total = len(filtered)

    by_provider: dict[str, int] = {}
    total_tokens = 0
    total_dur = 0
    dur_count = 0
    for r in filtered:
        p = r.get("provider", "?")
        by_provider[p] = by_provider.get(p, 0) + 1
        total_tokens += (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        if r.get("duration_ms") is not None:
            total_dur += r["duration_ms"]
            dur_count += 1

    avg_dur = total_dur // dur_count if dur_count else None
    max_prov = max(by_provider.values(), default=1)

    provider_bars = ""
    for prov, count in sorted(by_provider.items(), key=lambda x: -x[1]):
        color = PROVIDER_COLORS.get(prov, "#888")
        bg    = PROVIDER_BG.get(prov, "#f8f8f8")
        pct   = round(count / max_prov * 100)
        provider_bars += f"""
        <div style="margin-bottom:10px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
            <span style="font-size:13px;font-weight:600;color:{color};background:{bg};padding:2px 8px;border-radius:12px">{prov}</span>
            <span style="font-size:13px;color:#555">{count} runs</span>
          </div>
          <div style="height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden">
            <div style="height:100%;width:{pct}%;background:{color};border-radius:4px;transition:width .3s"></div>
          </div>
        </div>"""

    rows = ""
    for r in filtered_rev[:100]:
        prov  = r.get("provider", "?")
        color = PROVIDER_COLORS.get(prov, "#888")
        bg    = PROVIDER_BG.get(prov, "#f9fafb")
        badge = f'<span style="background:{bg};color:{color};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap">{prov}</span>'
        model = r.get("model", "—")
        model_short = model.split("/")[-1] if "/" in model else model
        task = r.get("task_preview", "")[:80] + ("…" if len(r.get("task_preview", "")) > 80 else "")
        reason = r.get("routing_reason", "—")
        rows += f"""<tr>
          <td style="padding:8px 10px;color:#6b7280;font-size:12px;white-space:nowrap">{_fmt_ts(r.get('ts',''))}</td>
          <td style="padding:8px 10px;font-weight:600;font-size:13px;color:#1f2937">{r.get('project','—')}</td>
          <td style="padding:8px 10px">{badge}</td>
          <td style="padding:8px 10px;font-size:12px;color:#6b7280">{model_short}</td>
          <td style="padding:8px 10px;font-size:12px;color:#374151;text-align:right">{_fmt_ms(r.get('duration_ms'))}</td>
          <td style="padding:8px 10px;font-size:12px;color:#374151;text-align:right">{_fmt_tokens(r.get('input_tokens'), r.get('output_tokens'))}</td>
          <td style="padding:8px 10px;font-size:12px;color:#6b7280;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{task}">{task}</td>
          <td style="padding:8px 10px;font-size:11px;color:#9ca3af;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{reason}">{reason}</td>
        </tr>"""

    project_options = '<option value="">Todos los proyectos</option>'
    for p in projects:
        sel = 'selected' if p == selected_project else ''
        project_options += f'<option value="{p}" {sel}>{p}</option>'

    tokens_display = f"{total_tokens // 1000}K" if total_tokens >= 1000 else str(total_tokens)

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="15">
  <title>Orchestrator Dashboard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;color:#111827}}
    .header{{background:#1f2937;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between}}
    .header h1{{font-size:18px;font-weight:700;letter-spacing:-.3px}}
    .header .meta{{font-size:11px;color:#9ca3af}}
    .container{{max-width:1400px;margin:0 auto;padding:20px 16px}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}}
    .card{{background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:16px}}
    .card .label{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#6b7280;font-weight:600;margin-bottom:6px}}
    .card .value{{font-size:28px;font-weight:700;color:#111827;line-height:1}}
    .card .sub{{font-size:11px;color:#9ca3af;margin-top:4px}}
    .grid2{{display:grid;grid-template-columns:300px 1fr;gap:16px;margin-bottom:20px}}
    @media(max-width:700px){{.grid2{{grid-template-columns:1fr}}}}
    .panel{{background:#fff;border-radius:10px;border:1px solid #e5e7eb;padding:16px}}
    .panel h2{{font-size:13px;font-weight:700;color:#374151;margin-bottom:14px;text-transform:uppercase;letter-spacing:.4px}}
    .toolbar{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
    select{{border:1px solid #d1d5db;border-radius:6px;padding:6px 10px;font-size:13px;background:#fff;color:#374151}}
    table{{width:100%;border-collapse:collapse}}
    thead tr{{background:#f9fafb;border-bottom:2px solid #e5e7eb}}
    th{{padding:8px 10px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#6b7280;font-weight:600;white-space:nowrap}}
    tbody tr{{border-bottom:1px solid #f3f4f6}}
    tbody tr:hover{{background:#fafafa}}
    .empty{{text-align:center;padding:40px;color:#9ca3af;font-size:14px}}
  </style>
</head>
<body>
<div class="header">
  <h1>⬡ Orchestrator Dashboard</h1>
  <span class="meta">Auto-refresh 15s · {now}</span>
</div>
<div class="container">

  <div class="toolbar">
    <form method="get" style="display:flex;align-items:center;gap:8px">
      <label style="font-size:13px;color:#6b7280;font-weight:600">Proyecto:</label>
      <select name="project" onchange="this.form.submit()">{project_options}</select>
      <span style="font-size:12px;color:#9ca3af">mostrando {len(filtered_rev[:100])} de {total} runs</span>
    </form>
  </div>

  <div class="cards">
    <div class="card">
      <div class="label">Total Runs</div>
      <div class="value">{total}</div>
    </div>
    <div class="card">
      <div class="label">Tokens Usados</div>
      <div class="value">{tokens_display}</div>
    </div>
    <div class="card">
      <div class="label">Duración Promedio</div>
      <div class="value">{_fmt_ms(avg_dur)}</div>
    </div>
    <div class="card">
      <div class="label">Proveedores</div>
      <div class="value">{len(by_provider)}</div>
      <div class="sub">{", ".join(by_provider.keys()) or "—"}</div>
    </div>
  </div>

  <div class="grid2">
    <div class="panel">
      <h2>Uso por Proveedor</h2>
      {provider_bars if provider_bars else '<p style="color:#9ca3af;font-size:13px">Sin datos</p>'}
    </div>
    <div class="panel" style="overflow-x:auto">
      <h2>Runs Recientes</h2>
      {'<table><thead><tr><th>Fecha</th><th>Proyecto</th><th>Proveedor</th><th>Modelo</th><th style="text-align:right">Dur.</th><th style="text-align:right">Tokens</th><th>Tarea</th><th>Ruteo</th></tr></thead><tbody>' + rows + '</tbody></table>' if rows else '<p class="empty">No hay runs registrados aún.<br>Ejecutá <code>ai-orchestrator run ...</code> para ver el historial aquí.</p>'}
    </div>
  </div>

</div>
</body>
</html>"""
