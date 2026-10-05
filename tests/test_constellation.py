"""Constelación del proyecto (spec §22.4, §22.5) sobre una base SQLite sintética."""

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator import api_v1, projections
from orchestrator.api_v1 import Request, work
from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from orchestrator.projections import CommitIndex, project_constellation
from tests.test_api_work import _context, _empty_db, _run, _step

SCHEMA = json.loads(
    (Path(projections.__file__).parent / "schemas" / "project_constellation.schema.json").read_text(encoding="utf-8")
)


def sha(n: int) -> str:
    return f"{n:x}".rjust(8, "c") + "0123456789abcdef" * 2


def _validate(payload):
    jsonschema.validate(payload, SCHEMA, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


@pytest.fixture
def data():
    conn = _empty_db()
    ctx = {name: _context(conn, project, name, status, "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
           for name, project, status in [("a", "mi-proyecto", "active"), ("b", "mi-proyecto", "completed"),
                                         ("c", "mi-proyecto", "active"), ("x", "otro-proyecto", "active")]}
    _step(conn, ctx["a"], 1, "a1", "completed", provider="claude", notes=f"{sha(1)} {sha(2)} {sha(3)}")
    _step(conn, ctx["a"], 2, "a2", "in_progress", provider="codex")
    _step(conn, ctx["a"], 3, "a3", "pending", provider="claude")
    _step(conn, ctx["b"], 1, "b1", "completed", provider="codex", notes=f"cita {sha(1)} y {sha(2)}")
    _step(conn, ctx["c"], 1, "c1", "completed", provider="", notes="sin commits")
    _step(conn, ctx["x"], 1, "x1", "completed", provider="claude", notes=sha(3))
    for value in (sha(1), sha(2), sha(3)):
        _run(conn, "mi-proyecto", "2026-05-02T00:00:00Z", provider=GIT_PROVIDER, session_id=f"git::mi-proyecto::{value}")
    conn.commit()
    yield conn, ctx
    conn.close()


def test_bridges_weigh_shared_commits_and_portals_stand_for_other_projects(data):
    conn, ctx = data
    result = project_constellation(conn, "mi-proyecto")
    _validate(result)
    bridges = result["constellation"]["bridges"]
    a, b = f"context:{ctx['a']}", f"context:{ctx['b']}"
    assert bridges == [
        {"source": a, "target": b, "weight": 2, "commits": [f"commit:{sha(1)}", f"commit:{sha(2)}"], "portal": False},
        {"source": a, "target": "portal:otro-proyecto", "weight": 1, "commits": [f"commit:{sha(3)}"], "portal": True},
    ]
    portal = next(node for node in result["nodes"] if node["kind"] == "portal")
    assert portal == {"id": "portal:otro-proyecto", "kind": "portal", "label": "otro-proyecto", "attrs": {"commits": 1}}
    # Del otro proyecto no viaja ningún contexto ni paso.
    assert f"context:{ctx['x']}" not in {node["id"] for node in result["nodes"]}


def test_contexts_carry_size_activity_and_dominant_agent(data):
    conn, ctx = data
    result = project_constellation(conn, "mi-proyecto")
    contexts = {node["id"]: node for node in result["nodes"] if node["kind"] == "context"}
    a = contexts[f"context:{ctx['a']}"]["attrs"]
    assert (a["steps"], a["in_progress"], a["agent"], a["connected"]) == (3, 1, "claude", True)
    assert contexts[f"context:{ctx['b']}"]["attrs"]["agent"] == "codex"
    c = contexts[f"context:{ctx['c']}"]["attrs"]
    assert (c["agent"], c["connected"]) == ("sin agente", False)
    satellites = [node for node in result["nodes"] if node["kind"] == "step" and node["attrs"]["context"] == f"context:{ctx['a']}"]
    assert [node["label"] for node in satellites] == ["Paso 1", "Paso 2", "Paso 3"]
    assert len([edge for edge in result["edges"] if edge["source"] == f"context:{ctx['a']}"]) == 3


def test_isolated_contexts_go_to_a_grid_below_the_connected_ones(data):
    conn, ctx = data
    c = project_constellation(conn, "mi-proyecto")["constellation"]
    assert c["isolated"] == [f"context:{ctx['c']}"]
    connected_y = [c["positions"][node]["y"] for node in (f"context:{ctx['a']}", f"context:{ctx['b']}", "portal:otro-proyecto")]
    assert c["positions"][f"context:{ctx['c']}"]["y"] > max(connected_y)
    assert c["size"]["height"] > max(connected_y)


def test_positions_are_deterministic(data):
    conn, _ = data
    first = project_constellation(conn, "mi-proyecto")["constellation"]["positions"]
    second = project_constellation(conn, "mi-proyecto", CommitIndex.from_db(conn))["constellation"]["positions"]
    assert first == second
    assert len(first) == 4


def test_a_project_without_bridges_lays_out_every_context_in_the_grid():
    conn = _empty_db()
    ids = [_context(conn, "solo", f"c{n}", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z") for n in range(12)]
    conn.commit()
    result = project_constellation(conn, "solo", CommitIndex([]))
    _validate(result)
    c = result["constellation"]
    assert c["bridges"] == [] and c["isolated"] == [f"context:{i}" for i in ids]
    assert len({(p["x"], p["y"]) for p in c["positions"].values()}) == 12
    conn.close()


def test_the_endpoint_answers_for_known_projects_only(data, monkeypatch):
    conn, _ = data
    monkeypatch.setattr(work, "_connection", lambda: conn)
    monkeypatch.setattr(work, "_registered_projects", lambda: {"mi-proyecto"})
    api_v1.discover()
    status, payload = api_v1.dispatch(Request("GET", "/api/v1/projects/mi-proyecto/constellation"))
    assert status == 200
    _validate(payload)
    status, _ = api_v1.dispatch(Request("GET", "/api/v1/projects/desconocido/constellation"))
    assert status == 404
