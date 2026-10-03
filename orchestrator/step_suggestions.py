"""Conservative, read-only links between imported commits and open steps."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


_STEP_REFERENCE = re.compile(r"(?:step|paso)\s*#?(\d+)\b|\bs(\d+)\b", re.I)


def _normalize_since(since: str) -> str:
    """Parse an ISO date or datetime and return it in UTC.

    SQLite's julianday() also accepts values like "12:00", "1234" or
    "2026-02-30", so validation cannot rely on it.
    """
    value = since.strip()
    if value[-1:] in ("Z", "z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise ValueError(
            f"since inválido: {since!r}. Usá una fecha ISO, por ejemplo 2026-06-02 "
            "o 2026-06-02T00:00:00+00:00 (sin zona horaria se interpreta como UTC)."
        ) from None


def suggest_step_commits(
    conn: Any, project: str, since: str | None = None, ticket_regex: str = r"\b[A-Z]+-\d+\b",
    limit: int | None = None,
) -> list[dict]:
    """Return explainable commit candidates for open steps in active contexts."""
    if since is not None:
        since = _normalize_since(since)
    query = """SELECT s.id, s.title, s.description FROM steps s
               JOIN contexts c ON c.id=s.context_id
               WHERE c.project=? AND c.status='active' AND s.status IN ('pending', 'in_progress')
               ORDER BY c.id, s.order_idx, s.id"""
    steps = conn.execute(query, (project,)).fetchall()
    if not steps:
        return []
    commits_query = "SELECT ts, task, session_id FROM runs WHERE project=? AND provider='git'"
    params = [project]
    if since:
        commits_query += " AND julianday(ts)>=julianday(?)"
        params.append(since)
    ticket_pattern = re.compile(ticket_regex)
    commits = []
    for commit in conn.execute(commits_query + " ORDER BY julianday(ts) DESC, ts DESC, id DESC", params):
        task = commit["task"]
        references = {int(a or b) for a, b in _STEP_REFERENCE.findall(task)}
        commits.append((commit, references, set(ticket_pattern.findall(task))))
    results = []
    for step in steps:
        tickets = set(ticket_pattern.findall(step["title"]))
        candidates = []
        for commit, references, commit_tickets in commits:
            shared = tickets & commit_tickets
            if step["id"] in references:
                reason = f"referencia explícita al paso #{step['id']}"
                strength = "fuerte"
            elif shared:
                reason = f"ticket compartido: {', '.join(sorted(shared))}"
                strength = "fuerte"
            else:
                continue
            candidates.append({
                "sha": (commit["session_id"] or "").rsplit("::", 1)[-1][:8],
                "date": commit["ts"], "subject": commit["task"].splitlines()[0], "reason": reason, "strength": strength,
            })
        if candidates:
            results.append({"step_id": step["id"], "title": step["title"], "commits": candidates})
            if limit is not None and len(results) >= limit:
                break
    return results
