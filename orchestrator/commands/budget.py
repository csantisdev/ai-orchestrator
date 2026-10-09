"""Admisión de presupuesto de los comandos que llaman a un proveedor (RFC-010 §3.5, I15).

Antes de encolar, el costo estimado se reserva contra el presupuesto diario del proyecto. La
estimación es conservadora: los tokens previstos (configurables en `budgets`) al precio del
modelo más caro que el comando podría usar. Al terminar, la reserva se concilia con el costo
real del run (que ya cuenta en `daily_cost`) o se libera si el trabajo no llegó a gastarlo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

DEFAULT_RESERVATION_INPUT_TOKENS = 16_000
DEFAULT_RESERVATION_OUTPUT_TOKENS = 8_000


def period() -> str:
    """El período del presupuesto es el día local, igual que `db.daily_cost`."""
    return datetime.now().astimezone().date().isoformat()


def _price(table: dict, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * float(table.get("input", 0)) + output_tokens * float(table.get("output", 0))) / 1_000_000


def estimate_run_usd(config: dict, provider: Optional[str]) -> float:
    """Costo máximo previsto de un run: con `provider` forzado, su modelo; si no, el más caro
    de los proveedores configurados (el router puede elegir cualquiera). Un modelo sin precio
    conocido se estima con el precio más alto del catálogo."""
    from orchestrator.config import get_pricing_table

    budgets = config.get("budgets", {})
    input_tokens = int(budgets.get("reservation_input_tokens", DEFAULT_RESERVATION_INPUT_TOKENS))
    output_tokens = int(budgets.get("reservation_output_tokens", DEFAULT_RESERVATION_OUTPUT_TOKENS))
    pricing = get_pricing_table(config)
    ceiling = max((_price(table, input_tokens, output_tokens) for table in pricing.values()), default=0.0)
    providers = config.get("providers", {})
    names = [provider] if provider else list(providers)
    estimates = []
    for name in names:
        model = (providers.get(name) or {}).get("model")
        table = pricing.get(model) if model else None
        estimates.append(_price(table, input_tokens, output_tokens) if table else ceiling)
    return round(max(estimates, default=ceiling), 6)


def daily_limit(project: str, config: dict) -> float:
    """Límite diario del proyecto: el de su context.yaml o el de config.yaml."""
    limit = None
    try:
        from orchestrator import context as context_module
        from orchestrator import index as index_module
        ctx = context_module.load_context(index_module.get_project_path(project))
        limit = getattr(ctx, "daily_budget_usd", None)
    except Exception:
        limit = None
    return float(limit or config.get("budgets", {}).get("default_daily_budget_usd", 5.0))


def committed_usd(conn, project: str) -> float:
    """Gasto del día más las reservas abiertas del proyecto."""
    from orchestrator.db import daily_cost

    reserved = conn.execute(
        "SELECT COALESCE(SUM(estimated_usd), 0) FROM budget_reservations "
        "WHERE project = ? AND period = ? AND status = 'reserved'",
        (project, period()),
    ).fetchone()[0]
    return float(daily_cost(project)) + float(reserved)


def reserve(conn, request_id: str, project: str, estimated_usd: float) -> None:
    conn.execute(
        "INSERT INTO budget_reservations (request_id, project, period, estimated_usd, status, created_at) "
        "VALUES (?, ?, ?, ?, 'reserved', ?)",
        (request_id, project, period(), estimated_usd, datetime.now(timezone.utc).isoformat()),
    )


def close(conn, request_id: str, actual_usd: Optional[float]) -> None:
    """Concilia la reserva con el costo real, o la libera si no hubo costo."""
    status = "settled" if actual_usd is not None else "released"
    conn.execute(
        "UPDATE budget_reservations SET status = ?, actual_usd = ?, settled_at = ? "
        "WHERE request_id = ? AND status = 'reserved'",
        (status, actual_usd, datetime.now(timezone.utc).isoformat(), request_id),
    )
