"""Lee sesiones de Claude Code y las importa al DB del orquestador."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CLAUDE_HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"

PROVIDER_NAME = "claude-code"


@dataclass
class CCSession:
    session_id: str
    project_cwd: str
    model: str
    ts_start: str
    ts_end: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    task_preview: str = ""
    slug: str = ""
    prompts: list[str] = field(default_factory=list)


def _parse_session(jsonl_path: Path) -> Optional[CCSession]:
    entries = []
    try:
        with jsonl_path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        return None

    if not entries:
        return None

    session_id = None
    cwd = ""
    model = "claude-sonnet-4-6"
    timestamps: list[datetime] = []
    total_input = 0
    total_output = 0
    total_cache_creation = 0
    total_cache_read = 0
    user_prompts: list[str] = []

    for entry in entries:
        etype = entry.get("type", "")

        if not session_id and entry.get("sessionId"):
            session_id = entry["sessionId"]

        if not cwd and entry.get("cwd"):
            cwd = entry["cwd"]

        raw_ts = entry.get("timestamp")
        if raw_ts:
            try:
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                timestamps.append(ts)
            except (ValueError, TypeError):
                pass

        if etype == "assistant":
            msg = entry.get("message", {})
            if msg.get("model") and msg["model"] != "<synthetic>":
                model = msg["model"]
            usage = msg.get("usage", {})
            total_input            += usage.get("input_tokens", 0) or 0
            total_output           += usage.get("output_tokens", 0) or 0
            total_cache_creation   += usage.get("cache_creation_input_tokens", 0) or 0
            total_cache_read       += usage.get("cache_read_input_tokens", 0) or 0

        if etype == "user":
            msg = entry.get("message", {})
            content = msg.get("content", []) if isinstance(msg, dict) else []
            for block in (content if isinstance(content, list) else []):
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        user_prompts.append(text)
                elif isinstance(block, str) and block.strip():
                    user_prompts.append(block.strip())

    if not session_id:
        session_id = jsonl_path.stem

    if not timestamps:
        return None

    ts_start = min(timestamps)
    ts_end   = max(timestamps)
    duration_ms = int((ts_end - ts_start).total_seconds() * 1000)

    first_prompt = user_prompts[0][:150].replace("\n", " ").strip() if user_prompts else ""

    return CCSession(
        session_id=session_id,
        project_cwd=cwd,
        model=model,
        ts_start=ts_start.isoformat(),
        ts_end=ts_end.isoformat(),
        duration_ms=max(duration_ms, 0),
        input_tokens=total_input,
        output_tokens=total_output,
        cache_creation_tokens=total_cache_creation,
        cache_read_tokens=total_cache_read,
        task_preview=first_prompt,
        slug=jsonl_path.parent.name,
        prompts=user_prompts[:3],
    )


def _cwd_to_alias(cwd: str, index: dict) -> str:
    """Mapea un path de cwd al alias del proyecto más cercano."""
    if not cwd:
        return ""
    cwd_path = Path(cwd).resolve()
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


def _session_already_imported(conn, session_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM runs WHERE session_id=?", (session_id,)
    ).fetchone()
    return row is not None


def scan_and_import(config: dict, quiet: bool = False) -> list[dict]:
    """Escanea ~/.claude/projects/ e importa sesiones nuevas al DB.

    Retorna lista de resúmenes de lo importado.
    """
    from orchestrator.costs import DEFAULT_PRICING, calculate_cost
    from orchestrator.db import _conn, _write_lock, init_db
    from orchestrator.index import load_index
    from orchestrator.providers.base import CompletionResult

    init_db()
    conn = _conn()
    index = load_index().get("projects", {})
    pricing = config.get("pricing", {}) or DEFAULT_PRICING
    imported = []

    if not CLAUDE_PROJECTS_DIR.exists():
        return []

    for slug_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not slug_dir.is_dir():
            continue
        for jsonl_file in sorted(slug_dir.glob("*.jsonl")):
            session = _parse_session(jsonl_file)
            if session is None:
                continue
            if session.input_tokens + session.output_tokens == 0:
                continue
            if _session_already_imported(conn, session.session_id):
                continue

            project_alias = _cwd_to_alias(session.project_cwd, index)
            if not project_alias:
                project_alias = slug_dir.name.replace("C--Fuentes-", "").replace("c--Fuentes-", "").split("-")[0]

            fake_result = CompletionResult(
                text="",
                provider=PROVIDER_NAME,
                model=session.model,
                raw_response={"usage": {
                    "input_tokens": session.input_tokens,
                    "output_tokens": session.output_tokens,
                }},
                cache_creation_tokens=session.cache_creation_tokens,
                cache_read_tokens=session.cache_read_tokens,
            )
            cost_usd = calculate_cost(fake_result, pricing)

            with _write_lock:
                conn.execute(
                    """INSERT OR IGNORE INTO runs
                       (ts, project, provider, model, status,
                        task, task_preview, response,
                        duration_ms, input_tokens, output_tokens,
                        cache_creation_tokens, cache_read_tokens,
                        cost_usd, routing_reason, session_id)
                       VALUES (?, ?, ?, ?, 'done', ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session.ts_start,
                        project_alias,
                        PROVIDER_NAME,
                        session.model,
                        session.task_preview,
                        session.task_preview,
                        session.duration_ms,
                        session.input_tokens,
                        session.output_tokens,
                        session.cache_creation_tokens,
                        session.cache_read_tokens,
                        cost_usd,
                        f"Claude Code session · {session.slug[:40]}",
                        session.session_id,
                    ),
                )
                conn.commit()

            imported.append({
                "project": project_alias,
                "session_id": session.session_id[:8],
                "model": session.model,
                "input_tokens": session.input_tokens,
                "output_tokens": session.output_tokens,
                "cost_usd": cost_usd,
                "task_preview": session.task_preview[:60],
            })

    return imported
