"""Proyecciones puras de la base hacia los DTO del dashboard (spec §10, §20, §21.4).

Leen SQLite y devuelven estructuras serializables; no escriben ni modifican los
datos de origen. La normalización de agentes y timestamps vive solo acá (§20.4).
"""

from __future__ import annotations

import bisect
import re
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

AGENT_CATALOG = ("claude", "codex", "copilot", "gemini")
NO_AGENT = "sin agente"

_SHA_CANDIDATE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{7,40}(?![0-9A-Za-z])")
_PR_REFERENCE = re.compile(r"\bPR\s*#?(\d+)\b", re.I)
_TEST_MENTION = re.compile(r"\b(?:pytest|tests?|passed)\b", re.I)
_GIT_SESSION_PREFIX = "git::"

ACTIVITY_KIND_ORDER = (
    "run",
    "egress_decision",
    "tool_call",
    "alignment",
    "mcp_invocation",
    "step_completed",
    "step_started",
)


def parse_instant(value: object) -> Optional[datetime]:
    """Parsea un timestamp ISO a un datetime UTC; sin zona se interpreta como UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def to_utc(value: object) -> Optional[str]:
    """Timestamp ISO normalizado a UTC (`+00:00`), o None si no se puede parsear."""
    instant = parse_instant(value)
    return instant.isoformat() if instant is not None else None


def normalize_agent(value: object) -> str:
    """Identidad del agente en el catálogo común; lo desconocido cae en `sin agente`.

    Acepta los alias que hoy conviven en `alignments.agent`, `steps.provider` y
    `mcp_invocations.client_surface` (`claude-code`, `copilot-cli`, `github-copilot`…).
    """
    if not isinstance(value, str):
        return NO_AGENT
    text = value.strip().lower()
    for agent in AGENT_CATALOG:
        if agent in text:
            return agent
    return NO_AGENT


def _catalog_rank(agent: str) -> int:
    return AGENT_CATALOG.index(agent) if agent in AGENT_CATALOG else len(AGENT_CATALOG)


def extract_references(notes: object) -> dict:
    """Referencias citadas en las notas de un paso, con la gramática de §20.0."""
    text = notes if isinstance(notes, str) else ""
    shas: list[str] = []
    for match in _SHA_CANDIDATE.finditer(text):
        token = match.group(0).lower()
        if not any(ch.isdigit() for ch in token) or not any(ch in "abcdef" for ch in token):
            continue
        if token not in shas:
            shas.append(token)
    prs: list[int] = []
    for match in _PR_REFERENCE.finditer(text):
        number = int(match.group(1))
        if number not in prs:
            prs.append(number)
    return {
        "sha_candidates": shas,
        "prs": prs,
        "mentions_tests": bool(_TEST_MENTION.search(text)),
    }


class CommitIndex:
    """SHAs completos de los commits importados (`runs.session_id = git::<alias>::<sha>`)."""

    def __init__(self, shas: Iterable[str]):
        self._shas = sorted({sha.lower() for sha in shas if sha})

    @classmethod
    def from_db(cls, conn: sqlite3.Connection) -> "CommitIndex":
        rows = conn.execute(
            "SELECT session_id FROM runs WHERE session_id LIKE ?", (_GIT_SESSION_PREFIX + "%",)
        ).fetchall()
        shas = []
        for (session_id,) in rows:
            parts = session_id.split("::")
            if len(parts) == 3 and parts[2]:
                shas.append(parts[2])
        return cls(shas)

    def resolve(self, token: str) -> Optional[str]:
        """SHA completo si `token` es prefijo de exactamente un commit; si no, None."""
        token = token.lower()
        start = bisect.bisect_left(self._shas, token)
        matches = []
        for sha in self._shas[start:]:
            if not sha.startswith(token):
                break
            matches.append(sha)
            if len(matches) > 1:
                return None
        return matches[0] if matches else None


def step_references(notes: object, commits: CommitIndex) -> dict:
    """Referencias de un paso separadas en SHAs verificados y texto sin verificar."""
    refs = extract_references(notes)
    verified: list[str] = []
    unverified: list[str] = []
    for token in refs["sha_candidates"]:
        full = commits.resolve(token)
        if full is None:
            unverified.append(token)
        elif full not in verified:
            verified.append(full)
    return {
        "verified_commits": verified,
        "unverified_shas": unverified,
        "prs": refs["prs"],
        "mentions_tests": refs["mentions_tests"],
    }


def _now_utc(now: Optional[datetime]) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _step_lanes(provider: object, alignment_agents: list[str]) -> tuple[str, list[str]]:
    lane = normalize_agent(provider)
    counts: dict[str, int] = {}
    for agent in alignment_agents:
        if agent != NO_AGENT:
            counts[agent] = counts.get(agent, 0) + 1
    if lane == NO_AGENT and counts:
        lane = min(counts, key=lambda agent: (-counts[agent], _catalog_rank(agent)))
    secondary = sorted((agent for agent in counts if agent != lane), key=_catalog_rank)
    return lane, secondary


def context_graph(
    conn: sqlite3.Connection,
    context_id: int,
    commits: Optional[CommitIndex] = None,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """ProjectGraph (§10.1) de un contexto: el contexto, sus pasos y los commits citados.

    Sin texto de notas, títulos de commits ni contenido de runs (§21.4).
    """
    context = conn.execute(
        "SELECT id, project, status FROM contexts WHERE id = ?", (context_id,)
    ).fetchone()
    if context is None:
        return None
    commits = commits or CommitIndex.from_db(conn)
    steps = conn.execute(
        "SELECT id, order_idx, status, provider, notes FROM steps "
        "WHERE context_id = ? ORDER BY order_idx, id",
        (context_id,),
    ).fetchall()
    step_ids = [row[0] for row in steps]

    alignments: dict[int, list[tuple[str, int]]] = {step_id: [] for step_id in step_ids}
    for step_id, agent, confirmed in conn.execute(
        "SELECT step_id, agent, confirmed FROM alignments WHERE context_id = ?", (context_id,)
    ).fetchall():
        if step_id in alignments:
            alignments[step_id].append((normalize_agent(agent), confirmed))

    run_totals: dict[int, tuple[int, float]] = {}
    if step_ids:
        placeholders = ",".join("?" for _ in step_ids)
        for step_id, count, cost in conn.execute(
            f"SELECT step_id, COUNT(*), COALESCE(SUM(cost_usd), 0) FROM runs "
            f"WHERE step_id IN ({placeholders}) GROUP BY step_id",
            step_ids,
        ).fetchall():
            run_totals[step_id] = (count, round(float(cost or 0), 6))

    nodes = [
        {
            "id": f"context:{context[0]}",
            "kind": "context",
            "label": f"Contexto {context[0]}",
            "state": context[2] or "",
        }
    ]
    edges = []
    commit_nodes: dict[str, dict] = {}
    for position, (step_id, order_idx, status, provider, notes) in enumerate(steps, start=1):
        step_alignments = alignments.get(step_id, [])
        lane, secondary = _step_lanes(provider, [agent for agent, _ in step_alignments])
        runs, cost = run_totals.get(step_id, (0, 0.0))
        refs = step_references(notes, commits)
        node_id = f"step:{step_id}"
        nodes.append(
            {
                "id": node_id,
                "kind": "step",
                "label": f"Paso {position}",
                "state": status or "",
                "attrs": {
                    "idx": position,
                    "order_idx": order_idx,
                    "lane": lane,
                    "secondary": secondary,
                    "alignments": len(step_alignments),
                    "deviations": sum(1 for _, confirmed in step_alignments if not confirmed),
                    "runs": runs,
                    "cost_usd": cost,
                    "prs": refs["prs"],
                    "unverified_shas": len(refs["unverified_shas"]),
                    "mentions_tests": refs["mentions_tests"],
                },
            }
        )
        edges.append(
            {
                "source": f"context:{context[0]}",
                "target": node_id,
                "relation_type": "contains",
                "origin": "system",
                "confidence": 1.0,
                "evidence_ref": "steps.context_id",
            }
        )
        for sha in refs["verified_commits"]:
            commit_id = f"commit:{sha}"
            commit_nodes.setdefault(sha, {"id": commit_id, "kind": "commit", "label": sha[:7]})
            edges.append(
                {
                    "source": node_id,
                    "target": commit_id,
                    "relation_type": "cites",
                    "origin": "verified_reference",
                    "confidence": 1.0,
                    "evidence_ref": "steps.notes",
                }
            )
    nodes.extend(commit_nodes[sha] for sha in sorted(commit_nodes))
    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "project": context[1] or "",
            "context_id": context[0],
            "generated_at": _now_utc(now),
        },
    }


def _window_clause(column: str, since: Optional[str], until: Optional[str]) -> tuple[str, list]:
    clauses = []
    params: list = []
    if since:
        clauses.append(f"julianday({column}) >= julianday(?)")
        params.append(since)
    if until:
        clauses.append(f"julianday({column}) < julianday(?)")
        params.append(until)
    return "".join(f" AND {clause}" for clause in clauses), params


def activity(
    conn: sqlite3.Connection,
    project: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 200,
    now: Optional[datetime] = None,
) -> dict:
    """Activity del proyecto (§10.4): hitos de la base ordenados por instante UTC.

    `since` es inclusivo y `until` exclusivo. Los eventos con timestamp que no se
    puede parsear se descartan y se cuentan en `metadata.skipped_invalid_ts`.
    """
    since_utc = to_utc(since) if since else None
    until_utc = to_utc(until) if until else None
    if since and since_utc is None:
        raise ValueError(f"since inválido: {since!r}")
    if until and until_utc is None:
        raise ValueError(f"until inválido: {until!r}")
    limit = max(1, int(limit))
    raw: list[dict] = []

    clause, params = _window_clause("ts", since_utc, until_utc)
    for run_id, ts, provider, model, status, step_id in conn.execute(
        "SELECT id, ts, provider, model, status, step_id FROM runs WHERE project = ?" + clause,
        [project, *params],
    ).fetchall():
        label = "/".join(part for part in (provider, model) if part) or "run"
        raw.append({"kind": "run", "row_id": run_id, "ts": ts, "step_id": step_id,
                    "agent": normalize_agent(provider) if provider else None,
                    "label": label, "state": status or ""})

    clause, params = _window_clause("ts", since_utc, until_utc)
    for row_id, ts, phase, decision, reason_code in conn.execute(
        "SELECT id, ts, phase, decision, reason_code FROM egress_decisions WHERE project = ?"
        + clause,
        [project, *params],
    ).fetchall():
        raw.append({"kind": "egress_decision", "row_id": row_id, "ts": ts, "step_id": None,
                    "agent": None, "label": " ".join(p for p in (phase, reason_code) if p) or "egress",
                    "state": decision or ""})

    clause, params = _window_clause("a.ts", since_utc, until_utc)
    for row_id, ts, step_id, context_id, agent, confirmed in conn.execute(
        "SELECT a.id, a.ts, a.step_id, a.context_id, a.agent, a.confirmed FROM alignments a "
        "JOIN contexts c ON c.id = a.context_id WHERE c.project = ?" + clause,
        [project, *params],
    ).fetchall():
        raw.append({"kind": "alignment", "row_id": row_id, "ts": ts, "step_id": step_id,
                    "context_id": context_id, "agent": normalize_agent(agent),
                    "label": "alineamiento" if confirmed else "desviación",
                    "state": "confirmed" if confirmed else "deviation"})

    clause, params = _window_clause("t.ts", since_utc, until_utc)
    for row_id, ts, step_id, context_id, tool_name, status in conn.execute(
        "SELECT t.id, t.ts, t.step_id, t.context_id, t.tool_name, t.status FROM tool_calls t "
        "JOIN contexts c ON c.id = t.context_id WHERE c.project = ?" + clause,
        [project, *params],
    ).fetchall():
        raw.append({"kind": "tool_call", "row_id": row_id, "ts": ts, "step_id": step_id,
                    "context_id": context_id, "agent": None,
                    "label": (tool_name or "tool call")[:80], "state": status or ""})

    clause, params = _window_clause("ts", since_utc, until_utc)
    for row_id, ts, surface, tool_name, status in conn.execute(
        "SELECT id, ts, client_surface, tool_name, status FROM mcp_invocations "
        "WHERE project = ? AND COALESCE(tool_category, '') <> 'read'" + clause,
        [project, *params],
    ).fetchall():
        raw.append({"kind": "mcp_invocation", "row_id": row_id, "ts": ts, "step_id": None,
                    "agent": normalize_agent(surface), "label": (tool_name or "mcp")[:80],
                    "state": status or ""})

    for column, kind in (("started_at", "step_started"), ("completed_at", "step_completed")):
        clause, params = _window_clause(f"s.{column}", since_utc, until_utc)
        for step_id, ts, context_id, order_idx, provider in conn.execute(
            f"SELECT s.id, s.{column}, s.context_id, s.order_idx, s.provider FROM steps s "
            f"JOIN contexts c ON c.id = s.context_id WHERE c.project = ? AND s.{column} IS NOT NULL"
            + clause,
            [project, *params],
        ).fetchall():
            raw.append({"kind": kind, "row_id": step_id, "ts": ts, "step_id": step_id,
                        "context_id": context_id, "agent": normalize_agent(provider),
                        "label": f"paso {order_idx}", "state": kind.split("_", 1)[1]})

    since_dt = parse_instant(since_utc) if since_utc else None
    until_dt = parse_instant(until_utc) if until_utc else None
    events = []
    skipped = 0
    for item in raw:
        instant = parse_instant(item["ts"])
        if instant is None:
            skipped += 1
            continue
        if since_dt is not None and instant < since_dt:
            continue
        if until_dt is not None and instant >= until_dt:
            continue
        events.append((instant, item))

    events.sort(
        key=lambda pair: (
            pair[0],
            -ACTIVITY_KIND_ORDER.index(pair[1]["kind"]),
            pair[1]["row_id"],
        ),
        reverse=True,
    )
    truncated = len(events) > limit
    result = []
    for instant, item in events[:limit]:
        step_id = item.get("step_id")
        context_id = item.get("context_id")
        result.append(
            {
                "id": f"{item['kind']}:{item['row_id']}",
                "kind": item["kind"],
                "ts": instant.isoformat(),
                "ref": f"step:{step_id}" if step_id is not None else None,
                "context_id": context_id,
                "agent": item["agent"],
                "label": item["label"],
                "state": item["state"],
            }
        )
    return {
        "project": project,
        "events": result,
        "metadata": {
            "generated_at": _now_utc(now),
            "since": since_utc,
            "until": until_utc,
            "limit": limit,
            "truncated": truncated,
            "skipped_invalid_ts": skipped,
        },
    }
