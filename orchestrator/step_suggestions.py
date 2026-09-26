"""Conservative, read-only links between imported commits and open steps."""

from __future__ import annotations

import re
from typing import Any


_STEP_REFERENCE = re.compile(r"(?:step|paso)\s*#?(\d+)\b|\bs(\d+)\b", re.I)


def suggest_step_commits(
    conn: Any, project: str, since: str | None = None, ticket_regex: str = r"\b[A-Z]+-\d+\b",
    limit: int | None = None,
) -> list[dict]:
    """Return explainable commit candidates for open steps in active contexts."""
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
        commits_query += " AND ts>=?"
        params.append(since)
    ticket_pattern = re.compile(ticket_regex)
    commits = []
    for commit in conn.execute(commits_query + " ORDER BY ts DESC, id DESC", params):
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
