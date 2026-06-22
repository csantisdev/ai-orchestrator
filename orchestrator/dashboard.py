"""Dashboard interactivo con SSE, sender de tareas y panel de detalle."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone


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
                    f'<button class="ctx-step-btn ctx-step-advance" onclick="advanceStep({sid},{ctx_id})" title="Marcar completado">✓</button>'
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

        cards += (
            f'<div class="ctx-card">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
            f'<span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1">{_escape(_text(ctx.get("title"), "(sin título)"))}</span>'
            f'<span style="font-size:11px;color:var(--text-faint);font-family:\'JetBrains Mono\',monospace">{_escape(_text(ctx.get("project")))}</span>'
            f'<span style="font-size:10px;background:{sbg};color:{sc};padding:2px 8px;border-radius:20px;font-weight:600">{_escape(ctx_status)}</span>'
            f'<button onclick="openContextDetail({ctx_id})" class="ctx-step-btn" style="font-size:10px;padding:2px 8px;border-radius:20px">→ Detalle</button>'
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


def _build_css() -> str:
    return """\n    :root{
      --bg-base:#09090b;--bg-surface:#111827;--bg-elevated:#0c0c0e;
      --bg-input:#18181b;--bg-code:#0f172a;
      --border:#27272a;--border-subtle:#1f1f23;--border-faint:#18181b;
      --text-primary:#f8fafc;--text-secondary:#a1a1aa;
      --text-muted:#71717a;--text-faint:#52525b;
      --text-code:#e2e8f0;--text-detail:#d1d5db;
      --overlay-bg:rgba(0,0,0,.65);--shadow-panel:-4px 0 40px rgba(0,0,0,.6);
    }
    [data-theme="light"]{
      --bg-base:#f8fafc;--bg-surface:#ffffff;--bg-elevated:#f1f5f9;
      --bg-input:#f4f4f5;--bg-code:#f0f4f8;
      --border:#e4e4e7;--border-subtle:#e4e4e7;--border-faint:#e2e8f0;
      --text-primary:#0f172a;--text-secondary:#52525b;
      --text-muted:#71717a;--text-faint:#a1a1aa;
      --text-code:#1e293b;--text-detail:#374151;
      --overlay-bg:rgba(0,0,0,.35);--shadow-panel:-4px 0 40px rgba(0,0,0,.1);
    }
    [data-theme="midnight"]{
      --bg-base:#0a0e1a;--bg-surface:#0f1629;--bg-elevated:#070b14;
      --bg-input:#141d35;--bg-code:#080c18;
      --border:#1e2d50;--border-subtle:#162040;--border-faint:#141d35;
      --text-primary:#e2e8f0;--text-secondary:#94a3b8;
      --text-muted:#64748b;--text-faint:#475569;
      --text-code:#cbd5e1;--text-detail:#b0bec5;
      --overlay-bg:rgba(0,0,0,.75);--shadow-panel:-4px 0 40px rgba(0,0,0,.7);
    }
    [data-theme="nord"]{
      --bg-base:#2e3440;--bg-surface:#3b4252;--bg-elevated:#292e39;
      --bg-input:#434c5e;--bg-code:#252a35;
      --border:#4c566a;--border-subtle:#434c5e;--border-faint:#3b4252;
      --text-primary:#eceff4;--text-secondary:#d8dee9;
      --text-muted:#a8b2c0;--text-faint:#7a8698;
      --text-code:#d8dee9;--text-detail:#c5ccd8;
      --overlay-bg:rgba(0,0,0,.55);--shadow-panel:-4px 0 40px rgba(0,0,0,.45);
    }
    [data-theme="espresso"]{
      --bg-base:#1c1410;--bg-surface:#261c14;--bg-elevated:#160f0a;
      --bg-input:#2e2018;--bg-code:#120d08;
      --border:#3d2e20;--border-subtle:#2d2218;--border-faint:#2e2018;
      --text-primary:#f5e6cf;--text-secondary:#c8a880;
      --text-muted:#8a7055;--text-faint:#6b5540;
      --text-code:#e8d5b0;--text-detail:#d4bc95;
      --overlay-bg:rgba(0,0,0,.7);--shadow-panel:-4px 0 40px rgba(0,0,0,.6);
    }
    [data-theme="a11y"]{
      --bg-base:#000000;--bg-surface:#0d0d0d;--bg-elevated:#000000;
      --bg-input:#141414;--bg-code:#000000;
      --border:#ffffff;--border-subtle:#cccccc;--border-faint:#999999;
      --text-primary:#ffffff;--text-secondary:#f0f0f0;
      --text-muted:#dddddd;--text-faint:#bbbbbb;
      --text-code:#ffffff;--text-detail:#eeeeee;
      --overlay-bg:rgba(0,0,0,.92);--shadow-panel:-4px 0 40px rgba(255,255,255,.12);
    }
    [data-theme="a11y"] *{letter-spacing:.03em}
    [data-theme="a11y"] body{font-size:15px}
    [data-theme="a11y"] select,
    [data-theme="a11y"] input,
    [data-theme="a11y"] textarea{border-width:2px;font-size:14px}
    [data-theme="a11y"] .btn{outline:2px solid currentColor;outline-offset:2px}
    [data-theme="a11y"] *:focus-visible{outline:3px solid #ffff00;outline-offset:2px}
    [data-theme="a11y"] a{text-decoration:underline}
    [data-theme="a11y"] .badge{outline:2px solid currentColor;outline-offset:1px;font-weight:700}
    [data-theme="a11y"] .badge-running{background:rgba(0,120,255,.25);color:#60b0ff}
    [data-theme="a11y"] .badge-pending{background:rgba(255,180,0,.25);color:#ffcc00}
    [data-theme="a11y"] .badge-failed{background:rgba(255,120,0,.25);color:#ff8800}
    [data-theme="a11y"] thead tr{border-top:2px solid var(--border);border-bottom:2px solid var(--border)}
    [data-theme="a11y"] tbody tr{border-bottom:1px solid var(--border-subtle)}
    [data-theme="a11y"] tbody tr:hover{background:rgba(255,255,255,.08);outline:2px solid var(--border);outline-offset:-2px}
    [data-theme="a11y"] .card{border-width:2px}
    [data-theme="a11y"] .panel{border-width:2px}
    [data-theme="a11y"] .detail-panel{border-left-width:3px}
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Inter',system-ui,sans-serif;background:var(--bg-base);color:var(--text-primary);-webkit-font-smoothing:antialiased;padding-bottom:48px}
    .activity-bar{position:fixed;bottom:0;left:0;right:0;background:var(--bg-elevated);border-top:1px solid var(--border);z-index:200;font-family:'JetBrains Mono',monospace}
    .activity-hdr{display:flex;align-items:center;gap:10px;padding:0 16px;height:40px;cursor:pointer;user-select:none;transition:background .1s}
    .activity-hdr:hover{background:var(--bg-surface)}
    .act-dot{width:7px;height:7px;border-radius:50%;background:var(--border);flex-shrink:0;transition:background .2s}
    .act-dot.live{background:#22c55e}
    .act-dot.pulse{animation:_adot .6s ease-in-out 3}
    @keyframes _adot{0%,100%{opacity:1}50%{opacity:.2}}
    .act-title{font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.7px;flex-shrink:0}
    .act-summary{font-size:11px;color:var(--text-faint);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0 8px}
    .act-toggle{font-size:10px;color:var(--text-faint);flex-shrink:0}
    #activity-log{max-height:200px;overflow-y:auto;border-top:1px solid var(--bg-input)}
    .tr-row{display:grid;grid-template-columns:80px 44px 14px 1fr 64px;gap:8px;padding:4px 16px;align-items:center;font-size:11px;border-bottom:1px solid var(--bg-elevated)}
    .tr-ts{color:var(--border);font-variant-numeric:tabular-nums}
    .tr-run{color:var(--text-faint);text-align:right}
    .tr-icon{text-align:center;font-size:12px}
    .tr-name{color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .tr-dur{color:var(--text-faint);text-align:right;font-variant-numeric:tabular-nums}
    .tr-running .tr-icon{color:#f59e0b}.tr-running .tr-name{color:var(--text-primary)}
    .tr-done .tr-icon{color:#22c55e}
    .tr-error .tr-icon{color:#f87171}.tr-error .tr-name{color:#f87171}
    .header{background:var(--bg-surface);border-bottom:1px solid var(--border);color:var(--text-primary);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
    .header h1{font-size:16px;font-weight:700;letter-spacing:-.4px;color:var(--text-primary)}
    .header .meta{font-size:11px;color:var(--text-muted)}
    .container{max-width:1500px;margin:0 auto;padding:20px 16px}
    .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
    .card{background:var(--bg-surface);border-radius:16px;border:1px solid var(--border);padding:18px}
    .card .label{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);font-weight:600;margin-bottom:8px}
    .card .value{font-size:28px;font-weight:700;color:var(--text-primary);line-height:1}
    .card .sub{font-size:11px;color:var(--text-faint);margin-top:5px}
    .grid-charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:20px}
    .panel{background:var(--bg-surface);border-radius:16px;border:1px solid var(--border);padding:18px}
    .panel h2{font-size:10px;font-weight:700;color:var(--text-muted);margin-bottom:14px;text-transform:uppercase;letter-spacing:.7px}
    .toolbar{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
    select,input,textarea{border:1px solid var(--border);border-radius:8px;padding:7px 12px;font-size:13px;background:var(--bg-input);color:var(--text-primary);font-family:inherit}
    textarea{width:100%;min-height:80px;resize:vertical}
    select:focus,input:focus,textarea:focus{outline:none;border-color:#22c55e}
    .btn{padding:7px 16px;border-radius:8px;border:none;font-size:13px;font-weight:600;cursor:pointer;transition:opacity .15s}
    .btn-primary{background:#22c55e;color:#09090b}
    .btn-primary:hover{opacity:.85}
    .btn-secondary{background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border)}
    .btn-secondary:hover{background:var(--border)}
    table{width:100%;border-collapse:collapse}
    thead tr{background:var(--bg-elevated);border-bottom:1px solid var(--border)}
    th{padding:9px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);font-weight:600;white-space:nowrap}
    tbody tr{border-bottom:1px solid var(--border-faint);transition:background .1s}
    tbody tr:hover{background:var(--bg-input)}
    .empty{text-align:center;padding:40px;color:var(--text-muted);font-size:14px}
    .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
    .badge-running{background:rgba(56,189,248,0.12);color:#38bdf8;animation:pulse 1.5s ease-in-out infinite}
    .badge-pending{background:rgba(251,191,36,0.12);color:#fcd34d}
    .badge-failed{background:rgba(248,113,113,0.12);color:#f87171}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
    .sender-panel{background:var(--bg-surface);border-radius:16px;border:1px solid var(--border);padding:18px;margin-bottom:20px;display:none}
    .sender-panel.open{display:block}
    .sender-form{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    @media(max-width:700px){.sender-form{grid-template-columns:1fr}}
    .sender-form .full{grid-column:1/-1}
    .detail-overlay{display:none;position:fixed;inset:0;background:var(--overlay-bg);z-index:100;backdrop-filter:blur(3px)}
    .detail-overlay.open{display:flex;align-items:flex-start;justify-content:flex-end}
    .detail-panel{background:var(--bg-surface);width:min(660px,95vw);height:100vh;overflow-y:auto;padding:24px;box-shadow:var(--shadow-panel);border-left:1px solid var(--border)}
    .detail-panel h3{font-size:15px;font-weight:700;margin-bottom:16px;color:var(--text-primary)}
    .detail-section{margin-bottom:18px}
    .detail-section label{display:block;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);margin-bottom:8px}
    .detail-section pre{background:var(--bg-code);border:1px solid var(--border);border-radius:12px;padding:14px;font-size:12px;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow-y:auto;font-family:'JetBrains Mono','Consolas',monospace;color:var(--text-code);line-height:1.65}
    .budget-bar{height:5px;background:var(--border);border-radius:3px;overflow:hidden;margin-top:8px}
    .budget-fill{height:100%;border-radius:3px;transition:width .4s}
    .close-btn{float:right;background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-muted);padding:0 4px}
    .close-btn:hover{color:var(--text-primary)}
    .spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:#22c55e;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle}
    @keyframes spin{to{transform:rotate(360deg)}}
    #toast{position:fixed;bottom:20px;right:20px;background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border);padding:10px 18px;border-radius:10px;font-size:13px;display:none;z-index:200;box-shadow:0 8px 24px rgba(0,0,0,.5)}
    .tabnav{background:var(--bg-surface);border-bottom:1px solid var(--border)}
    .tabnav-inner{max-width:1500px;margin:0 auto;padding:0 16px;display:flex;gap:2px}
    .tab-btn{background:none;border:none;border-bottom:2px solid transparent;color:var(--text-muted);font-size:13px;font-weight:500;padding:12px 14px;cursor:pointer;font-family:inherit;transition:color .15s,border-color .15s}
    .tab-btn:hover{color:var(--text-primary)}
    .tab-active{color:var(--text-primary);border-bottom-color:#22c55e}
    .insp-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}
    .insp-stat{background:var(--bg-input);border:1px solid var(--border);border-radius:12px;padding:14px}
    .insp-stat .col-name{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted);margin-bottom:8px;font-weight:600}
    .insp-stat .col-count{font-size:26px;font-weight:700;color:var(--text-primary);line-height:1}
    .insp-stat .col-sub{font-size:11px;color:var(--text-faint);margin-top:4px}
    .insp-stat .col-projects{margin-top:10px;border-top:1px solid var(--border);padding-top:8px}
    .insp-stat .col-proj-row{display:flex;justify-content:space-between;font-size:11px;padding:3px 0;border-bottom:1px solid var(--border-subtle)}
    .chip{background:var(--bg-input);color:var(--text-secondary);padding:3px 10px;border-radius:20px;font-size:11px}
    .chip-mono{background:var(--bg-input);color:var(--text-secondary);padding:3px 10px;border-radius:20px;font-size:11px;font-family:'JetBrains Mono',monospace}
    .td-ts{padding:9px 12px;color:var(--text-faint);font-size:11px;white-space:nowrap;font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums}
    .td-project{padding:9px 12px;font-weight:600;font-size:13px;color:var(--text-primary)}
    .td-muted{padding:9px 12px;font-size:12px;color:var(--text-muted)}
    .ctx-card{background:var(--bg-input);border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:10px}
    .ctx-desc{font-size:12px;color:var(--text-muted);margin-bottom:10px;line-height:1.5}
    .step-idx{font-size:11px;font-weight:700;color:var(--text-faint);min-width:18px;text-align:center;font-family:'JetBrains Mono',monospace}
    .step-title{font-size:12px;color:var(--text-detail);flex:1}
    .ctx-step-btn{background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;padding:2px 7px;cursor:pointer;font-family:inherit;line-height:1.4;flex-shrink:0;transition:background .12s,color .12s}
    .ctx-step-btn:hover{background:var(--bg-surface);color:var(--text-primary)}
    .ctx-step-advance:hover{border-color:#22c55e;color:#22c55e}
    .ctx-step-skip:hover{border-color:#f59e0b;color:#f59e0b}
    .pagination-bar{display:flex;align-items:center;gap:6px;padding:10px 0 4px;flex-wrap:wrap}
    .pg-btn{background:var(--bg-input);border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:11px;padding:3px 9px;cursor:pointer;font-family:inherit;transition:background .12s}
    .pg-btn:hover:not(:disabled){background:var(--border);color:var(--text-primary)}
    .pg-btn:disabled{opacity:.35;cursor:default}
    .pg-btn-active{background:#22c55e;color:#09090b;border-color:#22c55e}
    .pg-btn-active:hover{background:#22c55e}
    .budget-meta{display:flex;justify-content:space-between;font-size:12px;color:var(--text-muted);margin-bottom:6px}
    .detail-text{font-size:13px;color:var(--text-secondary);line-height:1.5}
    .detail-thead-row{color:var(--text-faint);border-bottom:1px solid var(--border)}
    .detail-tbody-row{border-bottom:1px solid var(--border-faint)}
    .td-sm{padding:5px 8px}
    .td-sm-ts{padding:5px 8px;color:var(--text-faint);white-space:nowrap;font-family:'JetBrains Mono',monospace}
    .td-sm-text{padding:5px 8px;color:var(--text-detail)}
    .td-sm-muted{padding:5px 8px;color:var(--text-secondary)}
    .td-sm-mono{padding:5px 8px;font-weight:600;color:var(--text-primary);font-family:'JetBrains Mono',monospace}
    .theme-btn{background:none;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-size:13px;padding:4px 10px;cursor:pointer;font-family:inherit;transition:color .15s,border-color .15s}
    .theme-btn:hover{color:var(--text-primary);border-color:var(--text-muted)}
    .text-muted{color:var(--text-muted)}
    .text-faint{color:var(--text-faint)}
    .text-primary{color:var(--text-primary)}
"""

def _build_js() -> str:
    return """\n
// ── Runs table state ─────────────────────────────────────────────────────────
let _runsPage = 0;
let _runsPageSize = 10;
let _runsFilterProject = "";
let _runsFilterModel = "";

function _fmtRunTs(iso) {
  try {
    return new Date(iso).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
  } catch { return (iso||"").slice(0,16); }
}
function _fmtRunDur(ms) {
  if (ms == null) return "—";
  if (ms >= 60000) return (ms/60000).toFixed(1)+"m";
  if (ms >= 1000)  return (ms/1000).toFixed(1)+"s";
  return ms+"ms";
}
function _fmtRunTokens(inp,out) {
  if (inp==null && out==null) return "—";
  const t=(inp||0)+(out||0);
  return t>=1000 ? Math.floor(t/1000)+"K" : String(t);
}
function _fmtRunCost(v) {
  if (v==null) return "—";
  return parseFloat(v)<0.0001 ? "<$0.0001" : "$"+parseFloat(v).toFixed(4);
}
function _fmtRunCache(cr,inp) {
  if (!cr||!inp) return "—";
  return Math.round(cr/inp*100)+"%";
}

function renderRunsTable() {
  const PROV_CLR = {claude:"#fb923c",deepseek:"#22c55e",openai:"#818cf8"};
  const PROV_BG  = {claude:"rgba(251,146,60,0.15)",deepseek:"rgba(34,197,94,0.15)",openai:"rgba(129,140,248,0.15)"};
  const data = (window.__runsData||[]).filter(r => {
    if (_runsFilterProject && r.project !== _runsFilterProject) return false;
    if (_runsFilterModel && (r.model||"").split("/").pop() !== _runsFilterModel) return false;
    return true;
  });
  const total = data.length;
  const totalPages = Math.max(1, Math.ceil(total/_runsPageSize));
  if (_runsPage >= totalPages) _runsPage = totalPages-1;
  const start = _runsPage*_runsPageSize;
  const pageData = data.slice(start, start+_runsPageSize);

  const tbody = document.getElementById("runs-body");
  const table = document.getElementById("runs-table");
  const empty = document.getElementById("empty-msg");
  if (!total) {
    if (table) table.style.display = "none";
    if (empty) empty.style.display = "";
    const pg = document.getElementById("runs-pagination");
    if (pg) pg.innerHTML = "";
    const cnt = document.getElementById("runs-count");
    if (cnt) cnt.textContent = "(0)";
    return;
  }
  if (table) table.style.display = "";
  if (empty) empty.style.display = "none";

  tbody.innerHTML = pageData.map(r => {
    const prov = r.provider||"?";
    const clr  = PROV_CLR[prov]||"#888";
    const bg   = PROV_BG[prov]||"rgba(113,113,122,0.12)";
    const badge = `<span style="background:${bg};color:${clr};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap">${escHtml(prov)}</span>`;
    const modelShort = (r.model||"—").split("/").pop();
    const task = r.task_preview||r.task||"";
    const taskD = task.length>80 ? task.slice(0,80)+"…" : task;
    let statusHtml = "";
    if (r.status==="running") statusHtml='<span class="badge badge-running">⟳ running</span>';
    else if (r.status==="pending") statusHtml='<span class="badge badge-pending">… pending</span>';
    else if (r.status==="failed")  statusHtml='<span class="badge badge-failed">✗ failed</span>';
    return `<tr data-run-id="${r.id}" onclick="openDetail(${r.id})" style="cursor:pointer">
      <td class="td-ts">${_fmtRunTs(r.ts)}</td>
      <td class="td-project">${escHtml(r.project||"—")}</td>
      <td style="padding:9px 12px">${badge}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);font-family:'JetBrains Mono',monospace">${escHtml(modelShort)}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);text-align:right;font-variant-numeric:tabular-nums">${_fmtRunDur(r.duration_ms)}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);text-align:right;font-variant-numeric:tabular-nums">${_fmtRunTokens(r.input_tokens,r.output_tokens)}</td>
      <td style="padding:9px 12px;font-size:12px;color:#22c55e;text-align:right;font-weight:500;font-variant-numeric:tabular-nums">${_fmtRunCost(r.cost_usd)}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);text-align:center">${_fmtRunCache(r.cache_read_tokens,r.input_tokens)}</td>
      <td class="td-muted" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(task)}">${escHtml(taskD)}</td>
      <td style="padding:9px 12px;font-size:11px">${statusHtml}</td>
    </tr>`;
  }).join("");

  const cnt = document.getElementById("runs-count");
  if (cnt) cnt.textContent = `(${start+1}–${Math.min(start+_runsPageSize,total)} de ${total})`;

  const pg = document.getElementById("runs-pagination");
  if (pg) pg.innerHTML = _buildPagination(
    _runsPage, totalPages, _runsPageSize,
    `_runsPage=${_runsPage-1};renderRunsTable()`,
    `_runsPage=${_runsPage+1};renderRunsTable()`,
    `_runsPageSize=10;_runsPage=0;renderRunsTable()`,
    `_runsPageSize=25;_runsPage=0;renderRunsTable()`,
    `_runsPageSize=50;_runsPage=0;renderRunsTable()`,
    `_runsPageSize=100;_runsPage=0;renderRunsTable()`
  );
}

function applyRunFilters() {
  _runsFilterProject = (document.getElementById("filterProject")||{}).value||"";
  _runsFilterModel   = (document.getElementById("filterModel")||{}).value||"";
  _runsPage = 0;
  renderRunsTable();
}

function _buildPagination(page, totalPages, pageSize, cbPrev, cbNext, cbSize10, cbSize25, cbSize50, cbSize100) {
  const sizes = [[10,cbSize10],[25,cbSize25],[50,cbSize50],[100,cbSize100]];
  const btns = sizes.map(([n,cb]) =>
    `<button class="pg-btn${n===pageSize?' pg-btn-active':''}" onclick="${cb}">${n}</button>`
  ).join("");
  return `<div class="pagination-bar">
    <button class="pg-btn" onclick="${cbPrev}" ${page<=0?'disabled':''}>← Ant.</button>
    <span style="font-size:12px;color:var(--text-muted);padding:0 4px">Pág. ${page+1} / ${totalPages}</span>
    <button class="pg-btn" onclick="${cbNext}" ${page>=totalPages-1?'disabled':''}>Sig. →</button>
    <span style="font-size:11px;color:var(--text-faint);margin-left:6px">Filas:</span>
    ${btns}
  </div>`;
}

// ── Inspector pagination ──────────────────────────────────────────────────────
const _inspPages = {};
const _inspSizes = {};

function mkTablePaged(id, title, rows, cols) {
  if (!_inspPages[id]) _inspPages[id] = 0;
  if (!_inspSizes[id]) _inspSizes[id] = 10;
  const n = (rows||[]).length;
  if (!n) return `<div class="panel" style="margin-bottom:16px"><h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">(0)</span></h2><p class="text-faint" style="font-size:13px">Sin registros.</p></div>`;
  const ps = _inspSizes[id];
  const tp = Math.max(1,Math.ceil(n/ps));
  if (_inspPages[id]>=tp) _inspPages[id]=tp-1;
  const pg = _inspPages[id];
  const slice = rows.slice(pg*ps, pg*ps+ps);
  const ths = cols.map(c=>`<th style="text-align:left;padding:7px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px">${c.label}</th>`).join("");
  const trs = slice.map(r=>`<tr style="border-bottom:1px solid var(--border-faint)">${
    cols.map(c=>{
      const val=r[c.key]??"—";
      const sval=c.fmt?c.fmt(val):String(val);
      const display=c.max&&sval.length>c.max?sval.slice(0,c.max)+"…":sval;
      return `<td style="padding:7px 10px;font-size:12px;color:${c.color||"var(--text-secondary)"};${c.mono?"font-family:'JetBrains Mono',monospace":""}">${escHtml(display)}</td>`;
    }).join("")
  }</tr>`).join("");
  const pgHtml = _buildPagination(pg, tp, ps,
    `_inspPages['${id}']=${pg-1};reloadInspector()`,
    `_inspPages['${id}']=${pg+1};reloadInspector()`,
    `_inspSizes['${id}']=10;_inspPages['${id}']=0;reloadInspector()`,
    `_inspSizes['${id}']=25;_inspPages['${id}']=0;reloadInspector()`,
    `_inspSizes['${id}']=50;_inspPages['${id}']=0;reloadInspector()`,
    `_inspSizes['${id}']=100;_inspPages['${id}']=0;reloadInspector()`
  );
  return `<div class="panel" style="margin-bottom:16px;overflow-x:auto">
    <h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">${n} filas</span></h2>
    <table><thead><tr style="background:var(--bg-elevated);border-bottom:1px solid var(--border)">${ths}</tr></thead><tbody>${trs}</tbody></table>
    ${pgHtml}
  </div>`;
}

// ── Context actions ───────────────────────────────────────────────────────────
let _ctxStatusFilter = "all";

function setCtxFilter(status) {
  _ctxStatusFilter = status || "all";
  document.querySelectorAll(".ctx-filter-btn").forEach(b => b.classList.remove("pg-btn-active"));
  const btn = document.getElementById("ctx-filter-" + _ctxStatusFilter);
  if (btn) btn.classList.add("pg-btn-active");
  _refreshContexts();
}

function advanceStep(stepId, ctxId) {
  fetch("/advance-step",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_id:stepId})})
    .then(r=>r.json())
    .then(d=>{
      if (d.error){showToast("Error: "+d.error,true);return;}
      showToast(d.context_done?"Contexto completado":"Paso avanzado");
      _refreshContexts();
    }).catch(()=>showToast("Error de conexión",true));
}

function skipStep(stepId, ctxId) {
  fetch("/skip-step",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_id:stepId,reason:"omitido desde dashboard"})})
    .then(r=>r.json())
    .then(d=>{
      if (d.error){showToast("Error: "+d.error,true);return;}
      showToast("Paso omitido");
      _refreshContexts();
    }).catch(()=>showToast("Error de conexión",true));
}

function _refreshContexts() {
  const params = [];
  if (_runsFilterProject) params.push("project="+encodeURIComponent(_runsFilterProject));
  params.push("status="+encodeURIComponent(_ctxStatusFilter||"all"));
  fetch("/contexts-html?"+params.join("&"))
    .then(r=>r.text())
    .then(html=>{
      const el=document.getElementById("contextsSection");
      if(el){const tmp=document.createElement("div");tmp.innerHTML=html;el.replaceWith(tmp.firstChild||el);}
    }).catch(()=>{});
}

// ── Context detail overlay ───────────────────────────────────────────────────
function openContextDetail(ctxId) {
  const overlay = document.getElementById("ctxDetailOverlay");
  const content = document.getElementById("ctxDetailContent");
  overlay.classList.add("open");
  content.innerHTML='<p class="text-muted" style="font-size:13px"><span class="spinner"></span> Cargando...</p>';
  fetch("/context/"+ctxId)
    .then(r=>r.json())
    .then(data=>{
      const STEP_CLR={pending:"#71717a",in_progress:"#38bdf8",completed:"#22c55e",blocked:"#f87171",skipped:"#52525b"};
      const stepsHtml=(data.steps||[]).map(s=>{
        const sc=STEP_CLR[s.status]||"#71717a";
        const aligns=(s.alignments||[]).map(a=>`<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border-faint);display:flex;gap:8px">
          <span style="color:var(--text-faint);white-space:nowrap">${a.ts?new Date(a.ts).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"—"}</span>
          <span style="color:${a.confirmed?"#22c55e":"#f87171"};font-weight:700">${a.confirmed?"✓":"✗"}</span>
          <span style="color:var(--text-secondary)">${escHtml(a.checkpoint||"")}</span>
          <span style="color:var(--text-faint)">${escHtml(a.agent||"")}</span>
        </div>`).join("") || '<span style="font-size:11px;color:var(--text-faint)">Sin alineamientos.</span>';
        const tools=(s.tool_calls||[]).map(tc=>`<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border-faint);display:flex;gap:8px">
          <span style="color:var(--text-faint);white-space:nowrap">${tc.ts?new Date(tc.ts).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"—"}</span>
          <span style="font-family:'JetBrains Mono',monospace;color:var(--text-primary)">${escHtml(tc.tool_name||"")}</span>
          <span style="color:${tc.status==="ok"?"#22c55e":"#f87171"}">${escHtml(tc.status||"")}</span>
          <span style="color:var(--text-faint)">${tc.duration_ms!=null?tc.duration_ms+"ms":""}</span>
        </div>`).join("") || '<span style="font-size:11px;color:var(--text-faint)">Sin tool calls.</span>';
        return `<div style="margin-bottom:14px;padding:10px;background:var(--bg-elevated);border-radius:10px;border-left:3px solid ${sc}">
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
            <span style="font-size:11px;font-weight:700;color:var(--text-faint);font-family:'JetBrains Mono',monospace">${s.order_idx||"?"}</span>
            <span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1">${escHtml(s.title||"")}</span>
            <span style="font-size:10px;background:rgba(0,0,0,.2);color:${sc};padding:2px 8px;border-radius:20px;font-weight:600">${escHtml(s.status||"")}</span>
          </div>
          <div style="margin-bottom:6px"><span style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px">Alineamientos</span><div style="margin-top:4px">${aligns}</div></div>
          <div><span style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px">Tool Calls</span><div style="margin-top:4px">${tools}</div></div>
        </div>`;
      }).join("") || '<p class="text-muted" style="font-size:13px">Sin pasos.</p>';
      const CTX_CLR={active:"#22c55e",programado:"#818cf8",completed:"#71717a",abandoned:"#f87171"};
      const cs=CTX_CLR[data.status||"active"]||"#71717a";
      content.innerHTML=`
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
          <span class="chip-mono">#${data.id}</span>
          <span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1">${escHtml(data.title||"")}</span>
          <span style="font-size:10px;background:rgba(0,0,0,.2);color:${cs};padding:2px 8px;border-radius:20px;font-weight:600">${escHtml(data.status||"")}</span>
        </div>
        ${data.description?`<p style="font-size:12px;color:var(--text-muted);margin-bottom:14px">${escHtml(data.description)}</p>`:""}
        <div class="detail-section"><label>Pasos</label>${stepsHtml}</div>
      `;
    }).catch(()=>{content.innerHTML='<p style="color:#ef4444;font-size:13px">Error al cargar.</p>';});
}

function closeCtxDetail(e) {
  if (e && e.target !== document.getElementById("ctxDetailOverlay")) return;
  document.getElementById("ctxDetailOverlay").classList.remove("open");
}

// ── Export CSV ────────────────────────────────────────────────────────────────
function exportCSV() {
  const proj = (document.getElementById("filterProject")||{}).value||"";
  const mdl  = (document.getElementById("filterModel")||{}).value||"";
  let url = "/export-csv";
  const params = [];
  if (proj) params.push("project="+encodeURIComponent(proj));
  if (mdl)  params.push("model="+encodeURIComponent(mdl));
  if (params.length) url += "?"+params.join("&");
  window.location.href = url;
}

const evtSource = new EventSource("/events");
evtSource.addEventListener("ctx_updated", e => {
  const d = JSON.parse(e.data);
  _refreshContexts();
});

evtSource.addEventListener("run_started", e => {
  const d = JSON.parse(e.data);
  prependPendingRow(d);
});
evtSource.addEventListener("run_done", e => {
  const d = JSON.parse(e.data);
  updateRow(d);
  showToast("Run #" + d.run_id + " completado — " + (d.provider || "?") + " " + (d.cost_usd ? "$" + d.cost_usd.toFixed(4) : ""));
});
evtSource.addEventListener("run_failed", e => {
  const d = JSON.parse(e.data);
  markFailed(d);
  showToast("Run #" + d.run_id + " falló: " + d.error, true);
});
evtSource.addEventListener("budget_warning", e => {
  const d = JSON.parse(e.data);
  updateBudgetGauge(d);
});

function prependPendingRow(d) {
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
    <td class="td-ts">ahora</td>
    <td class="td-project">${escHtml(d.project)}</td>
    <td style="padding:9px 12px"><span class="badge badge-pending">… pending</span></td>
    <td colspan="7" class="td-muted"><span class="spinner"></span> esperando respuesta...</td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);
}

function updateRow(d) {
  const tr = document.querySelector(`tr[data-run-id="${d.run_id}"]`);
  if (!tr) return;
  tr.cells[2].innerHTML = '<span class="badge" style="background:rgba(34,197,94,0.12);color:#22c55e">done</span>';
  if (tr.cells[3]) {
    tr.cells[3].colSpan = 1;
    tr.cells[3].textContent = d.model ? d.model.split("/").pop() : "?";
    for (let i = 4; i < 10; i++) {
      if (!tr.cells[i]) {
        const td = tr.insertCell(i);
        td.style.padding = "8px 10px";
        td.style.fontSize = "12px";
        td.style.textAlign = i < 7 ? "right" : "left";
      }
    }
    tr.cells[4].textContent = d.duration_ms ? (d.duration_ms >= 1000 ? (d.duration_ms/1000).toFixed(1)+"s" : d.duration_ms+"ms") : "—";
    tr.cells[6].textContent = d.cost_usd ? "$" + parseFloat(d.cost_usd).toFixed(4) : "—";
  }
}

function markFailed(d) {
  const tr = document.querySelector(`tr[data-run-id="${d.run_id}"]`);
  if (!tr) return;
  tr.cells[2].innerHTML = '<span class="badge badge-failed">✗ failed</span>';
  if (tr.cells[3]) tr.cells[3].textContent = d.error || "error";
}

function updateBudgetGauge(d) {
  const sec = document.getElementById("budgetSection");
  const pct = Math.min(d.pct * 100, 100).toFixed(0);
  const color = d.pct >= 1.0 ? "#ef4444" : d.pct >= 0.8 ? "#f59e0b" : "#22c55e";
  sec.innerHTML = `<div class="panel" style="margin-bottom:20px">
    <h2>Presupuesto diario — ${escHtml(d.project)}</h2>
    <div class="budget-meta">
      <span>Gastado: <strong class="text-primary">$${parseFloat(d.spent_usd).toFixed(4)}</strong></span>
      <span>Límite: <strong class="text-primary">$${parseFloat(d.limit_usd).toFixed(2)}</strong></span>
      <span style="color:${color};font-weight:700">${pct}%</span>
    </div>
    <div class="budget-bar"><div class="budget-fill" style="width:${pct}%;background:${color}"></div></div>
  </div>`;
}

function openDetail(runId) {
  if (!runId) return;
  const overlay = document.getElementById("detailOverlay");
  const content = document.getElementById("detailContent");
  overlay.classList.add("open");
  content.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span> Cargando...</p>';
  fetch("/run/" + runId)
    .then(r => r.json())
    .then(data => {
      const provColor = {"claude":"#fb923c","deepseek":"#22c55e","openai":"#818cf8"}[data.provider] || "var(--text-muted)";
      const provBg = {"claude":"rgba(251,146,60,0.12)","deepseek":"rgba(34,197,94,0.12)","openai":"rgba(129,140,248,0.12)"}[data.provider] || "rgba(113,113,122,0.12)";
      content.innerHTML = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
          <span class="chip-mono">#${data.id}</span>
          <span style="background:${provBg};color:${provColor};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600">${escHtml(data.provider)}</span>
          <span class="chip-mono">${escHtml(data.model ? data.model.split('/').pop() : '—')}</span>
          <span class="chip">${data.duration_ms ? (data.duration_ms/1000).toFixed(1)+"s" : "—"}</span>
          ${data.cost_usd ? `<span style="background:rgba(34,197,94,0.10);color:#22c55e;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600">$${parseFloat(data.cost_usd).toFixed(4)}</span>` : ''}
        </div>
        <div class="detail-section">
          <label>Tarea enviada</label>
          <pre>${escHtml(data.task || data.task_preview || "(sin texto)")}</pre>
        </div>
        <div class="detail-section">
          <label>Respuesta del modelo</label>
          <pre>${escHtml(data.response || "(sin respuesta aún)")}</pre>
        </div>
        <div class="detail-section">
          <label>Razón de ruteo</label>
          <p class="detail-text">${escHtml(data.routing_reason || "—")}</p>
        </div>
        ${data.cache_read_tokens ? `<div class="detail-section">
          <label>Cache Claude</label>
          <p class="detail-text">
            Leídos: <strong style="color:#38bdf8">${data.cache_read_tokens}</strong> tokens
            ${data.cache_creation_tokens ? ` · Escritos: <strong style="color:#22c55e">${data.cache_creation_tokens}</strong>` : ''}
          </p>
        </div>` : ''}
        ${data.alignments && data.alignments.length ? `<div class="detail-section">
          <label>Checkpoints de alineación</label>
          <table style="width:100%;font-size:12px;border-collapse:collapse">
            <thead><tr class="detail-thead-row">
              <th class="td-sm">Hora</th>
              <th class="td-sm">Checkpoint</th>
              <th class="td-sm">Agente</th>
              <th class="td-sm" style="text-align:center">OK</th>
              <th class="td-sm">Mensaje</th>
            </tr></thead>
            <tbody>
              ${data.alignments.map(a => `<tr class="detail-tbody-row">
                <td class="td-sm-ts">${a.ts ? new Date(a.ts).toLocaleString("es",{hour12:false,day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : '—'}</td>
                <td class="td-sm-text">${escHtml(a.checkpoint || '—')}</td>
                <td class="td-sm-muted">${escHtml(a.agent || '—')}</td>
                <td class="td-sm" style="text-align:center">${a.confirmed ? '<span style="color:#22c55e;font-weight:700;font-size:14px">✓</span>' : '<span style="color:#f87171;font-weight:700;font-size:14px">✗</span>'}</td>
                <td class="td-sm-muted">${escHtml(a.message || '')}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>` : ''}
        ${data.tool_calls && data.tool_calls.length ? `<div class="detail-section">
          <label>Herramientas invocadas</label>
          <table style="width:100%;font-size:12px;border-collapse:collapse">
            <thead><tr class="detail-thead-row">
              <th class="td-sm">Hora</th>
              <th class="td-sm">Herramienta</th>
              <th class="td-sm" style="text-align:center">Estado</th>
              <th class="td-sm" style="text-align:right">ms</th>
              <th class="td-sm">Salida</th>
            </tr></thead>
            <tbody>
              ${data.tool_calls.map(tc => `<tr class="detail-tbody-row">
                <td class="td-sm-ts">${tc.ts ? new Date(tc.ts).toLocaleString("es",{hour12:false,day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : '—'}</td>
                <td class="td-sm-mono">${escHtml(tc.tool_name || '—')}</td>
                <td class="td-sm" style="text-align:center"><span style="font-size:10px;padding:2px 7px;border-radius:20px;background:${tc.status==='ok'?'rgba(34,197,94,0.12)':'rgba(248,113,113,0.12)'};color:${tc.status==='ok'?'#22c55e':'#f87171'};font-weight:600">${escHtml(tc.status || '—')}</span></td>
                <td class="td-sm text-muted" style="text-align:right;font-variant-numeric:tabular-nums">${tc.duration_ms != null ? tc.duration_ms : '—'}</td>
                <td class="td-sm-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(tc.output ? String(tc.output).slice(0,80) : '')}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>` : ''}
      `;
    })
    .catch(() => { content.innerHTML = '<p style="color:#ef4444;font-size:13px">Error al cargar detalle.</p>'; });
}

function closeDetail(e) {
  if (e && e.target !== document.getElementById("detailOverlay")) return;
  document.getElementById("detailOverlay").classList.remove("open");
}

function toggleSender() {
  document.getElementById("senderPanel").classList.toggle("open");
}

function toggleContextForm() {
  switchTab("contextos");
}

let _ctxStepCount = 0;
function addCtxStep() {
  _ctxStepCount++;
  const container = document.getElementById("ctxSteps");
  const row = document.createElement("div");
  row.style.cssText = "display:flex;gap:8px;margin-bottom:8px;align-items:center";
  row.innerHTML = `
    <input type="text" placeholder="Título del paso..." style="flex:1" class="ctx-step-title">
    <select class="ctx-step-provider">
      <option value="">auto</option>
      <option value="claude">claude</option>
      <option value="deepseek">deepseek</option>
      <option value="openai">openai</option>
    </select>
    <button onclick="this.parentElement.remove()" class="close-btn" title="Quitar paso">✕</button>
  `;
  container.appendChild(row);
}

function submitContext() {
  const project = document.getElementById("ctxProject").value;
  const title   = document.getElementById("ctxTitle").value.trim();
  const desc    = document.getElementById("ctxDesc").value.trim();
  const status  = document.getElementById("ctxStatus");
  if (!project) { status.textContent = "Seleccioná un proyecto."; return; }
  if (!title)   { status.textContent = "El título no puede estar vacío."; return; }
  const steps = Array.from(document.querySelectorAll("#ctxSteps > div")).map(row => ({
    title:    row.querySelector(".ctx-step-title").value.trim(),
    provider: row.querySelector(".ctx-step-provider").value,
  })).filter(s => s.title);
  status.innerHTML = '<span class="spinner"></span> Creando...';
  fetch("/create-context", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project, title, description: desc, steps}),
  })
  .then(r => r.json())
  .then(d => {
    if (d.error) { status.textContent = "Error: " + d.error; return; }
    status.textContent = "Contexto #" + d.context_id + " creado con " + (d.steps || []).length + " paso(s).";
    document.getElementById("ctxTitle").value = "";
    document.getElementById("ctxDesc").value = "";
    document.getElementById("ctxSteps").innerHTML = "";
    _ctxStepCount = 0;
    showToast("Contexto '" + d.title + "' creado para " + d.project);
  })
  .catch(() => { status.textContent = "Error al crear."; });
}

function submitTask() {
  const project = document.getElementById("senderProject").value;
  const task    = document.getElementById("senderTask").value.trim();
  const model   = document.getElementById("senderModel").value;
  const status  = document.getElementById("senderStatus");
  if (!project) { status.textContent = "Seleccioná un proyecto."; return; }
  if (!task)    { status.textContent = "La tarea no puede estar vacía."; return; }
  status.innerHTML = '<span class="spinner"></span> Enviando...';
  fetch("/run", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project, task, model: model || undefined}),
  })
  .then(r => r.json())
  .then(d => {
    status.textContent = "Run #" + d.run_id + " enviado.";
    document.getElementById("senderTask").value = "";
  })
  .catch(() => { status.textContent = "Error al enviar."; });
}

function showToast(msg, isError) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.background = isError ? "#ef4444" : "";
  t.style.display = "block";
  setTimeout(() => { t.style.display = "none"; }, 4000);
}

// ── Theme selector ────────────────────────────────────────────────────────────
function setTheme(name) {
  if (!name || name === "dark") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", name);
  }
  localStorage.setItem("theme", name || "dark");
  const sel = document.getElementById("themeSelect");
  if (sel) sel.value = name || "dark";
}

(function() {
  const saved = localStorage.getItem("theme") || "dark";
  const sel = document.getElementById("themeSelect");
  if (sel) sel.value = saved;
})();

function escHtml(s) {
  if (s == null) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── Activity bar ─────────────────────────────────────────────────────────────
let _actOpen = false;
const _traceMap = {};

evtSource.addEventListener("trace", e => _handleTrace(JSON.parse(e.data)));

function toggleActivity() {
  _actOpen = !_actOpen;
  document.getElementById("activity-log").style.display = _actOpen ? "block" : "none";
  document.getElementById("act-toggle").textContent  = _actOpen ? "▲" : "▼";
}

function _traceKey(d) {
  return ("tr_" + d.name + (d.run_id != null ? "_" + d.run_id : "")).replace(/[^a-z0-9_]/gi, "_");
}

function _fmtTs(iso) {
  try { return new Date(iso).toLocaleTimeString("es", {hour12:false, fractionalSecondDigits:2}); }
  catch { return iso.slice(11, 22); }
}

function _handleTrace(d) {
  const key  = _traceKey(d);
  const log  = document.getElementById("activity-log");
  const dot  = document.getElementById("act-dot");
  const runLabel = d.run_id != null ? "#" + d.run_id : "";
  const detLabel = d.detail ? " · " + escHtml(d.detail) : "";

  if (d.status === "running") {
    const row = document.createElement("div");
    row.id = key;
    row.className = "tr-row tr-running";
    row.innerHTML =
      `<span class="tr-ts">${_fmtTs(d.ts)}</span>` +
      `<span class="tr-run">${escHtml(runLabel)}</span>` +
      `<span class="tr-icon">▶</span>` +
      `<span class="tr-name">${escHtml(d.name)}${detLabel}</span>` +
      `<span class="tr-dur"></span>`;
    _traceMap[key] = row;
    log.insertBefore(row, log.firstChild);
    while (log.children.length > 80) log.removeChild(log.lastChild);
    if (!_actOpen) { _actOpen = true; log.style.display = "block"; document.getElementById("act-toggle").textContent = "▲"; }
  } else {
    const icon = d.status === "done" ? "✓" : "✗";
    const dur  = d.duration_ms != null ? d.duration_ms + "ms" : "";
    const cls  = "tr-row tr-" + d.status;
    const existing = _traceMap[key] || document.getElementById(key);
    if (existing) {
      existing.className = cls;
      existing.querySelector(".tr-icon").textContent = icon;
      existing.querySelector(".tr-dur").textContent  = dur;
      delete _traceMap[key];
    }
  }

  const icon2 = d.status === "done" ? "✓" : d.status === "error" ? "✗" : "▶";
  const dur2  = d.duration_ms ? " " + d.duration_ms + "ms" : "";
  document.getElementById("act-summary").textContent = icon2 + " " + d.name + (runLabel ? " " + runLabel : "") + dur2;
  dot.classList.add("live");
  dot.classList.remove("pulse");
  void dot.offsetWidth;
  dot.classList.add("pulse");
}

let _inspectorLoaded = false;
function switchTab(name) {
  document.getElementById("tab-main").style.display      = name === "main"      ? "" : "none";
  document.getElementById("tab-contextos").style.display = name === "contextos" ? "" : "none";
  document.getElementById("tab-inspector").style.display = name === "inspector" ? "" : "none";
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("tab-active"));
  document.getElementById("tab-btn-" + name).classList.add("tab-active");
  if (name === "inspector" && !_inspectorLoaded) {
    _inspectorLoaded = true;
    loadInspector();
  }
  if (name === "contextos") _refreshContexts();
}

function loadInspector() {
  const el = document.getElementById("inspector-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Cargando...</p>';
  fetch("/inspect")
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        el.innerHTML = `<p style="color:#f87171;font-size:13px">Error del servidor: ${escHtml(data.error)}</p>`;
        return;
      }
      renderInspector(data);
    })
    .catch(err => {
      el.innerHTML = `<p style="color:#f87171;font-size:13px">Error de conexión: ${escHtml(String(err))}</p>`;
    });
}

function reloadInspector() {
  const el = document.getElementById("inspector-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Actualizando...</p>';
  fetch("/inspect")
    .then(r => r.json())
    .then(renderInspector)
    .catch(() => { el.innerHTML = '<p style="color:#f87171;font-size:13px">Error al recargar.</p>'; });
}

function pickFolder(alias) {
  const btn    = document.getElementById("reg-pick-" + alias);
  const input  = document.getElementById("reg-path-" + alias);
  const status = document.getElementById("reg-status-" + alias);
  const orig   = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  fetch("/pick-folder")
    .then(r => r.json())
    .then(d => {
      if (d.path) {
        input.value = d.path;
        status.textContent = "";
        input.focus();
      } else {
        status.textContent = d.error ? "✗ " + d.error : "Cancelado.";
        status.style.color = "var(--text-muted)";
      }
    })
    .catch(() => { status.textContent = "✗ Sin respuesta."; status.style.color = "#f87171"; })
    .finally(() => { btn.disabled = false; btn.innerHTML = orig; });
}

function registerProject(alias) {
  const input  = document.getElementById("reg-path-" + alias);
  const status = document.getElementById("reg-status-" + alias);
  const path = input ? input.value.trim() : "";
  if (!path) { status.textContent = "Ingresá la ruta."; status.style.color = "#f87171"; return; }
  status.innerHTML = '<span class="spinner"></span>';
  fetch("/add-project", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({alias, path}),
  })
  .then(r => r.json())
  .then(d => {
    if (d.error) { status.textContent = "✗ " + d.error; status.style.color = "#f87171"; }
    else {
      status.textContent = "✓ registrado";
      status.style.color = "#22c55e";
      const row = document.getElementById("reg-row-" + alias);
      if (row) row.style.opacity = "0.4";
      setTimeout(reloadInspector, 900);
    }
  })
  .catch(() => { status.textContent = "✗ Error de conexión."; status.style.color = "#f87171"; });
}

function indexDocs() {
  const sel = document.getElementById("insp-project-sel");
  const status = document.getElementById("insp-action-status");
  const proj = sel ? sel.value : "";
  if (!proj) { status.textContent = "Seleccioná un proyecto."; return; }
  status.innerHTML = '<span class="spinner"></span>&nbsp;Indexando...';
  document.getElementById("insp-index-btn").disabled = true;
  fetch("/index-docs", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project: proj}),
  })
  .then(r => r.json())
  .then(d => {
    if (d.error) { status.textContent = "Error: " + d.error; }
    else { status.textContent = "✓ " + d.chunks + " chunks indexados para '" + d.project + "'."; }
    document.getElementById("insp-index-btn").disabled = false;
    reloadInspector();
  })
  .catch(() => {
    status.textContent = "Error de conexión.";
    document.getElementById("insp-index-btn").disabled = false;
  });
}

function fmtTs(iso) {
  try {
    return new Date(iso).toLocaleString("es", {
      day:"2-digit", month:"2-digit", year:"2-digit",
      hour:"2-digit", minute:"2-digit", hour12:false,
    });
  } catch { return iso ? iso.slice(0,16) : "—"; }
}

function renderInspector(data) {
  const el = document.getElementById("inspector-content");
  const chroma = data.chroma || {};
  const COLS = ["runs","docs","responses"];
  const colLabels = {runs:"Routing memory",docs:"Docs (RAG)",responses:"Respuestas"};
  const registered = new Set(data.registered_projects || []);
  const allProjects = data.all_projects || [];
  const projOpts = allProjects.map(p => {
    const indexable = registered.has(p);
    const label = indexable ? p : p + " (sin ruta)";
    return `<option value="${escHtml(p)}" ${indexable ? "" : 'style="color:var(--text-muted)"'}>${escHtml(label)}</option>`;
  }).join("");
  let html = `<div class="panel" style="margin-bottom:16px">
    <h2>Acciones</h2>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <select id="insp-project-sel" style="min-width:160px">
        <option value="">— proyecto —</option>${projOpts}
      </select>
      <button id="insp-index-btn" class="btn btn-primary" onclick="indexDocs()">Indexar docs</button>
      <span id="insp-action-status" class="text-muted" style="font-size:12px"></span>
      <button class="btn btn-secondary" onclick="reloadInspector()" style="margin-left:auto">↻ Recargar</button>
    </div>
  </div>
  <div class="panel" style="margin-bottom:20px">
    <h2>ChromaDB — Colecciones vectoriales</h2>
    <div class="insp-grid">`;
  COLS.forEach(col => {
    const c = chroma[col] || {};
    const bp = c.by_project || {};
    const bpRows = Object.entries(bp).map(([p,n]) =>
      `<div class="col-proj-row"><span class="text-faint">${escHtml(p)}</span><span style="color:#22c55e;font-weight:600">${n}</span></div>`
    ).join("");
    html += `<div class="insp-stat">
      <div class="col-name">${colLabels[col] || col}</div>
      <div class="col-count">${c.count ?? "—"}</div>
      <div class="col-sub">documentos indexados</div>
      ${bpRows ? '<div class="col-projects">' + bpRows + '</div>' : ""}
    </div>`;
  });
  html += `</div></div></div>`;

  const unregistered = allProjects.filter(p => !registered.has(p));
  if (unregistered.length > 0) {
    const regRows = unregistered.map(p => `
      <div style="display:flex;gap:8px;align-items:center;padding:10px 0;border-bottom:1px solid var(--border-faint)" id="reg-row-${escHtml(p)}">
        <span style="font-size:12px;color:var(--text-primary);min-width:140px;font-family:'JetBrains Mono',monospace;flex-shrink:0">${escHtml(p)}</span>
        <input type="text" id="reg-path-${escHtml(p)}" placeholder="Ruta al directorio del proyecto" style="flex:1;min-width:0">
        <button id="reg-pick-${escHtml(p)}" class="btn btn-secondary" title="Seleccionar carpeta…" style="padding:0 10px;font-size:15px;flex-shrink:0" onclick="pickFolder('${escHtml(p)}')">&#128193;</button>
        <button class="btn btn-secondary" style="white-space:nowrap;flex-shrink:0" onclick="registerProject('${escHtml(p)}')">Registrar</button>
        <span id="reg-status-${escHtml(p)}" style="font-size:12px;min-width:80px;flex-shrink:0"></span>
      </div>`).join("");
    html += `<div class="panel" style="margin-bottom:16px">
      <h2>Proyectos sin ruta registrada</h2>
      <p class="text-muted" style="font-size:12px;margin-bottom:10px">Ingresá la ruta local para habilitarlos en el router y en el indexador RAG.</p>
      ${regRows}
    </div>`;
  }

  function mkTable(title, rows, cols) {
    const n = (rows||[]).length;
    if (!n) return `<div class="panel" style="margin-bottom:16px"><h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">(0)</span></h2><p class="text-faint" style="font-size:13px">Sin registros.</p></div>`;
    const ths = cols.map(c => `<th style="text-align:left;padding:7px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px">${c.label}</th>`).join("");
    const trs = rows.map(r => `<tr style="border-bottom:1px solid var(--border-faint)">${
      cols.map(c => {
        const val = r[c.key] ?? "—";
        const sval = c.fmt ? c.fmt(val) : String(val);
        const display = c.max && sval.length > c.max ? sval.slice(0, c.max) + "…" : sval;
        return `<td style="padding:7px 10px;font-size:12px;color:${c.color||"var(--text-secondary)"};${c.mono?"font-family:'JetBrains Mono',monospace":""}">
          ${escHtml(display)}
        </td>`;
      }).join("")
    }</tr>`).join("");
    return `<div class="panel" style="margin-bottom:16px;overflow-x:auto">
      <h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">${n} filas</span></h2>
      <table><thead><tr style="background:var(--bg-elevated);border-bottom:1px solid var(--border)">${ths}</tr></thead><tbody>${trs}</tbody></table>
    </div>`;
  }

  html += mkTablePaged("chunks","Chunks indexados (RAG)", data.chunks, [
    {label:"Proyecto",    key:"project",    color:"var(--text-primary)"},
    {label:"Archivo",     key:"source_path",color:"var(--text-secondary)",mono:true,max:60},
    {label:"Chunks",      key:"chunk_count",color:"#22c55e"},
    {label:"Colección",   key:"collection", color:"var(--text-muted)"},
    {label:"Indexado",    key:"ts",         color:"var(--text-faint)",mono:true,fmt:fmtTs},
  ]);

  html += mkTablePaged("contexts","Contextos", data.contexts, [
    {label:"ID",      key:"id",          color:"var(--text-faint)",mono:true},
    {label:"Proyecto",key:"project",     color:"var(--text-primary)"},
    {label:"Título",  key:"title",       color:"var(--text-detail)",max:50},
    {label:"Estado",  key:"status",      color:"#22c55e"},
    {label:"Creado",  key:"ts",          color:"var(--text-faint)",mono:true,fmt:fmtTs},
  ]);

  html += mkTablePaged("steps","Pasos", data.steps, [
    {label:"ID",       key:"id",            color:"var(--text-faint)",mono:true},
    {label:"Proyecto", key:"project",       color:"var(--text-primary)"},
    {label:"Contexto", key:"context_title", color:"var(--text-secondary)",max:30},
    {label:"#",        key:"order_idx",     color:"var(--text-muted)",mono:true},
    {label:"Título",   key:"title",         color:"var(--text-detail)",max:40},
    {label:"Estado",   key:"status",        color:"#38bdf8"},
    {label:"Provider", key:"provider",      color:"var(--text-muted)"},
  ]);

  html += mkTablePaged("alignments","Alineamientos", data.alignments, [
    {label:"ID",         key:"id",         color:"var(--text-faint)",mono:true},
    {label:"Hora",       key:"ts",         color:"var(--text-faint)",mono:true,fmt:fmtTs},
    {label:"Paso",       key:"step_title", color:"var(--text-secondary)",max:35},
    {label:"Agente",     key:"agent",      color:"var(--text-detail)"},
    {label:"OK",         key:"confirmed",  color:"#22c55e"},
    {label:"Checkpoint", key:"checkpoint", color:"var(--text-muted)",max:50},
  ]);

  html += mkTablePaged("tool_calls","Tool Calls", data.tool_calls, [
    {label:"ID",          key:"id",          color:"var(--text-faint)",mono:true},
    {label:"Hora",        key:"ts",          color:"var(--text-faint)",mono:true,fmt:fmtTs},
    {label:"Paso",        key:"step_title",  color:"var(--text-secondary)",max:35},
    {label:"Herramienta", key:"tool_name",   color:"var(--text-primary)",mono:true},
    {label:"Estado",      key:"status",      color:"#22c55e"},
    {label:"ms",          key:"duration_ms", color:"var(--text-muted)"},
  ]);

  el.innerHTML = html;
}
"""

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
    cache_pct = round(total_cache_read / total_input_tok * 100) if total_input_tok else 0

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
    runs_json = _json.dumps(
        [{"id": r.get("id"), "ts": _text(r.get("ts")), "project": _text(r.get("project")),
          "provider": _text(r.get("provider")), "model": _text(r.get("model")),
          "status": _text(r.get("status","done")), "duration_ms": r.get("duration_ms"),
          "input_tokens": r.get("input_tokens"), "output_tokens": r.get("output_tokens"),
          "cost_usd": r.get("cost_usd"), "cache_read_tokens": r.get("cache_read_tokens"),
          "task_preview": _text(r.get("task_preview") or r.get("task","")),
          "routing_reason": _text(r.get("routing_reason",""))}
         for r in runs],
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

    tokens_display = f"{total_tokens // 1000}K" if total_tokens >= 1000 else str(total_tokens)
    cost_display = f"${total_cost:.4f}" if total_cost > 0 else "—"
    cache_display = f"{cache_pct}%" if cache_pct else "—"
    now_dt = datetime.now().astimezone()
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
    <button class="btn btn-secondary" onclick="toggleContextForm()">+ Nuevo contexto</button>
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
    <button class="tab-btn tab-active" id="tab-btn-main" onclick="switchTab('main')">Dashboard</button>
    <button class="tab-btn" id="tab-btn-contextos" onclick="switchTab('contextos')">Contextos</button>
    <button class="tab-btn" id="tab-btn-inspector" onclick="switchTab('inspector')">Inspector</button>
  </div>
</div>

<div id="tab-main">
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
    <table id="runs-table" style="display:none"><thead><tr><th>Fecha</th><th>Proyecto</th><th>Proveedor</th><th>Modelo</th><th style="text-align:right">Dur.</th><th style="text-align:right">Tokens</th><th style="text-align:right">Costo</th><th style="text-align:center">Cache</th><th>Tarea</th><th>Estado</th></tr></thead><tbody id="runs-body"></tbody></table>
    <p class="empty" id="empty-msg" style="display:none">No hay runs aún. Usá el botón <strong>+ Nueva tarea</strong> para enviar una.</p>
    <div id="runs-pagination"></div>
  </div>

</div>
</div>

<div id="tab-contextos" style="display:none">
<div class="container">

  <div class="panel" style="margin-bottom:16px">
    <h2>Nuevo contexto</h2>
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
        <button class="btn btn-primary" onclick="submitContext()">Crear contexto</button>
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

<div id="tab-inspector" style="display:none">
<div class="container">
  <div id="inspector-content" style="padding-top:4px">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
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
    <h3>Detalle del contexto</h3>
    <div id="ctxDetailContent"><p class="text-muted" style="font-size:13px">Cargando...</p></div>
  </div>
</div>

<div id="toast"></div>

<div class="activity-bar">
  <div class="activity-hdr" onclick="toggleActivity()">
    <span class="act-dot" id="act-dot"></span>
    <span class="act-title">Actividad</span>
    <span class="act-summary" id="act-summary">sin eventos</span>
    <span class="act-toggle" id="act-toggle">▼</span>
  </div>
  <div id="activity-log" style="display:none"></div>
</div>

<script>
window.__runsData = {runs_json};
</script>
<script>{_js}</script>
<script>
_runsFilterProject = (document.getElementById("filterProject")||{{}}).value||"";
_runsFilterModel   = "";
renderRunsTable();
</script>

</body>
</html>"""
