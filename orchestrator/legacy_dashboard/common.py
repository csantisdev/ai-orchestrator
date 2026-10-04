"""Helpers compartidos del dashboard heredado (formato, escape y colores).

`orchestrator.dashboard` los reexporta: cli, server y tests los importan desde ahí.
"""

from __future__ import annotations

import html
import json
from datetime import datetime


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


def _json_for_script(value: object) -> str:
    """JSON safe to embed inside a <script> block.

    json.dumps leaves "</script>" and "<!--" intact, so a run's text could
    close the block and inject markup. Escaping <, > and & (plus the JS line
    separators) keeps the same value once parsed.
    """
    return (
        json.dumps(value, ensure_ascii=False, default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


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
