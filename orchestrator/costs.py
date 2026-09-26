"""Cálculo de costo estimado en USD por run."""

from __future__ import annotations

import logging

from orchestrator.providers.base import CompletionResult

_log = logging.getLogger(__name__)

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5":     {"input": 10.00, "output": 50.00, "cache_write": 12.50, "cache_read": 1.00},
    "claude-opus-5-5":    {"input": 4.00,  "output": 20.00, "cache_write": 5.00,  "cache_read": 0.20},
    "claude-opus-5":      {"input": 5.00,  "output": 25.00, "cache_write": 6.25,  "cache_read": 0.50},
    "claude-sonnet-5":    {"input": 2.00,  "output": 10.00, "cache_write": 2.50,  "cache_read": 0.20},
    "claude-sonnet-4-6":  {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-opus-4-8":    {"input": 5.00,  "output": 25.00, "cache_write": 6.25,  "cache_read": 0.50},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
    "gpt-4o":             {"input": 2.50,  "output": 10.00, "cache_read": 1.25},
    "gpt-4o-mini":        {"input": 0.15,  "output": 0.60,  "cache_read": 0.075},
    "gpt-5.4-mini":       {"input": 0.75,  "output": 4.50,  "cache_read": 0.075},
    "gpt-5":              {"input": 1.25,  "output": 10.00, "cache_read": 0.125},
    "gpt-5.6-sol":        {"input": 4.00,  "output": 20.00, "cache_write": 5.00,  "cache_read": 0.40},
    "gpt-5.6-terra":      {"input": 2.00,  "output": 12.00, "cache_write": 2.50,  "cache_read": 0.20},
    "gpt-5.6-luna":       {"input": 0.20,  "output": 1.20,  "cache_write": 0.25,  "cache_read": 0.02},
    "gpt-5.5":            {"input": 5.00,  "output": 30.00, "cache_read": 0.50},
    "gpt-5.4":            {"input": 2.50,  "output": 15.00, "cache_read": 0.25},
    "gpt-5.3-codex":      {"input": 1.75,  "output": 14.00, "cache_read": 0.175},
    "gpt-5.1-codex-max":  {"input": 1.25,  "output": 10.00, "cache_read": 0.125},
    "deepseek-v4-flash":  {"input": 0.14,  "output": 0.28},
    "deepseek-chat":      {"input": 0.14,  "output": 0.28},
    # verificar precio vigente en platform.deepseek.com/api-docs
    "deepseek-v4-pro":    {"input": 0.435, "output": 0.87},
    "gemini-2.5-pro":     {"input": 1.25,  "output": 10.00},
    "gemini-2.5-flash":   {"input": 0.30,  "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
}


def resolve_price_key(model: str, pricing: dict) -> str | None:
    """Clave de `pricing` usada para costear `model`; la subcadena más larga como último recurso."""
    if not model:
        return None
    for key in (model, model.split("/")[-1]):
        if pricing.get(key):
            return key
    matches = [key for key in pricing if key and key in model and pricing.get(key)]
    if not matches:
        return None
    key = max(matches, key=len)
    _log.warning("pricing: substring fallback %r → %r; add exact key to config", model, key)
    return key


def is_approximate_price_key(model: str, price_key: str | None) -> bool:
    """True si el costo se calculó con el precio de otro modelo (fallback por subcadena)."""
    return bool(price_key) and price_key not in (model, model.split("/")[-1])


def calculate_cost(result: CompletionResult, pricing: dict) -> float | None:
    return calculate_cost_with_key(result, pricing)[0]


def calculate_cost_with_key(result: CompletionResult, pricing: dict) -> tuple[float | None, str | None]:
    """Costo estimado y clave de precio usada; `(None, None)` si el modelo no tiene precio."""
    key = resolve_price_key(result.model or "", pricing)
    if key is None:
        return None, None
    table = pricing[key]

    usage = (result.raw_response or {}).get("usage", {})
    inp = result.input_tokens or usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    out = result.output_tokens or usage.get("output_tokens") or usage.get("completion_tokens") or 0
    cc  = getattr(result, "cache_creation_tokens", 0) or 0
    cr  = getattr(result, "cache_read_tokens", 0) or 0

    inp_billable = max(inp - cc - cr, 0)
    cost = (
        inp_billable * table.get("input", 0)      / 1_000_000
        + out         * table.get("output", 0)    / 1_000_000
        + cc          * table.get("cache_write", table.get("input", 0)) / 1_000_000
        + cr          * table.get("cache_read",  table.get("input", 0)) / 1_000_000
    )
    return round(cost, 6), key


def check_budget(project: str, config: dict, daily_budget_usd: float | None = None) -> dict:
    from orchestrator.db import daily_cost
    budget_cfg = config.get("budgets", {})
    limit = daily_budget_usd or budget_cfg.get("default_daily_budget_usd", 5.0)
    threshold = float(budget_cfg.get("warning_threshold", 0.80))
    spent = daily_cost(project)
    pct = spent / limit if limit else 0.0
    return {
        "spent_usd": spent,
        "limit_usd": limit,
        "pct": pct,
        "warning": pct >= threshold,
        "over": pct >= 1.0,
    }
