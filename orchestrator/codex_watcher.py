"""Lee sesiones de Codex (state_N.sqlite + rollout JSONL) e importa al DB del orquestador."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROVIDER_NAME = "codex"
CODEX_HOME = Path.home() / ".codex"


def _find_state_db() -> Optional[Path]:
    """Retorna el state_N.sqlite más reciente en ~/.codex/ (por mtime)."""
    candidates = sorted(
        CODEX_HOME.glob("state_*.sqlite"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _strip_cwd_prefix(cwd: str) -> str:
    """Elimina el prefijo de long paths de Windows (\\\\?\\)."""
    if cwd.startswith("\\\\?\\"):
        return cwd[4:]
    return cwd


def _cwd_to_alias(cwd: str, index: dict) -> str:
    """Mapea un cwd (ya sin prefijos) al alias de proyecto más cercano registrado."""
    if not cwd:
        return ""
    try:
        cwd_path = Path(cwd).resolve()
    except (OSError, ValueError):
        return Path(cwd).name
    best_alias = ""
    best_len = 0
    for alias, proj_path in index.items():
        try:
            p = Path(proj_path).resolve()
            if cwd_path == p or p in cwd_path.parents or cwd_path in p.parents:
                if len(str(p)) > best_len:
                    best_len = len(str(p))
                    best_alias = alias
        except (OSError, ValueError):
            pass
    return best_alias or Path(cwd).name


def _parse_jsonl_tokens(rollout_path: str) -> dict:
    """Lee el JSONL de rollout y devuelve el último total_token_usage acumulado.

    Los event_msg acumulan tokens turno a turno; el último da el total de la sesión.
    """
    last_usage: dict = {}
    try:
        for line in Path(rollout_path).open(encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "event_msg":
                continue
            payload = d.get("payload") or {}
            info = payload.get("info") or {}
            tu = info.get("total_token_usage")
            if tu and isinstance(tu, dict):
                last_usage = tu
    except OSError:
        pass
    return last_usage


def _extract_response_text(rollout_path: str, max_chars: int = 8000) -> str:
    """Concatena texto de bloques assistant/response_item del rollout JSONL."""
    texts: list[str] = []
    total = 0
    try:
        for line in Path(rollout_path).open(encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "response_item":
                continue
            payload = d.get("payload") or {}
            if payload.get("role") != "assistant":
                continue
            for block in (payload.get("content") or []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        texts.append(text)
                        total += len(text)
                        if total >= max_chars:
                            return "\n\n---\n\n".join(texts)
    except OSError:
        pass
    return "\n\n---\n\n".join(texts)


@dataclass
class CodexThread:
    thread_id: str
    cwd: str
    model: str
    model_provider: str
    ts_start: str
    duration_ms: int
    task: str
    rollout_path: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    response_text: str = ""


def scan_and_import(config: dict, quiet: bool = False) -> list[dict]:
    """Escanea ~/.codex/state_N.sqlite e importa threads nuevos al DB.

    Omite threads activos (updated_at_ms < 1min atrás) y threads cuyo cwd
    no corresponde a ningún proyecto registrado.

    Retorna lista de resúmenes de lo importado.
    """
    import sqlite3

    from orchestrator.config import get_pricing_table
    from orchestrator.costs import calculate_cost
    from orchestrator.db import _conn, _write_lock, init_db
    from orchestrator.index import load_index
    from orchestrator.providers.base import CompletionResult

    init_db()
    conn = _conn()
    index = load_index().get("projects", {})
    pricing = get_pricing_table(config)
    imported: list[dict] = []

    state_db = _find_state_db()
    if not state_db:
        return []

    cutoff_ms = int(time.time() * 1000) - 60_000  # ignorar threads activos

    codex_conn = sqlite3.connect(str(state_db))
    codex_conn.row_factory = sqlite3.Row
    try:
        rows = codex_conn.execute(
            """SELECT id, cwd, model, model_provider,
                      created_at_ms, updated_at_ms,
                      first_user_message, rollout_path
               FROM threads
               WHERE first_user_message IS NOT NULL
                 AND first_user_message != ''
                 AND (updated_at_ms IS NULL OR updated_at_ms < ?)
               ORDER BY created_at_ms""",
            (cutoff_ms,),
        ).fetchall()
    except sqlite3.OperationalError:
        codex_conn.close()
        return []
    finally:
        codex_conn.close()

    try:
        from orchestrator.tracer import span as _tspan
    except Exception:
        from contextlib import nullcontext as _tspan  # type: ignore[assignment]

    for r in rows:
        thread_id = str(r["id"])

        if conn.execute(
            "SELECT 1 FROM runs WHERE session_id=?", (thread_id,)
        ).fetchone():
            continue

        cwd = _strip_cwd_prefix(r["cwd"] or "")
        project_alias = _cwd_to_alias(cwd, index)
        if not project_alias:
            continue

        rollout = r["rollout_path"] or ""
        task = (r["first_user_message"] or "")[:150].replace("\n", " ").strip()
        label = task[:60] or thread_id[:8]

        with _tspan(f"Codex · {project_alias}", detail=label):
            tokens = _parse_jsonl_tokens(rollout) if rollout else {}
            input_tokens  = int(tokens.get("input_tokens", 0) or 0)
            output_tokens = int(tokens.get("output_tokens", 0) or 0)
            cache_read    = int(tokens.get("cached_input_tokens", 0) or 0)

            if input_tokens + output_tokens == 0:
                continue

            response_text = _extract_response_text(rollout) if rollout else ""

            created_ms  = int(r["created_at_ms"] or 0)
            updated_ms  = int(r["updated_at_ms"] or created_ms)
            duration_ms = max(updated_ms - created_ms, 0)
            ts_start = (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
                if created_ms else datetime.now(timezone.utc).isoformat()
            )

            model = r["model"] or ""
            fake_result = CompletionResult(
                text=response_text,
                provider=PROVIDER_NAME,
                model=model,
                raw_response={"usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }},
                cache_read_tokens=cache_read,
            )
            cost_usd = calculate_cost(fake_result, pricing)

            with _write_lock:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO runs
                       (ts, project, provider, model, status,
                        task, task_preview, response,
                        duration_ms, input_tokens, output_tokens,
                        cache_creation_tokens, cache_read_tokens,
                        cost_usd, routing_reason, session_id)
                       VALUES (?, ?, ?, ?, 'done', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
                    (
                        ts_start,
                        project_alias,
                        PROVIDER_NAME,
                        model,
                        task,
                        task[:150],
                        response_text,
                        duration_ms,
                        input_tokens,
                        output_tokens,
                        cache_read,
                        cost_usd,
                        f"Codex thread · {thread_id[:8]}",
                        thread_id,
                    ),
                )
                conn.commit()

            run_id = cur.lastrowid
            if run_id:
                try:
                    from orchestrator.db import get_active_step_id
                    step_id = get_active_step_id(project_alias)
                    if step_id:
                        with _write_lock:
                            conn.execute(
                                "UPDATE runs SET step_id=? WHERE id=? AND step_id IS NULL",
                                (step_id, run_id),
                            )
                            conn.commit()
                except Exception:
                    pass
            if run_id and response_text:
                try:
                    from orchestrator.rag import index_response
                    with _tspan(f"Codex · index-response · {project_alias}"):
                        index_response(run_id, project_alias, task, response_text)
                except Exception:
                    pass

        imported.append({
            "project": project_alias,
            "session_id": thread_id[:8],
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "task_preview": task[:60],
        })

    return imported
