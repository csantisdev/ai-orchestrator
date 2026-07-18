"""Evaluaciones offline de las decisiones de routing históricas."""

from __future__ import annotations

from typing import Any

from orchestrator import context as context_module
from orchestrator import egress
from orchestrator import index as index_module
from orchestrator.egress import EgressBlocked
from orchestrator.router import decide_with_local_router


def offline_router_eval(
    config: dict,
    project: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Compara el routing LLM histórico con el router local, sin usar la red."""
    if limit < 1:
        raise ValueError("limit debe ser mayor que cero")

    from orchestrator.db import _conn

    conn = _conn()
    run_columns = {
        row["name"] if hasattr(row, "keys") else row[1]
        for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }

    conditions = ["status='done'", "task != ''"]
    params: list[Any] = []
    if "routing_source" in run_columns:
        conditions.append("routing_source='llm_router'")
    if project is not None:
        conditions.append("project=?")
        params.append(project)
    params.append(limit)

    rows = conn.execute(
        f"""SELECT project, task, provider, rating, router_cost_usd
            FROM runs
            WHERE {' AND '.join(conditions)}
            ORDER BY ts DESC
            LIMIT ?""",
        params,
    ).fetchall()

    evaluated_runs = 0
    skipped_runs = 0
    agreements = 0
    rated_runs = 0
    observed_router_costs: list[float] = []

    for row in rows:
        try:
            project_path = index_module.get_project_path(row["project"])
            ctx = context_module.load_context(project_path)
        except Exception:
            # Los históricos pueden referir a proyectos borrados o contextos viejos.
            skipped_runs += 1
            continue

        token = None
        try:
            token = egress.set_policy(egress.policy_for_project(ctx, config))
            local_choice = decide_with_local_router(row["task"], ctx, config)
        except EgressBlocked:
            skipped_runs += 1
            continue
        finally:
            if token is not None:
                egress._POLICY.reset(token)

        evaluated_runs += 1
        agreements += local_choice.provider == row["provider"]
        rated_runs += row["rating"] is not None
        if row["router_cost_usd"] is not None:
            observed_router_costs.append(float(row["router_cost_usd"]))

    return {
        "evaluated_runs": evaluated_runs,
        "skipped_runs": skipped_runs,
        "agreement_rate": agreements / evaluated_runs if evaluated_runs else 0.0,
        "rating_coverage": rated_runs / evaluated_runs if evaluated_runs else 0.0,
        "external_router_spend_usd": (
            sum(observed_router_costs) if observed_router_costs else None
        ),
        "router_cost_observed_runs": len(observed_router_costs),
        "router_cost_missing_runs": evaluated_runs - len(observed_router_costs),
    }
