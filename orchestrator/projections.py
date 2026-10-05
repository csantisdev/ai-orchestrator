"""Proyecciones puras de la base hacia los DTO del dashboard (spec §10, §20, §21).

Leen SQLite y devuelven estructuras serializables; no escriben ni modifican los
datos de origen. La normalización de agentes y timestamps vive solo acá (§20.4).
Los DTO no llevan texto libre: solo identificadores, conteos y tokens validados.
"""

from __future__ import annotations

import bisect
import math
import re
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER

AGENT_ALIASES = {
    "claude": ("claude", "claude-code", "claude_code"),
    "codex": ("codex", "codex_cli"),
    "copilot": ("copilot", "copilot-cli", "github-copilot"),
    "otros": ("deepseek", "openai", "gemini"),
}
AGENT_CATALOG = tuple(AGENT_ALIASES)
NO_AGENT = "sin agente"
_ALIAS_TO_AGENT = {alias: agent for agent, aliases in AGENT_ALIASES.items() for alias in aliases}

_SHA_CANDIDATE = re.compile(r"(?<![0-9A-Za-z])(?:[0-9A-Fa-f]{64}|[0-9A-Fa-f]{7,40})(?![0-9A-Za-z])")
_FULL_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_PR_REFERENCE = re.compile(r"\bPR\s*#?(\d{1,9})\b", re.I)
_TEST_MENTION = re.compile(r"\b(?:pytest|tests?|passed)\b", re.I)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")
_GIT_SESSION_PREFIX = "git::"
OTHER = "otro"

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
    """Agente del catálogo de §21.1 (alias exactos); lo demás cae en `sin agente`."""
    if not isinstance(value, str):
        return NO_AGENT
    return _ALIAS_TO_AGENT.get(value.strip().lower(), NO_AGENT)


def _token(value: object) -> Optional[str]:
    """Identificador corto en minúsculas, o None si es texto libre."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if _TOKEN.fullmatch(text) else None


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
    """SHAs completos de los commits importados (`runs.session_id = git::<alias>::<sha>`).

    Solo se aceptan SHAs hexadecimales completos de 40 o 64 caracteres.
    """

    def __init__(self, shas: Iterable[str]):
        valid = set()
        for sha in shas:
            if isinstance(sha, str) and _FULL_SHA.fullmatch(sha.strip().lower()):
                valid.add(sha.strip().lower())
        self._shas = sorted(valid)

    def __len__(self) -> int:
        return len(self._shas)

    @classmethod
    def from_db(cls, conn: sqlite3.Connection) -> "CommitIndex":
        rows = conn.execute(
            "SELECT project, session_id FROM runs WHERE provider = ? AND session_id LIKE ?",
            (GIT_PROVIDER, _GIT_SESSION_PREFIX + "%"),
        ).fetchall()
        shas = []
        for project, session_id in rows:
            if not project:
                continue
            prefix = f"{_GIT_SESSION_PREFIX}{project}::"
            if session_id.startswith(prefix):
                shas.append(session_id[len(prefix):])
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
    """Referencias de un paso separadas en SHAs verificados y candidatos sin verificar."""
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


def _alignment_sort_key(ts: object, row_id: int) -> tuple:
    instant = parse_instant(ts)
    return (instant is None, instant or datetime.min.replace(tzinfo=timezone.utc), row_id)


def step_lanes(provider: object, alignments: list[tuple[object, int, str]]) -> tuple[str, list[str]]:
    """Carril principal y agentes secundarios de un paso (regla de §21.1).

    `alignments` son tuplas `(ts, id, agente_normalizado)`. Principal: `provider` si está
    en el catálogo; si no, el agente con más alineamientos y, en empate, el del primer
    alineamiento por instante y luego id; sin alineamientos, `sin agente`.
    """
    ordered = sorted(alignments, key=lambda item: _alignment_sort_key(item[0], item[1]))
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for position, (_, _, agent) in enumerate(ordered):
        if agent == NO_AGENT:
            continue
        counts[agent] = counts.get(agent, 0) + 1
        first_seen.setdefault(agent, position)
    lane = normalize_agent(provider)
    if lane == NO_AGENT and counts:
        lane = min(counts, key=lambda agent: (-counts[agent], first_seen[agent]))
    secondary = [agent for agent in AGENT_CATALOG if agent in counts and agent != lane]
    return lane, secondary


def context_graph(
    conn: sqlite3.Connection,
    context_id: int,
    commits: Optional[CommitIndex] = None,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """ProjectGraph (§10.1) de un contexto: el contexto, sus pasos y los commits citados.

    Sin texto de notas, títulos de commits ni contenido de runs (§21.4). Las
    representaciones (mapa, constelación) agregan su extensión con su propio esquema.
    """
    context = conn.execute(
        "SELECT id, project, status FROM contexts WHERE id = ?", (context_id,)
    ).fetchone()
    if context is None:
        return None
    commits = commits if commits is not None else CommitIndex.from_db(conn)
    steps = conn.execute(
        "SELECT id, order_idx, status, provider, notes FROM steps "
        "WHERE context_id = ? ORDER BY order_idx, id",
        (context_id,),
    ).fetchall()

    alignments: dict[int, list[tuple[object, int, str]]] = {}
    confirmations: dict[int, list[int]] = {}
    for row_id, step_id, ts, agent, confirmed in conn.execute(
        # Solo filas coherentes: un alineamiento o run que apunta al paso desde otro
        # contexto u otro proyecto no cuenta para su carril ni para sus totales.
        "SELECT a.id, a.step_id, a.ts, a.agent, a.confirmed FROM alignments a "
        "JOIN steps s ON s.id = a.step_id WHERE s.context_id = ? AND a.context_id = ?",
        (context_id, context_id),
    ).fetchall():
        alignments.setdefault(step_id, []).append((ts, row_id, normalize_agent(agent)))
        confirmations.setdefault(step_id, []).append(confirmed)

    run_counts: dict[int, int] = {}
    run_costs: dict[int, float] = {}
    for step_id, cost in conn.execute(
        "SELECT r.step_id, r.cost_usd FROM runs r "
        "JOIN steps s ON s.id = r.step_id WHERE s.context_id = ? AND r.project = ?",
        (context_id, context[1]),
    ).fetchall():
        run_counts[step_id] = run_counts.get(step_id, 0) + 1
        if isinstance(cost, (int, float)) and math.isfinite(cost) and cost >= 0:
            run_costs[step_id] = run_costs.get(step_id, 0.0) + float(cost)
    run_totals: dict[int, tuple[int, Optional[float]]] = {}
    for step_id, count in run_counts.items():
        total = run_costs.get(step_id, 0.0)
        run_totals[step_id] = (count, round(total, 6) if math.isfinite(total) else None)

    context_node = f"context:{context[0]}"
    nodes = [
        {
            "id": context_node,
            "kind": "context",
            "label": f"Contexto {context[0]}",
            "state": _token(context[2]) or OTHER,
        }
    ]
    edges = []
    commit_nodes: dict[str, dict] = {}
    for position, (step_id, order_idx, status, provider, notes) in enumerate(steps, start=1):
        lane, secondary = step_lanes(provider, alignments.get(step_id, []))
        runs, cost = run_totals.get(step_id, (0, 0.0))
        refs = step_references(notes, commits)
        node_id = f"step:{step_id}"
        nodes.append(
            {
                "id": node_id,
                "kind": "step",
                "label": f"Paso {position}",
                "state": _token(status) or OTHER,
                "attrs": {
                    "idx": position,
                    "order_idx": order_idx if isinstance(order_idx, int) else None,
                    "lane": lane,
                    "secondary": secondary,
                    "alignments": len(confirmations.get(step_id, [])),
                    "deviations": sum(1 for confirmed in confirmations.get(step_id, []) if not confirmed),
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
                "source": context_node,
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


def _event(kind, row_id, ts, label, state, agent=None, step_id=None, context_id=None) -> dict:
    return {
        "kind": kind,
        "row_id": row_id,
        "ts": ts,
        "label": label,
        "state": _token(state) or OTHER,
        "agent": agent,
        "step_id": step_id,
        "context_id": context_id,
    }


def _joined_tokens(*values: object) -> Optional[str]:
    tokens = [token for token in (_token(value) for value in values) if token]
    return " ".join(tokens) if tokens else None


def _sort_key(instant: datetime, kind: str, row_id: int) -> tuple:
    return (instant, -ACTIVITY_KIND_ORDER.index(kind), row_id)


def _parse_cursor(cursor: str) -> tuple:
    """Clave de orden de un `next_cursor` (`<ts UTC>|<kind>|<id>`); ValueError si es inválido."""
    parts = cursor.split("|")
    instant = parse_instant(parts[0]) if len(parts) == 3 else None
    if instant is None or parts[1] not in ACTIVITY_KIND_ORDER or not parts[2].isdigit():
        raise ValueError(f"cursor inválido: {cursor!r}")
    return _sort_key(instant, parts[1], int(parts[2]))


def activity(
    conn: sqlite3.Connection,
    project: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 200,
    now: Optional[datetime] = None,
    cursor: Optional[str] = None,
) -> dict:
    """Activity del proyecto (§10.4): hitos de la base ordenados por instante UTC.

    `since` es inclusivo y `until` exclusivo. La ventana se aplica en Python, con el
    mismo parser que normaliza los timestamps, así que un valor que no se puede
    parsear siempre se descarta y se cuenta en `metadata.skipped_invalid_ts`.
    Orden: instante descendente; en empate, `ACTIVITY_KIND_ORDER` y luego id descendente.
    Paginación sin pérdidas: si el resultado se trunca, `metadata.next_cursor` lleva la
    clave de orden completa del último evento y `cursor=` devuelve los siguientes, aunque
    compartan instante. Los labels y estados son tokens validados.

    Costo: lee toda la historia del proyecto en cada llamada (a escala actual, cientos de
    ms para todos los proyectos). Acotarlo en SQL queda para D4 (§19.4 O4–O5).
    """
    since_dt = parse_instant(since) if since else None
    until_dt = parse_instant(until) if until else None
    if since and since_dt is None:
        raise ValueError(f"since inválido: {since!r}")
    if until and until_dt is None:
        raise ValueError(f"until inválido: {until!r}")
    cursor_key = _parse_cursor(cursor) if cursor else None
    limit = max(1, int(limit))
    raw: list[dict] = []

    for run_id, ts, provider, model, status, step_id in conn.execute(
        "SELECT id, ts, provider, model, status, step_id FROM runs WHERE project = ?", (project,)
    ).fetchall():
        provider_token = _token(provider)
        model_token = None if provider_token == GIT_PROVIDER else _token(model)
        label = "/".join(t for t in (provider_token, model_token) if t) or "run"
        raw.append(_event("run", run_id, ts, label, status, normalize_agent(provider), step_id))

    for row_id, ts, provider, phase, decision, reason_code in conn.execute(
        "SELECT id, ts, provider, phase, decision, reason_code FROM egress_decisions WHERE project = ?",
        (project,),
    ).fetchall():
        raw.append(_event("egress_decision", row_id, ts, _joined_tokens(phase, reason_code) or "egress",
                          decision, normalize_agent(provider)))

    step_alignments: dict[int, list[tuple[object, int, str]]] = {}
    for row_id, ts, step_id, context_id, agent, confirmed in conn.execute(
        "SELECT a.id, a.ts, a.step_id, a.context_id, a.agent, a.confirmed FROM alignments a "
        "JOIN contexts c ON c.id = a.context_id WHERE c.project = ?",
        (project,),
    ).fetchall():
        state = "confirmed" if confirmed else "deviation"
        agent_id = normalize_agent(agent)
        step_alignments.setdefault(step_id, []).append((ts, row_id, agent_id))
        raw.append(_event("alignment", row_id, ts, "alignment", state, agent_id,
                          step_id, context_id))

    for row_id, ts, step_id, context_id, tool_name, status in conn.execute(
        "SELECT t.id, t.ts, t.step_id, t.context_id, t.tool_name, t.status FROM tool_calls t "
        "JOIN contexts c ON c.id = t.context_id WHERE c.project = ?",
        (project,),
    ).fetchall():
        raw.append(_event("tool_call", row_id, ts, _token(tool_name) or "tool_call", status, None,
                          step_id, context_id))

    for row_id, ts, surface, tool_name, status in conn.execute(
        "SELECT id, ts, client_surface, tool_name, status FROM mcp_invocations "
        "WHERE project = ? AND COALESCE(tool_category, '') <> 'read'",
        (project,),
    ).fetchall():
        raw.append(_event("mcp_invocation", row_id, ts, _token(tool_name) or "mcp", status,
                          normalize_agent(surface)))

    for column, kind, state in (("started_at", "step_started", "started"),
                                ("completed_at", "step_completed", "completed")):
        for step_id, ts, context_id, order_idx, provider in conn.execute(
            f"SELECT s.id, s.{column}, s.context_id, s.order_idx, s.provider FROM steps s "
            f"JOIN contexts c ON c.id = s.context_id WHERE c.project = ? AND s.{column} IS NOT NULL",
            (project,),
        ).fetchall():
            label = f"paso {order_idx}" if type(order_idx) is int and order_idx >= 0 else "paso"
            lane, _ = step_lanes(provider, step_alignments.get(step_id, []))
            raw.append(_event(kind, step_id, ts, label, state, lane, step_id, context_id))

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

    events.sort(key=lambda pair: _sort_key(pair[0], pair[1]["kind"], pair[1]["row_id"]), reverse=True)
    if cursor_key is not None:
        events = [pair for pair in events
                  if _sort_key(pair[0], pair[1]["kind"], pair[1]["row_id"]) < cursor_key]
    truncated = len(events) > limit
    next_cursor = None
    if truncated:
        last_instant, last_item = events[limit - 1]
        next_cursor = f"{last_instant.isoformat()}|{last_item['kind']}|{last_item['row_id']}"
    result = []
    for instant, item in events[:limit]:
        step_id = item["step_id"]
        result.append(
            {
                "id": f"{item['kind']}:{item['row_id']}",
                "kind": item["kind"],
                "ts": instant.isoformat(),
                "ref": f"step:{step_id}" if isinstance(step_id, int) else None,
                "context_id": item["context_id"],
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
            "since": since_dt.isoformat() if since_dt else None,
            "until": until_dt.isoformat() if until_dt else None,
            "next_cursor": next_cursor,
            "limit": limit,
            "truncated": truncated,
            "skipped_invalid_ts": skipped,
        },
    }


MAP_MAX_STEPS = 30
MAP_MAX_COMMITS = 20
MAP_MAX_EDGES = 60


def _map_groups(steps: list[dict], shared_citers: set[str], max_steps: int) -> list[dict]:
    """Rangos maximales de pasos consecutivos completados, sin desvíos ni commits compartidos.

    Solo cuando el contexto supera `max_steps` pasos (§21.3, presupuesto visual); un rango de un
    solo paso no se agrupa.
    """
    if len(steps) <= max_steps:
        return []

    def groupable(node: dict) -> bool:
        attrs = node["attrs"]
        return node["state"] == "completed" and attrs["deviations"] == 0 and node["id"] not in shared_citers

    groups: list[dict] = []
    run: list[dict] = []

    def close() -> None:
        if len(run) >= 2:
            lanes: dict[str, int] = {}
            for node in run:
                lanes[node["attrs"]["lane"]] = lanes.get(node["attrs"]["lane"], 0) + 1
            order = {agent: position for position, agent in enumerate((*AGENT_CATALOG, NO_AGENT))}
            lane = min(lanes, key=lambda agent: (-lanes[agent], order.get(agent, len(order))))
            first, last = run[0]["attrs"]["idx"], run[-1]["attrs"]["idx"]
            groups.append({
                "id": f"group:{first}-{last}",
                "from_idx": first,
                "to_idx": last,
                "count": len(run),
                "members": [node["id"] for node in run],
                "lane": lane,
                "lanes": dict(sorted(lanes.items(), key=lambda item: order.get(item[0], len(order)))),
            })
        run.clear()

    for node in steps:
        if groupable(node):
            run.append(node)
        else:
            close()
    close()
    return groups


def context_map(
    conn: sqlite3.Connection,
    context_id: int,
    commits: Optional[CommitIndex] = None,
    now: Optional[datetime] = None,
    *,
    max_steps: int = MAP_MAX_STEPS,
    max_commits: int = MAP_MAX_COMMITS,
    max_edges: int = MAP_MAX_EDGES,
) -> Optional[dict]:
    """ProjectGraph del contexto con la extensión `map` (spec §21.3, §21.4).

    Los nodos y aristas conservan el formato del ProjectGraph y van completos (todos los
    commits verificados y todas las citas). Lo propio del mapa va en `map`: carriles,
    colocación de commits, commits compartidos, grupos, elegibilidad y los topes. Los topes
    de commits y aristas se deciden en el cliente sobre la ventana visible de columnas, como
    pide §21.3 ("ya dentro de la ventana de 30 columnas"); acá solo viajan sus valores.
    Disposición determinista: x = orden del paso, y = carril del agente principal, commits en
    una franja inferior bajo el primer paso que los cita, apilados por SHA.
    """
    graph = context_graph(conn, context_id, commits, now)
    if graph is None:
        return None
    steps = [node for node in graph["nodes"] if node["kind"] == "step"]
    column = {node["id"]: node["attrs"]["idx"] for node in steps}
    citers: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        if edge["relation_type"] != "cites":
            continue
        bucket = citers.setdefault(edge["target"], [])
        if edge["source"] not in bucket:
            bucket.append(edge["source"])
    for bucket in citers.values():
        bucket.sort(key=lambda step: column[step])
    shared = {commit for commit, citing in citers.items() if len(citing) >= 2}
    shared_citers = {step for commit in shared for step in citers[commit]}

    present = {node["attrs"]["lane"] for node in steps}
    lanes = [agent for agent in AGENT_CATALOG if agent in present]
    if NO_AGENT in present:
        lanes.append(NO_AGENT)
    eligible = len([lane for lane in lanes if lane != NO_AGENT]) >= 2 or bool(shared)

    # Colocación global: bajo el primer paso que cita el commit, apilados por SHA. El cliente
    # la recalcula si ese paso queda fuera de la ventana.
    ordered = sorted(citers, key=lambda commit: (column[citers[commit][0]], commit))
    placement: dict[str, dict] = {}
    stacks: dict[int, int] = {}
    for commit in ordered:
        col = column[citers[commit][0]]
        placement[commit] = {"column": col, "stack": stacks.get(col, 0)}
        stacks[col] = stacks.get(col, 0) + 1

    # Aristas en el orden de dibujo de §21.3: commits por colocación y, dentro de cada uno,
    # pasos citantes por orden del plan.
    cites = [
        {"source": step, "target": commit, "relation_type": "cites", "origin": "verified_reference",
         "confidence": 1.0, "evidence_ref": "steps.notes"}
        for commit in ordered for step in citers[commit]
    ]
    single_by_step: dict[str, int] = {}
    for commit, citing in citers.items():
        if commit not in shared:
            single_by_step[citing[0]] = single_by_step.get(citing[0], 0) + 1
    groups = _map_groups(steps, shared_citers, max_steps)
    for group in groups:
        group["single_commits"] = sum(single_by_step.get(member, 0) for member in group["members"])

    contains = [edge for edge in graph["edges"] if edge["relation_type"] == "contains"]
    commit_nodes = {node["id"]: node for node in graph["nodes"] if node["kind"] == "commit"}
    nodes = [node for node in graph["nodes"] if node["kind"] != "commit"] + [commit_nodes[commit] for commit in ordered]
    return {
        "nodes": nodes,
        "edges": contains + cites,
        "metadata": graph["metadata"],
        "map": {
            "lanes": lanes,
            "eligible": eligible,
            "shared": [commit for commit in ordered if commit in shared],
            "placement": placement,
            "groups": groups,
            "max_columns": max_steps,
            "limits": {"commits": max_commits, "edges": max_edges},
        },
    }



CONSTELLATION_LAYOUT_VERSION = "fr-1"
_CONSTELLATION_WIDTH = 1000.0
_CONSTELLATION_HEIGHT = 620.0
_CONSTELLATION_COLUMNS = 10


def _force_layout(ids: list[str], weights: dict[tuple[str, str], int], iterations: int = 240) -> dict[str, tuple[float, float]]:
    """Fruchterman-Reingold determinista: arranque en círculo por orden de id, sin azar.

    Los puentes con más commits acercan más a sus contextos; una gravedad suave al centro
    mantiene juntos los componentes. Misma entrada, mismas posiciones (§22.5).
    """
    if not ids:
        return {}
    width, height = _CONSTELLATION_WIDTH, _CONSTELLATION_HEIGHT
    count = len(ids)
    if count == 1:
        return {ids[0]: (width / 2, height / 2)}
    k = math.sqrt(width * height / count) * 0.6
    pos = {
        node: [width / 2 + math.cos(2 * math.pi * i / count) * width / 3,
               height / 2 + math.sin(2 * math.pi * i / count) * height / 3]
        for i, node in enumerate(ids)
    }
    temperature = width / 8
    cooling = temperature / (iterations + 1)
    for _ in range(iterations):
        disp = {node: [0.0, 0.0] for node in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                distance = math.hypot(dx, dy) or 0.01
                force = k * k / distance
                fx, fy = dx / distance * force, dy / distance * force
                disp[a][0] += fx
                disp[a][1] += fy
                disp[b][0] -= fx
                disp[b][1] -= fy
        for (a, b), weight in weights.items():
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            distance = math.hypot(dx, dy) or 0.01
            force = distance * distance / k * (1 + math.log1p(weight))
            fx, fy = dx / distance * force, dy / distance * force
            disp[a][0] -= fx
            disp[a][1] -= fy
            disp[b][0] += fx
            disp[b][1] += fy
        for node in ids:
            disp[node][0] += (width / 2 - pos[node][0]) * 0.02
            disp[node][1] += (height / 2 - pos[node][1]) * 0.02
            length = math.hypot(*disp[node]) or 0.01
            step = min(length, temperature)
            pos[node][0] += disp[node][0] / length * step
            pos[node][1] += disp[node][1] / length * step
        temperature = max(temperature - cooling, 1.0)
    # Normalizar a la caja de dibujo, con margen para el radio de los soles.
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    margin = 70.0
    span_x = (max(xs) - min(xs)) or 1.0
    span_y = (max(ys) - min(ys)) or 1.0
    return {
        node: (round(margin + (p[0] - min(xs)) / span_x * (width - 2 * margin), 2),
               round(margin + (p[1] - min(ys)) / span_y * (height - 2 * margin), 2))
        for node, p in pos.items()
    }


def _dominant_agent(steps: list[tuple]) -> str:
    """Agente con más pasos del contexto (desempate por catálogo); `sin agente` solo si no hay otro."""
    counts: dict[str, int] = {}
    for _, _, provider in steps:
        agent = normalize_agent(provider)
        if agent != NO_AGENT:
            counts[agent] = counts.get(agent, 0) + 1
    if not counts:
        return NO_AGENT
    return min(counts, key=lambda agent: (-counts[agent], AGENT_CATALOG.index(agent)))


def project_constellation(conn: sqlite3.Connection, project: str, commits: Optional[CommitIndex] = None,
                          now: Optional[datetime] = None) -> dict:
    """Constelación del proyecto (spec §22.4): contextos como soles, pasos como satélites,
    puentes por commits compartidos y portales hacia otros proyectos.

    Las citas se verifican contra todos los commits importados porque los puentes cruzan
    proyectos (§22.1); de otro proyecto solo viajan su alias y la cantidad de commits. Sin
    texto libre: títulos y notas se piden aparte. Posiciones deterministas (`_force_layout`).
    """
    commits = commits if commits is not None else CommitIndex.from_db(conn)
    contexts = conn.execute("SELECT id, status FROM contexts WHERE project = ? ORDER BY id", (project,)).fetchall()
    own_ids = [row[0] for row in contexts]
    steps_by_context: dict[int, list[tuple]] = {context_id: [] for context_id in own_ids}
    deviations: dict[int, int] = {}
    if own_ids:
        marks = ",".join("?" * len(own_ids))
        for step_id, context_id, status, provider in conn.execute(
            f"SELECT id, context_id, status, provider FROM steps WHERE context_id IN ({marks}) ORDER BY order_idx, id",
            own_ids,
        ).fetchall():
            steps_by_context[context_id].append((step_id, status, provider))
        for context_id, count in conn.execute(
            f"SELECT context_id, SUM(confirmed = 0) FROM alignments WHERE context_id IN ({marks}) GROUP BY context_id",
            own_ids,
        ).fetchall():
            deviations[context_id] = count or 0

    # Citas verificadas de todos los contextos (de cualquier proyecto) para encontrar puentes.
    cited_by: dict[str, set[tuple[int, str]]] = {}
    for context_id, context_project, notes in conn.execute(
        "SELECT s.context_id, c.project, s.notes FROM steps s JOIN contexts c ON c.id = s.context_id"
    ).fetchall():
        for sha in step_references(notes, commits)["verified_commits"]:
            cited_by.setdefault(sha, set()).add((context_id, context_project or ""))

    pair_commits: dict[tuple[str, str], list[str]] = {}
    for sha in sorted(cited_by):
        citing = cited_by[sha]
        local = sorted(context_id for context_id, owner in citing if owner == project)
        if not local or len(citing) < 2:
            continue
        others = sorted({owner for _, owner in citing if owner != project})
        for i, a in enumerate(local):
            for b in local[i + 1:]:
                pair_commits.setdefault((f"context:{a}", f"context:{b}"), []).append(sha)
            for alias in others:
                pair_commits.setdefault((f"context:{a}", f"portal:{alias}"), []).append(sha)

    bridges = [
        {"source": a, "target": b, "weight": len(shas), "commits": [f"commit:{sha}" for sha in shas],
         "portal": b.startswith("portal:")}
        for (a, b), shas in sorted(pair_commits.items())
    ]
    connected = {bridge["source"] for bridge in bridges} | {
        bridge["target"] for bridge in bridges if not bridge["portal"]}
    portals = sorted({bridge["target"] for bridge in bridges if bridge["portal"]})

    nodes = []
    edges = []
    for context_id, status in contexts:
        node_id = f"context:{context_id}"
        steps = steps_by_context[context_id]
        nodes.append({
            "id": node_id, "kind": "context", "label": f"Contexto {context_id}", "state": _token(status) or OTHER,
            "attrs": {
                "steps": len(steps),
                "in_progress": sum(1 for _, step_status, _ in steps if step_status == "in_progress"),
                "deviations": deviations.get(context_id, 0),
                "agent": _dominant_agent(steps),
                "connected": node_id in connected,
            },
        })
        for position, (step_id, step_status, provider) in enumerate(steps, start=1):
            nodes.append({"id": f"step:{step_id}", "kind": "step", "label": f"Paso {position}",
                          "state": _token(step_status) or OTHER,
                          "attrs": {"context": node_id, "lane": normalize_agent(provider)}})
            edges.append({"source": node_id, "target": f"step:{step_id}", "relation_type": "contains",
                          "origin": "system", "confidence": 1.0, "evidence_ref": "steps.context_id"})
    for portal in portals:
        nodes.append({"id": portal, "kind": "portal", "label": portal.split(":", 1)[1],
                      "attrs": {"commits": len({sha for b in bridges if b["target"] == portal for sha in b["commits"]})}})

    # Disposición: los conectados por fuerzas; los aislados, en una grilla debajo (§22.4).
    force_ids = sorted(connected | set(portals), key=lambda item: (item.startswith("portal:"), item))
    weights = {(b["source"], b["target"]): b["weight"] for b in bridges}
    positions = {node: {"x": x, "y": y} for node, (x, y) in _force_layout(force_ids, weights).items()}
    isolated = [node["id"] for node in nodes if node["kind"] == "context" and not node["attrs"]["connected"]]
    top = _CONSTELLATION_HEIGHT + 40 if force_ids else 60
    gap = (_CONSTELLATION_WIDTH - 120) / (_CONSTELLATION_COLUMNS - 1)
    for index, node_id in enumerate(isolated):
        positions[node_id] = {"x": round(60 + (index % _CONSTELLATION_COLUMNS) * gap, 2),
                              "y": round(top + (index // _CONSTELLATION_COLUMNS) * 90, 2)}
    rows = (len(isolated) - 1) // _CONSTELLATION_COLUMNS + 1 if isolated else 0
    height = top + rows * 90 if isolated else _CONSTELLATION_HEIGHT
    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {"project": project, "generated_at": _now_utc(now)},
        "constellation": {
            "bridges": bridges,
            "positions": positions,
            "isolated": isolated,
            "size": {"width": _CONSTELLATION_WIDTH, "height": round(height, 2)},
            "layout_version": CONSTELLATION_LAYOUT_VERSION,
        },
    }
