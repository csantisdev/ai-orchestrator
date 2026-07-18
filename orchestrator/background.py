"""Worker threads para runs asíncronos desde el dashboard."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

from orchestrator import egress
from orchestrator.db import fail_run, insert_run, update_run
from orchestrator.egress import EgressBlocked, EgressPolicy
from orchestrator.sse import BUS

_log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE = 2.0
_MAX_PARALLEL = 4
_semaphore = threading.Semaphore(_MAX_PARALLEL)


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
        args=(run_id, project, task, config, model, ctx, step_id),
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
    step_id: Optional[int] = None,
) -> None:
    policy_token = None
    try:
        from orchestrator import context as context_module
        from orchestrator import index as index_module
        from orchestrator import router as router_module
        from orchestrator.config import get_pricing_table
        from orchestrator.costs import calculate_cost, check_budget
        from orchestrator.providers.factory import build_provider

        if ctx is None:
            project_path = index_module.get_project_path(project)
            try:
                ctx = context_module.load_context(project_path)
            except context_module.ContextNotFoundError:
                ctx = None
                policy = EgressPolicy(project=project, sensitivity="internal")
            else:
                policy = egress.policy_for_project(ctx, config)
        else:
            policy = egress.policy_for_project(ctx, config)

        policy_token = egress.set_policy(policy)

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
        if decision.model:
            provider.model = decision.model

        system_prompt = (
            f"Eres un asistente técnico. Estás trabajando en el proyecto '{project}'.\n"
            "Responde directamente a la tarea sin pedir información adicional. "
            "Usa el contexto disponible para dar una respuesta concreta.\n"
        )
        if ctx:
            if ctx.stack:
                system_prompt += f"Stack: {ctx.stack}\n"
            if ctx.description:
                system_prompt += f"Descripción: {ctx.description}\n"
            if ctx.conventions:
                system_prompt += f"Convenciones: {', '.join(ctx.conventions)}\n"
            if ctx.routing_notes:
                system_prompt += f"Notas: {ctx.routing_notes}\n"

        if decision.system_prompt_addition:
            system_prompt += f"\n{decision.system_prompt_addition}\n"

        _rag_chunks: list[dict] = []
        try:
            from orchestrator.rag import retrieve_docs, retrieve_responses, build_context_block
            with _span("RAG retrieval", run_id=run_id):
                _doc_chunks = retrieve_docs(task, project)
                _resp_chunks = retrieve_responses(task, project)
                _rag_chunks = _doc_chunks + _resp_chunks
                rag_block = build_context_block(_doc_chunks, _resp_chunks)
            if rag_block:
                system_prompt += "\n\n" + rag_block
        except Exception as exc:
            _log.warning("RAG retrieval failed for run %d: %s", run_id, exc)

        from orchestrator.providers.base import StreamResult

        t0 = time.monotonic()
        _last_exc: Exception | None = None
        with _semaphore:
            for _attempt in range(_MAX_RETRIES):
                try:
                    with _span(f"{decision.provider} · API", run_id=run_id):
                        _gen = provider.complete_stream(prompt=task, system=system_prompt)
                        _sr: StreamResult | None = None
                        try:
                            while True:
                                _chunk = next(_gen)
                                BUS.publish(
                                    "run_token",
                                    json.dumps({"run_id": run_id, "chunk": _chunk}),
                                )
                        except StopIteration as _si:
                            _sr = _si.value
                        result = _sr.to_completion_result() if _sr is not None else provider.complete(prompt=task, system=system_prompt)
                    _last_exc = None
                    break
                except EgressBlocked:
                    raise
                except Exception as exc:
                    _last_exc = exc
                    if _attempt < _MAX_RETRIES - 1:
                        _delay = _RETRY_BASE ** _attempt
                        _log.warning(
                            "Run %d attempt %d/%d failed: %s — retrying in %.0fs",
                            run_id, _attempt + 1, _MAX_RETRIES, exc, _delay,
                        )
                        time.sleep(_delay)
        if _last_exc is not None:
            raise _last_exc
        duration_ms = int((time.monotonic() - t0) * 1000)

        pricing = get_pricing_table(config)
        cost_usd = calculate_cost(result, pricing)

        update_run(
            run_id=run_id,
            result=result,
            duration_ms=duration_ms,
            routing_reason=decision.reason,
            cost_usd=cost_usd,
            router_cost_usd=decision.router_cost_usd,
            routing_source=decision.routing_source,
        )

        if _rag_chunks:
            try:
                from orchestrator.rag import persist_context_hits
                persist_context_hits(run_id, _rag_chunks)
            except Exception as exc:
                _log.warning("persist_context_hits failed for run %d: %s", run_id, exc)

        try:
            from orchestrator.rag import index_response
            with _span("Indexar respuesta", run_id=run_id):
                index_response(run_id, project, task, result.text)
        except Exception as exc:
            _log.warning("index_response failed for run %d: %s", run_id, exc)

        event = {
            "run_id": run_id,
            "project": project,
            "provider": result.provider,
            "model": result.model,
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
        }
        if step_id is not None:
            event["step_id"] = step_id
        BUS.publish("run_done", json.dumps(event))

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
    finally:
        if policy_token is not None:
            egress._POLICY.reset(policy_token)
