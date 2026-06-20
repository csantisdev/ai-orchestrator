"""Persistencia y lectura del historial de runs del orquestador."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.paths import HOME_DIR
from orchestrator.providers.base import CompletionResult

RUNS_PATH = HOME_DIR / "runs.jsonl"


def _tokens(result: CompletionResult) -> tuple[int | None, int | None]:
    usage = (result.raw_response or {}).get("usage", {})
    if "input_tokens" in usage:
        return usage.get("input_tokens"), usage.get("output_tokens")
    if "prompt_tokens" in usage:
        return usage.get("prompt_tokens"), usage.get("completion_tokens")
    return None, None


def log_run(
    project: str,
    task: str,
    result: CompletionResult,
    duration_ms: int,
    routing_reason: str = "",
) -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    in_tok, out_tok = _tokens(result)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "provider": result.provider,
        "model": result.model,
        "task_preview": task[:150].replace("\n", " ").strip(),
        "duration_ms": duration_ms,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "routing_reason": routing_reason,
    }
    with RUNS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_runs(project: str | None = None, last: int = 200) -> list[dict]:
    if not RUNS_PATH.exists():
        return []
    runs = []
    for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    if project:
        runs = [r for r in runs if r.get("project") == project]
    return runs[-last:]


def projects_list() -> list[str]:
    runs = read_runs()
    seen: dict[str, None] = {}
    for r in runs:
        p = r.get("project", "")
        if p:
            seen[p] = None
    return list(seen.keys())
