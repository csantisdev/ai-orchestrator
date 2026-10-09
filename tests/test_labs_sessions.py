"""Kit de medición de Labs (scripts/labs_sessions.py, spec §21.6, §22.5, §23.8)."""

import importlib.util
import json
import random
from pathlib import Path

import pytest

from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from tests.test_api_work import _context, _empty_db, _run, _step

_SPEC = importlib.util.spec_from_file_location(
    "labs_sessions", Path(__file__).resolve().parent.parent / "scripts" / "labs_sessions.py")
labs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(labs)

TS = "2026-05-01T00:00:00Z"


def sha(n: int) -> str:
    return f"{n:x}".rjust(8, "d") + "0123456789abcdef" * 2


@pytest.fixture
def conn():
    db = _empty_db()
    a = _context(db, "mi-proyecto", "a", "active", TS, TS)
    b = _context(db, "mi-proyecto", "b", "completed", TS, TS)
    c = _context(db, "mi-proyecto", "c", "completed", TS, TS)
    d = _context(db, "mi-proyecto", "d", "completed", TS, TS)
    # order_idx discontinuo: "Paso N" es el ordinal que muestra la UI (1, 2, 3).
    s1 = _step(db, a, 10, "uno", "completed", provider="claude", notes=f"{sha(1)} {sha(2)}")
    _step(db, a, 20, "dos", "completed", provider="codex", notes=f"{sha(1)} {sha(2)}")
    _step(db, a, 30, "tres", "completed", provider="claude", notes=sha(1))
    _step(db, b, 1, "otro", "completed", provider="codex", notes=sha(2))
    # c y d (cerrados) comparten un commit entre sí: fuera del alcance por defecto del grafo.
    _step(db, c, 1, "c1", "completed", provider="claude", notes=sha(3))
    _step(db, d, 1, "d1", "completed", provider="claude", notes=sha(3))
    db.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message) VALUES (?, ?, ?, ?, 1, '', '')",
               (TS, s1, a, "codex"))
    for n in (1, 2, 3):
        _run(db, "mi-proyecto", TS, provider=GIT_PROVIDER, session_id=f"git::mi-proyecto::{sha(n)}")
    db.commit()
    yield db, a, b, c, d
    db.close()


def test_map_items_use_the_ordinal_shown_by_the_ui(conn):
    db, a, *_ = conn
    items = labs.map_items(db, "mi-proyecto")
    commits = [item for item in items if item["task"] == "commit"]
    assert [item["expected"]["steps"] for item in commits] == [[1, 2, 3], [1, 2]]
    assert sha(1)[:7] in commits[0]["question"]
    agent = next(item for item in items if item["task"] == "agent")
    assert agent["context"] == a and "Paso 1" in agent["question"]
    assert agent["expected"] == {"lane": "claude", "agents": ["claude", "codex"]}
    # El id es un hash local: no guarda el SHA.
    assert sha(1) not in json.dumps([item["id"] for item in items])


def test_constellation_items_flag_contexts_outside_the_default_scope(conn):
    db, a, b, c, d = conn
    items = {item["context"]: item for item in labs.constellation_items(db, "mi-proyecto")}
    assert items[a]["expected"] == {"contexts": [b], "portals": []}
    assert (items[a]["all_scope"], items[b]["all_scope"]) == (False, False)
    assert items[c]["expected"]["contexts"] == [d] and items[c]["all_scope"] is True


@pytest.mark.parametrize("task,expected,answer,ok", [
    ("commit", {"steps": [1, 3]}, "1, 3", True),
    ("commit", {"steps": [1, 3]}, "paso 1 y #3", True),
    ("commit", {"steps": [1, 3]}, "1, 3 (commit a1b2c3d)", True),
    ("commit", {"steps": [1, 3]}, "1", False),
    ("commit", {"steps": [1, 3]}, "1, 2, 3", False),
    ("agent", {"lane": "claude", "agents": ["claude", "codex"]}, "Claude, Codex", True),
    ("agent", {"lane": "claude", "agents": ["claude", "codex"]}, "CLAUDE; codex", True),
    ("agent", {"lane": "claude", "agents": ["claude", "codex"]}, "codex, claude", False),
    ("agent", {"lane": "claude", "agents": ["claude", "codex"]}, "claude", False),
    ("shared", {"contexts": [28, 29], "portals": ["otro-proyecto"]}, "28, 29, otro-proyecto", True),
    ("shared", {"contexts": [28, 29], "portals": ["otro-proyecto"]}, "#28 #29", False),
    ("shared", {"contexts": [28], "portals": ["proyecto-a"]}, "28, proyecto", False),
])
def test_check_answer_requires_the_exact_set(task, expected, answer, ok):
    assert labs.check_answer({"task": task, "expected": expected}, answer) is ok


def _item(task, n):
    return {"task": task, "id": f"{task}{n}", "feature": "map", "context": n}


def test_plan_alternates_order_and_balances_items_across_conditions():
    items = [_item("commit", n) for n in range(4)] + [_item("agent", 0)]
    even = labs.plan_session(items, 2, [], random.Random(1))
    odd = labs.plan_session(items, 3, [], random.Random(1))
    # Un solo ítem de "agent" no alcanza para las dos condiciones: esa tarea se omite.
    assert [condition for _, condition in even] == [labs.GRAPH, labs.LIST]
    assert [condition for _, condition in odd] == [labs.LIST, labs.GRAPH]
    assert even[0][0]["id"] != even[1][0]["id"]
    # Con historial, se eligen los menos medidos y cada uno va a la condición que le falta.
    history = [{"item": "commit0", "condition": labs.GRAPH}, {"item": "commit1", "condition": labs.LIST},
               {"item": "commit2", "condition": labs.GRAPH}, {"item": "commit2", "condition": labs.LIST}]
    plan = {item["id"]: condition for item, condition in labs.plan_session(items[:4], 4, history, random.Random(3))}
    assert "commit2" not in plan or set(plan) == {"commit3", "commit2"}
    assert plan.get("commit0", labs.LIST) == labs.LIST and plan.get("commit1", labs.GRAPH) == labs.GRAPH


def test_plan_assigns_the_pair_jointly_to_minimize_repeats():
    # A no se midió en el grafo; B ya se midió 10 veces en lista: B va al grafo y A a la lista,
    # aunque en una sesión par el grafo se presenta primero.
    items = [_item("commit", 0), _item("commit", 1)]
    history = [{"item": "commit1", "condition": labs.LIST}] * 10 + [{"item": "commit0", "condition": labs.LIST}]
    plan = {item["id"]: condition for item, condition in labs.plan_session(items, 2, history, random.Random(0))}
    assert plan == {"commit1": labs.GRAPH, "commit0": labs.LIST}


def test_url_for_switches_representation():
    item = {"feature": "map", "context": 7}
    assert labs.url_for("http://localhost:8080/", "mi-proyecto", item, labs.GRAPH) == \
        "http://localhost:8080/?project=mi-proyecto&view=trabajo&ctx=7&as=map"
    assert "as=" not in labs.url_for("http://localhost:8080", "mi-proyecto", item, labs.LIST)
    graph = labs.url_for("http://x", "mi-proyecto", {"feature": "constellation", "context": 7}, labs.GRAPH)
    assert graph.endswith("tab=contextos&as=constellation")


def _records(sessions, graph_s, list_s, graph_ok=True, list_ok=True, feature="map"):
    records = []
    for session in range(1, sessions + 1):
        base = {"feature": feature, "session": session, "task": "commit", "item": "x"}
        records.append({**base, "condition": labs.GRAPH, "seconds": graph_s, "correct": graph_ok, "mode": "local"})
        records.append({**base, "condition": labs.LIST, "seconds": list_s, "correct": list_ok})
    return records


def test_summary_applies_the_criterion_without_rounding():
    kept = labs.summarize(_records(10, 30, 40), "map")
    assert (round(kept["gain"], 2), kept["verdict"]) == (0.25, "se mantiene")
    assert labs.summarize(_records(9, 30, 40), "map")["verdict"].startswith("faltan sesiones")
    # 80,04 s vs 100 s es 19,96 %: no alcanza aunque redondeado parezca 20 %.
    assert labs.summarize(_records(10, 80.04, 100), "map")["verdict"].startswith("no cumple: retirar")
    assert labs.summarize(_records(10, 30, 40, graph_ok=False), "map")["verdict"].startswith("no cumple")
    assert labs.summarize([], "map")["verdict"] == "sin datos suficientes"
    line = labs.tracking_line(kept)
    assert "10 sesiones completas" in line and "25 %" in line


def test_partial_sessions_do_not_count_and_constellation_judges_each_mode():
    records = _records(10, 30, 40, feature="constellation")
    records.append({"feature": "constellation", "session": 11, "task": "shared", "item": "y", "condition": labs.GRAPH,
                    "seconds": 1, "correct": True, "mode": "global"})
    summary = labs.summarize(records, "constellation")
    assert summary["sessions"] == 10 and summary[labs.GRAPH]["median_s"] == 30
    assert summary["modes"]["local"]["trials"] == 10 and summary["modes"]["local"]["verdict"] == "se mantiene"
    assert summary["modes"]["global"]["verdict"] == "sin datos suficientes"
    assert "local 10 ensayos" in labs.tracking_line(summary)


def test_constellation_failure_falls_back_to_local_only_and_unrecorded_modes_are_reported():
    records = _records(10, 39, 40, feature="constellation")
    # Sin clave, nula, vacía o desconocida: todo cuenta como "sin registrar".
    for index, record in enumerate(records):
        if record["condition"] == labs.GRAPH:
            record.pop("mode", None)
            if index % 3 == 1:
                record["mode"] = None
            elif index % 3 == 2:
                record["mode"] = ""
    summary = labs.summarize(records, "constellation")
    assert summary["verdict"].startswith("no cumple: queda solo el modo local")
    assert summary["modes"][labs.UNRECORDED]["trials"] == 10
    assert "sin registrar 10 ensayos" in labs.tracking_line(summary)


def test_corrupt_lines_are_skipped_with_a_warning(tmp_path):
    path = tmp_path / "labs-sessions.jsonl"
    good = _records(1, 30, 40)
    path.write_text("\n".join([json.dumps(good[0]), "{truncado", json.dumps({"feature": "map"}), json.dumps(good[1])]) + "\n",
                    encoding="utf-8")
    warnings = []
    records = labs.load_records(path, warn=warnings.append)
    assert len(records) == 2 and len(warnings) == 2 and "Línea 2" in warnings[0]


def _run_session(monkeypatch, tmp_path, db, answers, feature="map"):
    from orchestrator import db as db_module
    from orchestrator import paths

    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(db_module, "_conn", lambda: db)
    replies = iter(answers)

    def ask(prompt=""):
        value = next(replies)
        if isinstance(value, BaseException):
            raise value
        return value

    code = labs.run_session(feature, "mi-proyecto", "http://localhost:8080", False, seed=1, ask=ask)
    return code, labs.load_records(tmp_path / "labs-sessions.jsonl")


def test_a_complete_session_is_saved_without_answer_text(tmp_path, monkeypatch, conn):
    db, *_ = conn
    code, records = _run_session(monkeypatch, tmp_path, db, ["", "texto privado 1 2 3", "", "otra cosa"])
    assert code == 0
    assert len(records) == 2 and {record["session"] for record in records} == {1}
    text = (tmp_path / "labs-sessions.jsonl").read_text(encoding="utf-8")
    assert "texto privado" not in text and sha(1) not in text
    assert labs.next_session(records, "map") == 2


def test_an_interrupted_session_saves_nothing(tmp_path, monkeypatch, conn):
    db, *_ = conn
    code, records = _run_session(monkeypatch, tmp_path, db, ["", "1, 2, 3", KeyboardInterrupt()])
    assert code == 130 and records == []


def test_constellation_session_records_the_mode_used(tmp_path, monkeypatch, conn):
    db, *_ = conn
    # Sesión 1 (impar): primero la lista (Enter y respuesta), después el grafo (más el modo).
    answers = ["", "respuesta", "", "respuesta", "l"]
    code, records = _run_session(monkeypatch, tmp_path, db, answers, feature="constellation")
    assert code == 0
    graph = [record for record in records if record["condition"] == labs.GRAPH]
    assert graph and graph[0]["mode"] == "local"
    assert all("mode" not in record for record in records if record["condition"] == labs.LIST)
