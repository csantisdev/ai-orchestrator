"""Worker threads para runs asíncronos desde el dashboard."""

from __future__ import annotations

import json
import threading
import time
from typing import Optional

from orchestrator.db import fail_run, insert_run, update_run
from orchestrator.sse import BUS


def submit_run(
    project: str,
    task: str,
    config: dict,
    model: Optional[str] = None,
    ctx=None,
) -> int:
    from orchestrator.router import _fetch_active_context
    active = _fetch_active_context(project)
    step_id = active["active_step"]["id"] if active and active.get("active_step") else None

    run_id = insert_run(
        project=project,
        task=task,
        provider="?",
        model="?",
        status="pending",
        step_id=step_id,
    )
    BUS.publish("run_started", json.dumps({"run_id": run_id, "project": project}))

    thread = threading.Thread(
        target=_worker,
        args=(run_id, project, task, config, model, ctx),
        daemon=True,
    )
    thread.start()
    return run_id


def _worker(
    run_id: int,
    project: str,
    task: str,
    config: dict,
    forced_model: Optional[str],
    ctx,
) -> None:
    try:
        from orchestrator import context as context_module
        from orchestrator import index as index_module
        from orchestrator import router as router_module
        from orchestrator.config import get_pricing_table
        from orchestrator.costs import calculate_cost, check_budget
        from orchestrator.providers.factory import build_provider

        if ctx is None:
            try:
                project_path = index_module.get_project_path(project)
                ctx = context_module.load_context(project_path)
            except Exception:
                ctx = None

        from orchestrator.tracer import span as _span

        if forced_model:
            decision = router_module.force_provider(forced_model)
        elif ctx:
            with _span("Router", run_id=run_id):
                decision = router_module.decide_provider(task=task, ctx=ctx, config=config)
        else:
            decision = router_module.force_provider(
                config.get("defaults", {}).get("default_provider", "claude")
            )

        provider = build_provider(config, decision.provider)

        system_prompt = ""
        if ctx:
            system_prompt = (
                f"Estás trabajando en el proyecto '{ctx.name}'.\n"
                f"Stack: {ctx.stack}\n"
                f"Convenciones: {', '.join(ctx.conventions) if ctx.conventions else 'ninguna registrada'}\n"
            )
            try:
                from orchestrator.rag import retrieve_docs, retrieve_responses, build_context_block
                with _span("RAG retrieval", run_id=run_id):
                    rag_block = build_context_block(
                        retrieve_docs(task, project),
                        retrieve_responses(task, project),
                    )
                if rag_block:
                    system_prompt += "\n\n" + rag_block
            except Exception:
                pass

        t0 = time.monotonic()
        with _span(f"{decision.provider} · API", run_id=run_id):
            result = provider.complete(prompt=task, system=system_prompt)
        duration_ms = int((time.monotonic() - t0) * 1000)

        pricing = get_pricing_table(config)
        cost_usd = calculate_cost(result, pricing)

        update_run(
            run_id=run_id,
            result=result,
            duration_ms=duration_ms,
            routing_reason=decision.reason,
            cost_usd=cost_usd,
        )

        try:
            from orchestrator.rag import index_response
            with _span("Indexar respuesta", run_id=run_id):
                index_response(run_id, project, task, result.text)
        except Exception:
            pass

        BUS.publish(
            "run_done",
            json.dumps({
                "run_id": run_id,
                "project": project,
                "provider": result.provider,
                "model": result.model,
                "duration_ms": duration_ms,
                "cost_usd": cost_usd,
            }),
        )

        budget_usd = getattr(ctx, "daily_budget_usd", None) if ctx else None
        budget = check_budget(project, config, daily_budget_usd=budget_usd)
        if budget["warning"]:
            BUS.publish(
                "budget_warning",
                json.dumps({
                    "project": project,
                    "spent_usd": budget["spent_usd"],
                    "limit_usd": budget["limit_usd"],
                    "pct": budget["pct"],
                }),
            )

    except Exception as exc:
        fail_run(run_id, str(exc))
        BUS.publish("run_failed", json.dumps({"run_id": run_id, "error": str(exc)}))
