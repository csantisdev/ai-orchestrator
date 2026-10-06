#!/usr/bin/env python
"""Sesiones de medición de Labs (spec §21.6, §22.5 y §23.8): Mapa y Constelación.

Cada función de Labs se queda solo si, en al menos 10 sesiones sobre datos reales, la mediana de
tiempo baja al menos 20 % frente a la alternativa (Contextos + Trace) sin bajar el acierto. Este
script arma las tareas con los datos locales, alterna la condición (grafo o lista), abre la URL,
cronometra y corrige la respuesta. Todo es local y sin telemetría (§12): los resultados van a
`~/.ai-orchestrator/labs-sessions.jsonl` (sin el texto de las respuestas) y `summary` da la línea
para registrar como evidencia en el tracking.

Uso:
    python scripts/labs_sessions.py items --feature map --project mi-proyecto
    python scripts/labs_sessions.py run --feature map --project mi-proyecto
    python scripts/labs_sessions.py summary --feature map
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.projections import AGENT_CATALOG, CommitIndex, context_map, project_constellation  # noqa: E402

FEATURES = ("map", "constellation")
GRAPH, LIST = "grafo", "lista"
MIN_SESSIONS = 10
MIN_GAIN = 0.20
TRIALS_PER_CONDITION = 1

INSTRUCTIONS = {
    ("map", GRAPH): "Usá la pestaña ◇ Mapa del contexto.",
    ("map", LIST): "Usá solo la lista de pasos y el Trace de cada paso (sin la pestaña Mapa).",
    ("constellation", GRAPH): "Usá la pestaña ◇ Grafo · Labs de Contextos.",
    ("constellation", LIST): "Usá solo la lista de contextos y el Trace de sus pasos (sin el Grafo).",
}


def results_path() -> Path:
    from orchestrator import paths

    return paths.HOME_DIR / "labs-sessions.jsonl"


# ── Tareas ──────────────────────────────────────────────────────────────────────────────


def map_items(conn, project: str, commits: Optional[CommitIndex] = None) -> list[dict]:
    """Tareas del Mapa (§21.6) sobre los contextos elegibles del proyecto.

    - commit: "¿qué pasos citan el commit X?" (commits citados por dos o más pasos);
    - agent: "¿qué agente hizo el paso N y quién más participó?" (pasos con participantes).
    """
    commits = commits if commits is not None else CommitIndex.from_db(conn)
    items = []
    for (context_id,) in conn.execute("SELECT id FROM contexts WHERE project = ? ORDER BY id", (project,)).fetchall():
        dto = context_map(conn, context_id, commits)
        if not dto or not dto["map"]["eligible"]:
            continue
        steps = {node["id"]: node for node in dto["nodes"] if node["kind"] == "step"}
        citing: dict[str, set[int]] = {}
        for edge in dto["edges"]:
            if edge["relation_type"] == "cites" and edge["source"] in steps:
                citing.setdefault(edge["target"], set()).add(steps[edge["source"]]["attrs"]["idx"])
        for commit in sorted(dto["map"]["shared"]):
            if len(citing.get(commit, ())) >= 2:
                sha = commit.split(":", 1)[1]
                items.append({"feature": "map", "task": "commit", "context": context_id, "key": f"{context_id}:{sha}",
                              "question": f"Contexto #{context_id}: ¿qué pasos citan el commit {sha[:7]}? (números de paso)",
                              "expected": {"steps": sorted(citing[commit])}})
        for node in steps.values():
            if node["attrs"]["secondary"]:
                idx = node["attrs"]["idx"]
                items.append({"feature": "map", "task": "agent", "context": context_id, "key": f"{context_id}:{idx}",
                              "question": f"Contexto #{context_id}: ¿qué agente hizo el Paso {idx} y quién más participó?",
                              "expected": {"lane": node["attrs"]["lane"], "agents": sorted({node["attrs"]["lane"], *node["attrs"]["secondary"]})}})
    return items


def constellation_items(conn, project: str, commits: Optional[CommitIndex] = None) -> list[dict]:
    """Tarea de la Constelación (§22.5): "¿qué contextos comparten evidencia con este?"."""
    dto = project_constellation(conn, project, commits)
    neighbors: dict[str, set[str]] = {}
    for bridge in dto["constellation"]["bridges"]:
        neighbors.setdefault(bridge["source"], set()).add(bridge["target"])
        if not bridge["portal"]:
            neighbors.setdefault(bridge["target"], set()).add(bridge["source"])
    items = []
    for node_id in sorted(neighbors, key=lambda value: int(value.split(":")[1])):
        context_id = int(node_id.split(":")[1])
        found = neighbors[node_id]
        items.append({"feature": "constellation", "task": "shared", "context": context_id, "key": str(context_id),
                      "question": f"¿Qué contextos (o proyectos) comparten commits con el contexto #{context_id}?",
                      "expected": {"contexts": sorted(int(item.split(":")[1]) for item in found if item.startswith("context:")),
                                   "portals": sorted(item.split(":", 1)[1] for item in found if item.startswith("portal:"))}})
    return items


def items_for(feature: str, conn, project: str) -> list[dict]:
    return map_items(conn, project) if feature == "map" else constellation_items(conn, project)


# ── Respuestas ──────────────────────────────────────────────────────────────────────────


def _numbers(text: str) -> set[int]:
    return {int(value) for value in re.findall(r"\d+", text)}


def _agents(text: str) -> list[str]:
    words = re.findall(r"[a-záéíóúñ]+", text.lower())
    return [word for word in words if word in AGENT_CATALOG]


def check_answer(item: dict, text: str) -> bool:
    """Acierto: el conjunto exacto pedido (ni de menos ni de más)."""
    expected = item["expected"]
    if item["task"] == "commit":
        return _numbers(text) == set(expected["steps"])
    if item["task"] == "agent":
        named = _agents(text)
        return bool(named) and named[0] == expected["lane"] and set(named) == set(expected["agents"])
    lowered = text.lower()
    portals_ok = all(alias.lower() in lowered for alias in expected["portals"])
    return portals_ok and _numbers(text) == set(expected["contexts"])


# ── Sesión ──────────────────────────────────────────────────────────────────────────────


def plan_session(items: list[dict], session: int, rng: random.Random) -> list[tuple[dict, str]]:
    """Ensayos de una sesión: por cada tipo de tarea, uno por condición con ítems distintos.

    El orden de las condiciones se alterna por sesión (par: grafo primero) para compensar el
    aprendizaje dentro de la sesión.
    """
    order = (GRAPH, LIST) if session % 2 == 0 else (LIST, GRAPH)
    trials = []
    for task in sorted({item["task"] for item in items}):
        pool = [item for item in items if item["task"] == task]
        if len(pool) < 2 * TRIALS_PER_CONDITION:
            continue
        chosen = rng.sample(pool, 2 * TRIALS_PER_CONDITION)
        for index, condition in enumerate(order):
            for item in chosen[index * TRIALS_PER_CONDITION:(index + 1) * TRIALS_PER_CONDITION]:
                trials.append((item, condition))
    return trials


def url_for(base: str, project: str, item: dict, condition: str) -> str:
    query = {"project": project, "view": "trabajo"}
    if item["feature"] == "map":
        query["ctx"] = item["context"]
        if condition == GRAPH:
            query["as"] = "map"
    else:
        query["tab"] = "contextos"
        if condition == GRAPH:
            query["as"] = "constellation"
    return base.rstrip("/") + "/?" + urllib.parse.urlencode(query)


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def next_session(records: list[dict], feature: str) -> int:
    return max((record["session"] for record in records if record["feature"] == feature), default=0) + 1


def summarize(records: list[dict], feature: str) -> dict:
    """Mediana de tiempo y acierto por condición, y el veredicto del criterio de permanencia."""
    own = [record for record in records if record["feature"] == feature]
    result = {"feature": feature, "sessions": len({record["session"] for record in own})}
    for condition in (GRAPH, LIST):
        trials = [record for record in own if record["condition"] == condition]
        result[condition] = {
            "trials": len(trials),
            "median_s": round(statistics.median(record["seconds"] for record in trials), 1) if trials else None,
            "accuracy": round(sum(record["correct"] for record in trials) / len(trials), 2) if trials else None,
        }
    graph, listing = result[GRAPH], result[LIST]
    if graph["median_s"] is None or listing["median_s"] is None or not listing["median_s"]:
        result["gain"] = None
        result["verdict"] = "sin datos suficientes"
        return result
    result["gain"] = round(1 - graph["median_s"] / listing["median_s"], 2)
    if result["sessions"] < MIN_SESSIONS:
        result["verdict"] = f"faltan sesiones ({result['sessions']} de {MIN_SESSIONS})"
    elif result["gain"] >= MIN_GAIN and graph["accuracy"] >= listing["accuracy"]:
        result["verdict"] = "se mantiene"
    else:
        result["verdict"] = "no cumple: retirar o dejar solo como enlace"
    return result


def tracking_line(summary: dict) -> str:
    graph, listing = summary[GRAPH], summary[LIST]
    gain = "—" if summary["gain"] is None else f"{round(summary['gain'] * 100)} %"
    return (f"Labs {summary['feature']}: {summary['sessions']} sesiones; mediana grafo {graph['median_s']} s "
            f"vs lista {listing['median_s']} s (mejora {gain}); acierto {graph['accuracy']} vs {listing['accuracy']}. "
            f"Veredicto: {summary['verdict']}.")


def run_session(feature: str, project: str, base: str, open_browser: bool, seed: Optional[int]) -> int:
    from orchestrator.db import _conn

    items = items_for(feature, _conn(), project)
    path = results_path()
    session = next_session(load_records(path), feature)
    trials = plan_session(items, session, random.Random(seed))
    if not trials:
        print("No hay tareas suficientes para este proyecto (hacen falta contextos elegibles).")
        return 1
    print(f"Sesión {session} de {feature} · {len(trials)} tareas. Respondé con números de paso o de contexto y nombres de agente.")
    for number, (item, condition) in enumerate(trials, start=1):
        print(f"\n[{number}/{len(trials)}] {INSTRUCTIONS[(feature, condition)]}")
        print(item["question"])
        url = url_for(base, project, item, condition)
        input(f"Enter para abrir {url} y empezar a cronometrar… ")
        if open_browser:
            webbrowser.open(url)
        else:
            print(url)
        start = time.monotonic()
        answer = input("Respuesta: ")
        seconds = round(time.monotonic() - start, 1)
        correct = check_answer(item, answer)
        print(f"{'Correcta' if correct else 'Incorrecta'} · {seconds} s")
        record = {"ts": datetime.now(timezone.utc).isoformat(), "feature": feature, "project": project,
                  "session": session, "task": item["task"], "condition": condition, "item": item["key"],
                  "seconds": seconds, "correct": correct}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("\n" + tracking_line(summarize(load_records(path), feature)))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("items", "run"):
        command = sub.add_parser(name)
        command.add_argument("--feature", choices=FEATURES, required=True)
        command.add_argument("--project", required=True)
        if name == "run":
            command.add_argument("--base", default="http://localhost:8080")
            command.add_argument("--no-browser", action="store_true")
            command.add_argument("--seed", type=int)
    summary = sub.add_parser("summary")
    summary.add_argument("--feature", choices=FEATURES, required=True)
    args = parser.parse_args(argv)

    if args.command == "items":
        from orchestrator.db import _conn

        items = items_for(args.feature, _conn(), args.project)
        tasks = {}
        for item in items:
            tasks[item["task"]] = tasks.get(item["task"], 0) + 1
        print(f"{len(items)} tareas posibles: " + ", ".join(f"{task} {count}" for task, count in sorted(tasks.items())))
        return 0
    if args.command == "run":
        return run_session(args.feature, args.project, args.base, not args.no_browser, args.seed)
    print(tracking_line(summarize(load_records(results_path()), args.feature)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
