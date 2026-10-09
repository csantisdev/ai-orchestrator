#!/usr/bin/env python
"""Sesiones de medición de Labs (spec §21.6, §22.5 y §23.8): Mapa y Constelación.

Cada función de Labs se queda solo si, en al menos 10 sesiones sobre datos reales, la mediana de
tiempo baja al menos 20 % frente a la alternativa (Contextos + Trace) sin bajar el acierto. Este
script arma las tareas con los datos locales, reparte cada ítem entre las dos condiciones (grafo
o lista) según lo que ya se midió, abre la URL, cronometra y corrige la respuesta.

Todo es local y sin telemetría (§12). Cada sesión completa se agrega al final a
`~/.ai-orchestrator/labs-sessions.jsonl` (una sesión cortada con Ctrl+C no se guarda). Por
ensayo se guarda: fecha, función, alias del proyecto, número de sesión, tarea, condición, modo
de la constelación, un hash local del ítem, segundos y acierto. No se guardan las respuestas, ni
SHAs ni números de contexto. `summary` da la línea para registrar como evidencia en el tracking.

Uso:
    python scripts/labs_sessions.py items --feature map --project mi-proyecto
    python scripts/labs_sessions.py run --feature map --project mi-proyecto
    python scripts/labs_sessions.py summary --feature map
"""

from __future__ import annotations

import argparse
import hashlib
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

from orchestrator.projections import (  # noqa: E402
    NO_AGENT, CommitIndex, context_map, normalize_agent, project_constellation,
)

FEATURES = ("map", "constellation")
GRAPH, LIST = "grafo", "lista"
CONDITIONS = (GRAPH, LIST)
MODES = {"g": "global", "l": "local"}
UNRECORDED = "sin registrar"
MIN_SESSIONS = 10
MIN_GAIN = 0.20

INSTRUCTIONS = {
    ("map", GRAPH): "Usá la pestaña ◇ Mapa del contexto.",
    ("map", LIST): "Usá solo la lista de pasos y el Trace de cada paso (sin la pestaña Mapa).",
    ("constellation", GRAPH): "Usá la pestaña ◇ Grafo · Labs de Contextos (modo Global o Local, el que prefieras).",
    ("constellation", LIST): "Usá solo la lista de contextos y el Trace de sus pasos (sin el Grafo).",
}
FORMATS = {
    "commit": "Formato: solo los números de paso, separados por coma (ej.: 2, 5).",
    "agent": "Formato: primero el agente principal y después los que participaron (ej.: claude, codex).",
    "shared": "Formato: números de contexto y alias de otros proyectos, separados por coma (ej.: 28, 29, otro-proyecto).",
}


def results_path() -> Path:
    from orchestrator import paths

    return paths.HOME_DIR / "labs-sessions.jsonl"


def opaque(key: str) -> str:
    """Identificador local del ítem: permite repartirlo entre condiciones sin guardar el dato."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


# ── Tareas ──────────────────────────────────────────────────────────────────────────────


def map_items(conn, project: str, commits: Optional[CommitIndex] = None) -> list[dict]:
    """Tareas del Mapa (§21.6) sobre los contextos elegibles del proyecto.

    - commit: "¿qué pasos citan el commit X?" (commits citados por dos o más pasos);
    - agent: "¿qué agente hizo el paso N y quién más participó?" (pasos con participantes).

    "Paso N" es el ordinal que muestran la lista y el mapa (`idx`), no `order_idx`.
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
                items.append({"feature": "map", "task": "commit", "context": context_id, "id": opaque(f"commit:{context_id}:{sha}"),
                              "question": f"Contexto #{context_id}: ¿qué pasos citan el commit {sha[:7]}?",
                              "expected": {"steps": sorted(citing[commit])}})
        for node in steps.values():
            if node["attrs"]["secondary"]:
                idx = node["attrs"]["idx"]
                items.append({"feature": "map", "task": "agent", "context": context_id, "id": opaque(f"agent:{context_id}:{idx}"),
                              "question": f"Contexto #{context_id}: ¿qué agente hizo el Paso {idx} y quién más participó?",
                              "expected": {"lane": node["attrs"]["lane"],
                                           "agents": sorted({node["attrs"]["lane"], *node["attrs"]["secondary"]})}})
    return items


def constellation_items(conn, project: str, commits: Optional[CommitIndex] = None) -> list[dict]:
    """Tarea de la Constelación (§22.5): "¿qué contextos comparten evidencia con este?".

    El grafo muestra por defecto solo los contextos activos y los conectados a ellos; si la
    respuesta incluye algo fuera de ese alcance, la consigna pide "Alcance: Todos".
    """
    dto = project_constellation(conn, project, commits)
    active = {node["id"] for node in dto["nodes"] if node["kind"] == "context" and node["state"] == "active"}
    neighbors: dict[str, set[str]] = {}
    for bridge in dto["constellation"]["bridges"]:
        neighbors.setdefault(bridge["source"], set()).add(bridge["target"])
        if not bridge["portal"]:
            neighbors.setdefault(bridge["target"], set()).add(bridge["source"])
    visible = set(active)
    for bridge in dto["constellation"]["bridges"]:
        if bridge["source"] in active or bridge["target"] in active:
            visible.update((bridge["source"], bridge["target"]))
    items = []
    for node_id in sorted(neighbors, key=lambda value: int(value.split(":")[1])):
        context_id = int(node_id.split(":")[1])
        found = neighbors[node_id]
        items.append({"feature": "constellation", "task": "shared", "context": context_id, "id": opaque(f"shared:{context_id}"),
                      "question": f"¿Qué contextos (o proyectos) comparten commits con el contexto #{context_id}?",
                      "all_scope": not ({node_id} | found) <= visible,
                      "expected": {"contexts": sorted(int(item.split(":")[1]) for item in found if item.startswith("context:")),
                                   "portals": sorted(item.split(":", 1)[1] for item in found if item.startswith("portal:"))}})
    return items


def items_for(feature: str, conn, project: str) -> list[dict]:
    return map_items(conn, project) if feature == "map" else constellation_items(conn, project)


# ── Respuestas ──────────────────────────────────────────────────────────────────────────


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[\s,;:]+", text.strip().lower()) if token]


def _numbers(text: str) -> set[int]:
    """Números sueltos ("3", "#3", "paso 3"); los fragmentos de un SHA u otro texto no cuentan."""
    found = set()
    for token in _tokens(text):
        match = re.fullmatch(r"#?(\d{1,6})[.)]?", token)
        if match:
            found.add(int(match.group(1)))
    return found


def _agents(text: str) -> list[str]:
    named = []
    for token in _tokens(text):
        agent = normalize_agent(token)
        if agent != NO_AGENT and agent not in named:
            named.append(agent)
    return named


def check_answer(item: dict, text: str) -> bool:
    """Acierto: el conjunto exacto pedido (ni de menos ni de más), con el formato de la consigna."""
    expected = item["expected"]
    if item["task"] == "commit":
        return _numbers(text) == set(expected["steps"])
    if item["task"] == "agent":
        named = _agents(text)
        return bool(named) and named[0] == expected["lane"] and set(named) == set(expected["agents"])
    tokens = set(_tokens(text))
    portals_ok = all(alias.lower() in tokens for alias in expected["portals"])
    return portals_ok and _numbers(text) == set(expected["contexts"])


# ── Registros ───────────────────────────────────────────────────────────────────────────

_REQUIRED = {"feature": str, "session": int, "task": str, "condition": str, "item": str, "seconds": (int, float), "correct": bool}


def load_records(path: Path, warn=print) -> list[dict]:
    """Registros válidos; las líneas corruptas o incompletas se omiten con un aviso."""
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not all(isinstance(record.get(key), kind) for key, kind in _REQUIRED.items()) or record["condition"] not in CONDITIONS:
                raise ValueError("campos inválidos")
        except ValueError as error:
            warn(f"Línea {number} de {path.name} omitida: {error}")
            continue
        records.append(record)
    return records


def next_session(records: list[dict], feature: str) -> int:
    return max((record["session"] for record in records if record["feature"] == feature), default=0) + 1


def append_session(path: Path, records: list[dict]) -> None:
    """Agrega una sesión completa de una sola vez (no quedan sesiones a medias)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))


# ── Plan ────────────────────────────────────────────────────────────────────────────────


def plan_session(items: list[dict], session: int, history: list[dict], rng: random.Random) -> list[tuple[dict, str]]:
    """Ensayos de una sesión: por cada tipo de tarea, un ítem por condición, ítems distintos.

    Contrabalanceo: se eligen los dos ítems menos medidos y, de las dos formas de repartirlos
    entre las condiciones, la que menos repite ítem-condición ya medidos (así, a lo largo de las
    sesiones, cada ítem pasa por las dos). En empate, el primer ítem va a la condición que se
    presenta primero. El orden de las condiciones se alterna por sesión (par: grafo primero).
    """
    order = (GRAPH, LIST) if session % 2 == 0 else (LIST, GRAPH)
    exposure: dict[tuple[str, str], int] = {}
    for record in history:
        key = (record["item"], record["condition"])
        exposure[key] = exposure.get(key, 0) + 1
    trials = []
    for task in sorted({item["task"] for item in items}):
        pool = [item for item in items if item["task"] == task]
        if len(pool) < 2:
            continue
        rng.shuffle(pool)
        pool.sort(key=lambda item: exposure.get((item["id"], GRAPH), 0) + exposure.get((item["id"], LIST), 0))
        first, second = pool[0], pool[1]
        options = [{order[0]: first, order[1]: second}, {order[0]: second, order[1]: first}]
        assigned = min(options, key=lambda option: sum(exposure.get((item["id"], condition), 0)
                                                        for condition, item in option.items()))
        trials.extend((assigned[condition], condition) for condition in order)
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


# ── Resumen ─────────────────────────────────────────────────────────────────────────────


def complete_sessions(records: list[dict], feature: str) -> dict[int, list[dict]]:
    """Sesiones con las dos condiciones medidas (las demás no cuentan para el criterio)."""
    sessions: dict[int, list[dict]] = {}
    for record in records:
        if record["feature"] == feature:
            sessions.setdefault(record["session"], []).append(record)
    return {number: trials for number, trials in sessions.items() if {trial["condition"] for trial in trials} == set(CONDITIONS)}


def _stats(trials: list[dict]) -> dict:
    if not trials:
        return {"trials": 0, "median_s": None, "accuracy": None}
    return {"trials": len(trials), "median_s": statistics.median(trial["seconds"] for trial in trials),
            "accuracy": sum(trial["correct"] for trial in trials) / len(trials)}


def _verdict(graph: dict, listing: dict, enough: bool, missing: str) -> tuple[Optional[float], str]:
    if not graph["trials"] or not listing["trials"] or not listing["median_s"]:
        return None, "sin datos suficientes"
    gain = 1 - graph["median_s"] / listing["median_s"]
    if not enough:
        return gain, missing
    if gain >= MIN_GAIN and graph["accuracy"] >= listing["accuracy"]:
        return gain, "se mantiene"
    return gain, "no cumple"


def summarize(records: list[dict], feature: str) -> dict:
    """Mediana de tiempo y acierto por condición, y el veredicto (con valores sin redondear).

    En la Constelación cada modo (global y local) se compara además contra la lista (§22.5:
    se miden por separado y, si el grafo no cumple, queda solo el modo local como panel).
    """
    sessions = complete_sessions(records, feature)
    trials = [trial for group in sessions.values() for trial in group]
    result = {"feature": feature, "sessions": len(sessions)}
    for condition in CONDITIONS:
        result[condition] = _stats([trial for trial in trials if trial["condition"] == condition])
    graph, listing = result[GRAPH], result[LIST]
    missing = f"faltan sesiones ({result['sessions']} de {MIN_SESSIONS})"
    result["gain"], verdict = _verdict(graph, listing, result["sessions"] >= MIN_SESSIONS, missing)
    if feature == "constellation":
        graph_trials = [trial for trial in trials if trial["condition"] == GRAPH]
        result["modes"] = {}
        for mode in (*MODES.values(), UNRECORDED):
            stats = _stats([trial for trial in graph_trials if (trial.get("mode") if trial.get("mode") in MODES.values() else UNRECORDED) == mode])
            if mode != UNRECORDED:
                stats["gain"], stats["verdict"] = _verdict(stats, listing, stats["trials"] >= MIN_SESSIONS,
                                                           f"faltan ensayos ({stats['trials']} de {MIN_SESSIONS})")
            result["modes"][mode] = stats
        if verdict == "no cumple":
            verdict = "no cumple: queda solo el modo local como panel del Inspector (§22.5)"
    elif verdict == "no cumple":
        verdict = "no cumple: retirar o dejar solo como enlace (§21.6)"
    result["verdict"] = verdict
    return result


def _fmt(value: Optional[float], digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def tracking_line(summary: dict) -> str:
    graph, listing = summary[GRAPH], summary[LIST]
    gain = "—" if summary["gain"] is None else f"{summary['gain'] * 100:.0f} %"
    line = (f"Labs {summary['feature']}: {summary['sessions']} sesiones completas; mediana grafo {_fmt(graph['median_s'])} s "
            f"vs lista {_fmt(listing['median_s'])} s (mejora {gain}); acierto {_fmt(graph['accuracy'], 2)} vs "
            f"{_fmt(listing['accuracy'], 2)}.")
    if "modes" in summary:
        parts = []
        for mode, stats in summary["modes"].items():
            if mode == UNRECORDED:
                if stats["trials"]:
                    parts.append(f"{mode} {stats['trials']} ensayos")
                continue
            gain = "—" if stats.get("gain") is None else f"{stats['gain'] * 100:.0f} %"
            parts.append(f"{mode} {stats['trials']} ensayos (mediana {_fmt(stats['median_s'])} s, mejora {gain}, "
                         f"acierto {_fmt(stats['accuracy'], 2)}: {stats['verdict']})")
        line += " Por modo: " + "; ".join(parts) + "."
    return line + f" Veredicto: {summary['verdict']}."


# ── Ejecución ───────────────────────────────────────────────────────────────────────────


def run_session(feature: str, project: str, base: str, open_browser: bool, seed: Optional[int], ask=input) -> int:
    from orchestrator.db import _conn

    items = items_for(feature, _conn(), project)
    path = results_path()
    history = load_records(path)
    session = next_session(history, feature)
    trials = plan_session(items, session, [record for record in history if record["feature"] == feature], random.Random(seed))
    if not trials:
        print("No hay tareas suficientes para este proyecto (hacen falta al menos dos ítems elegibles por tarea).")
        return 1
    print(f"Sesión {session} de {feature} · {len(trials)} tareas. Se guarda solo si la terminás (Ctrl+C la descarta).")
    results = []
    try:
        for number, (item, condition) in enumerate(trials, start=1):
            print(f"\n[{number}/{len(trials)}] {INSTRUCTIONS[(feature, condition)]}")
            if item.get("all_scope") and condition == GRAPH:
                print("En el grafo elegí Alcance: Todos (este contexto no está entre los activos).")
            print(item["question"])
            print(FORMATS[item["task"]])
            url = url_for(base, project, item, condition)
            ask(f"Enter para abrir {url} y empezar a cronometrar… ")
            if open_browser:
                webbrowser.open(url)
            else:
                print(url)
            start = time.monotonic()
            answer = ask("Respuesta: ")
            seconds = round(time.monotonic() - start, 2)
            correct = check_answer(item, answer)
            print(f"{'Correcta' if correct else 'Incorrecta'} · {seconds:.1f} s")
            record = {"ts": datetime.now(timezone.utc).isoformat(), "feature": feature, "project": project,
                      "session": session, "task": item["task"], "condition": condition, "item": item["id"],
                      "seconds": seconds, "correct": correct}
            if feature == "constellation" and condition == GRAPH:
                record["mode"] = MODES.get(ask("¿Qué modo usaste? (g = global, l = local): ").strip().lower()[:1], "global")
            results.append(record)
    except (KeyboardInterrupt, EOFError):
        print("\nSesión cortada: no se guardó nada.")
        return 130
    append_session(path, results)
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
        tasks: dict[str, int] = {}
        for item in items:
            tasks[item["task"]] = tasks.get(item["task"], 0) + 1
        print(f"{len(items)} tareas posibles: " + (", ".join(f"{task} {count}" for task, count in sorted(tasks.items())) or "ninguna"))
        return 0
    if args.command == "run":
        return run_session(args.feature, args.project, args.base, not args.no_browser, args.seed)
    print(tracking_line(summarize(load_records(results_path()), args.feature)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
