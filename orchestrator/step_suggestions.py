"""Conservative, read-only links between imported commits and open steps."""

from __future__ import annotations

import re
from typing import Any


def suggest_step_commits(conn: Any, project: str, since: str | None = None, ticket_regex: str = r"\b[A-Z]+-\d+\b") -> list[dict]:
    """Return explainable commit candidates for open steps in active contexts."""
    query = """SELECT s.id, s.title, s.description FROM steps s
               JOIN contexts c ON c.id=s.context_id
               WHERE c.project=? AND c.status='active' AND s.status IN ('pending', 'in_progress')"""
    steps = conn.execute(query, (project,)).fetchall()
    commits_query = "SELECT ts, task, session_id FROM runs WHERE project=? AND provider='git'"
    params = [project]
    if since:
        commits_query += " AND ts>=?"
        params.append(since)
    commits = conn.execute(commits_query + " ORDER BY ts DESC", params).fetchall()
    ticket_pattern = re.compile(ticket_regex)
    results = []
    for step in steps:
        step_text = f"{step['title']}\n{step['description']}"
        tickets = set(ticket_pattern.findall(step_text))
        candidates = []
        for commit in commits:
            task = commit["task"]
            explicit = re.search(rf"(?:\bstep\s*|\bs){step['id']}\b|#{step['id']}\b", task, re.I)
            shared = tickets & set(ticket_pattern.findall(task))
            if explicit:
                reason = f"referencia explícita al paso #{step['id']}"
            elif shared:
                reason = f"ticket compartido: {', '.join(sorted(shared))}"
            else:
                continue
            candidates.append({
                "sha": (commit["session_id"] or "").rsplit("::", 1)[-1][:8],
                "date": commit["ts"], "subject": task.splitlines()[0], "reason": reason,
            })
        if candidates:
            results.append({"step_id": step["id"], "title": step["title"], "commits": candidates})
    return results
