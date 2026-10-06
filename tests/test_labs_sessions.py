"""Kit de medición de Labs (scripts/labs_sessions.py, spec §21.6, §22.5, §23.8)."""

import importlib.util
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
    _context(db, "mi-proyecto", "c", "completed", TS, TS)
    s1 = _step(db, a, 1, "uno", "completed", provider="claude", notes=f"{sha(1)} {sha(2)}")
    _step(db, a, 2, "dos", "completed", provider="codex", notes=f"{sha(1)} {sha(2)}")
    _step(db, a, 3, "tres", "completed", provider="claude", notes=sha(1))
    _step(db, b, 1, "otro", "completed", provider="codex", notes=sha(2))
    # Codex también participó en el paso 1 (alineamiento): agente secundario.
    db.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message) VALUES (?, ?, ?, ?, 1, '', '')",
               (TS, s1, a, "codex"))
    for n in (1, 2):
        _run(db, "mi-proyecto", TS, provider=GIT_PROVIDER, session_id=f"git::mi-proyecto::{sha(n)}")
    db.commit()
    yield db, a, b
    db.close()


def test_map_items_ask_for_shared_commits_and_participants(conn):
    db, a, _ = conn
    items = labs.map_items(db, "mi-proyecto")
    commit = next(item for item in items if item["task"] == "commit")
    assert commit["context"] == a and commit["expected"] == {"steps": [1, 2, 3]}
    assert sha(1)[:7] in commit["question"]
    agent = next(item for item in items if item["task"] == "agent")
    assert agent["expected"] == {"lane": "claude", "agents": ["claude", "codex"]}
    assert "Paso 1" in agent["question"]


def test_constellation_items_list_neighbors(conn):
    db, a, b = conn
    items = {item["context"]: item for item in labs.constellation_items(db, "mi-proyecto")}
    assert items[a]["expected"] == {"contexts": [b], "portals": []}
    assert items[b]["expected"] == {"contexts": [a], "portals": []}


@pytest.mark.parametrize("task,expected,answer,ok", [
    ("commit", {"steps": [1, 3]}, "Paso 1 y paso 3", True),
    ("commit", {"steps": [1, 3]}, "1", False),
    ("commit", {"steps": [1, 3]}, "1, 2, 3", False),
    ("agent", {"lane": "claude", "agents": ["claude", "codex"]}, "Claude, participó Codex", True),
    ("agent", {"lane": "claude", "agents": ["claude", "codex"]}, "codex y claude", False),
    ("agent", {"lane": "claude", "agents": ["claude", "codex"]}, "claude", False),
    ("shared", {"contexts": [28, 29], "portals": ["otro-proyecto"]}, "#28, #29 y otro-proyecto", True),
    ("shared", {"contexts": [28, 29], "portals": ["otro-proyecto"]}, "#28 y #29", False),
])
def test_check_answer_requires_the_exact_set(task, expected, answer, ok):
    assert labs.check_answer({"task": task, "expected": expected}, answer) is ok


def test_plan_session_alternates_conditions_with_distinct_items():
    items = [{"task": "commit", "key": str(n)} for n in range(4)] + [{"task": "agent", "key": "x"}]
    even = labs.plan_session(items, 2, random.Random(1))
    odd = labs.plan_session(items, 3, random.Random(1))
    # Un solo ítem de "agent" no alcanza para las dos condiciones: esa tarea se omite.
    assert [condition for _, condition in even] == [labs.GRAPH, labs.LIST]
    assert [condition for _, condition in odd] == [labs.LIST, labs.GRAPH]
    assert even[0][0]["key"] != even[1][0]["key"]


def test_url_for_switches_representation():
    item = {"feature": "map", "context": 7}
    assert labs.url_for("http://localhost:8080/", "mi-proyecto", item, labs.GRAPH) == \
        "http://localhost:8080/?project=mi-proyecto&view=trabajo&ctx=7&as=map"
    assert "as=" not in labs.url_for("http://localhost:8080", "mi-proyecto", item, labs.LIST)
    graph = labs.url_for("http://x", "mi-proyecto", {"feature": "constellation", "context": 7}, labs.GRAPH)
    assert graph.endswith("tab=contextos&as=constellation")


def _records(sessions, graph_s, list_s, graph_ok=True, list_ok=True):
    records = []
    for session in range(1, sessions + 1):
        records.append({"feature": "map", "session": session, "condition": labs.GRAPH, "seconds": graph_s, "correct": graph_ok})
        records.append({"feature": "map", "session": session, "condition": labs.LIST, "seconds": list_s, "correct": list_ok})
    return records


def test_summary_applies_the_permanence_criterion():
    kept = labs.summarize(_records(10, 30, 40), "map")
    assert (kept["gain"], kept["verdict"]) == (0.25, "se mantiene")
    assert labs.summarize(_records(9, 30, 40), "map")["verdict"].startswith("faltan sesiones")
    assert labs.summarize(_records(10, 35, 40), "map")["verdict"].startswith("no cumple")
    assert labs.summarize(_records(10, 30, 40, graph_ok=False), "map")["verdict"].startswith("no cumple")
    assert labs.summarize([], "map")["verdict"] == "sin datos suficientes"
    assert "10 sesiones" in labs.tracking_line(kept) and "25 %" in labs.tracking_line(kept)


def test_records_are_appended_without_answer_text(tmp_path, monkeypatch, conn):
    db, _, _ = conn
    from orchestrator import db as db_module
    from orchestrator import paths

    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(db_module, "_conn", lambda: db)
    answers = iter(["", "texto privado 1 2 3", "", "otra cosa"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert labs.run_session("map", "mi-proyecto", "http://localhost:8080", False, seed=1) == 0
    records = labs.load_records(tmp_path / "labs-sessions.jsonl")
    assert len(records) == 2 and {record["session"] for record in records} == {1}
    assert "texto privado" not in (tmp_path / "labs-sessions.jsonl").read_text(encoding="utf-8")
    assert labs.next_session(records, "map") == 2
