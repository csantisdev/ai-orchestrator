"""Mapa del contexto (spec §21.3, §21.4) sobre una base SQLite sintética."""

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator import api_v1, projections
from orchestrator.api_v1 import Request, work
from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from orchestrator.projections import CommitIndex, context_map
from tests.test_api_work import _context, _empty_db, _run, _step

SCHEMA = json.loads(
    (Path(projections.__file__).parent / "schemas" / "context_map.schema.json").read_text(encoding="utf-8")
)


def sha(n: int) -> str:
    return f"{n:x}".rjust(8, "a") + "0123456789abcdef" * 2


def _validate(payload):
    jsonschema.validate(payload, SCHEMA, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


def _align(conn, step_id, context_id, agent, ts="2026-05-10T10:00:00Z", confirmed=1):
    conn.execute(
        "INSERT INTO alignments (ts, step_id, context_id, agent, confirmed) VALUES (?, ?, ?, ?, ?)",
        (ts, step_id, context_id, agent, confirmed),
    )


@pytest.fixture
def conn():
    db = _empty_db()
    yield db
    db.close()


def _commits(conn, project, shas):
    for value in shas:
        _run(conn, project, "2026-05-10T10:00:00Z", provider=GIT_PROVIDER, session_id=f"git::{project}::{value}")
    conn.commit()
    return CommitIndex(shas)


def test_lanes_follow_the_catalog_and_no_agent_goes_last(conn):
    ctx = _context(conn, "mi-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    _step(conn, ctx, 1, "a", "completed", provider="")
    _step(conn, ctx, 2, "b", "completed", provider="codex")
    third = _step(conn, ctx, 3, "c", "completed", provider="")
    _align(conn, third, ctx, "claude-code")
    conn.commit()
    result = context_map(conn, ctx, CommitIndex([]))
    _validate(result)
    assert result["map"]["lanes"] == ["claude", "codex", "sin agente"]
    assert result["map"]["eligible"] is True
    assert [node["attrs"]["lane"] for node in result["nodes"] if node["kind"] == "step"] == ["sin agente", "codex", "claude"]


def test_a_single_lane_without_shared_commits_is_not_eligible(conn):
    ctx = _context(conn, "mi-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    _step(conn, ctx, 1, "a", "completed", provider="claude", notes=f"commit {sha(1)}")
    _step(conn, ctx, 2, "b", "completed", provider="")
    index = _commits(conn, "mi-proyecto", [sha(1)])
    result = context_map(conn, ctx, index)
    assert result["map"]["lanes"] == ["claude", "sin agente"]
    assert result["map"]["eligible"] is False
    assert result["map"]["shared"] == []


def test_shared_commits_are_placed_under_their_first_citing_step_and_stacked_by_sha(conn):
    ctx = _context(conn, "mi-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    first = _step(conn, ctx, 1, "a", "completed", provider="claude", notes=f"{sha(3)} y {sha(2)}")
    second = _step(conn, ctx, 2, "b", "completed", provider="claude", notes=f"{sha(2)}")
    third = _step(conn, ctx, 3, "c", "completed", provider="claude", notes=f"{sha(3)} {sha(4)}")
    index = _commits(conn, "mi-proyecto", [sha(2), sha(3), sha(4)])
    result = context_map(conn, ctx, index)
    _validate(result)
    mp = result["map"]
    assert mp["eligible"] is True
    assert mp["shared"] == [f"commit:{sha(2)}", f"commit:{sha(3)}"]
    assert mp["placement"] == {
        f"commit:{sha(2)}": {"column": 1, "stack": 0},
        f"commit:{sha(3)}": {"column": 1, "stack": 1},
        f"commit:{sha(4)}": {"column": 3, "stack": 0},
    }
    cites = [(edge["source"], edge["target"]) for edge in result["edges"] if edge["relation_type"] == "cites"]
    assert cites == [
        (f"step:{first}", f"commit:{sha(2)}"), (f"step:{second}", f"commit:{sha(2)}"),
        (f"step:{first}", f"commit:{sha(3)}"), (f"step:{third}", f"commit:{sha(3)}"),
        (f"step:{third}", f"commit:{sha(4)}"),
    ]


def test_too_many_commits_turn_single_citations_into_step_counters(conn):
    ctx = _context(conn, "mi-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    first = _step(conn, ctx, 1, "a", "completed", provider="claude", notes=f"{sha(1)} {sha(2)} {sha(9)}")
    _step(conn, ctx, 2, "b", "completed", provider="claude", notes=f"{sha(3)} {sha(9)}")
    index = _commits(conn, "mi-proyecto", [sha(1), sha(2), sha(3), sha(9)])
    result = context_map(conn, ctx, index, max_commits=3)
    _validate(result)
    mp = result["map"]
    assert [node["id"] for node in result["nodes"] if node["kind"] == "commit"] == [f"commit:{sha(9)}"]
    assert mp["single_commits"] == {f"step:{first}": 2, mp["single_commits"] and next(k for k in mp["single_commits"] if k != f"step:{first}"): 1}
    assert mp["shared"] == [f"commit:{sha(9)}"]


def test_extreme_case_keeps_the_most_cited_shared_commits_and_caps_edges(conn):
    ctx = _context(conn, "mi-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    shas = [sha(n) for n in range(1, 5)]
    # sha(4) lo citan los tres pasos; el resto, dos.
    _step(conn, ctx, 1, "a", "completed", provider="claude", notes=" ".join(shas))
    _step(conn, ctx, 2, "b", "completed", provider="claude", notes=" ".join(shas))
    _step(conn, ctx, 3, "c", "completed", provider="claude", notes=shas[3])
    index = _commits(conn, "mi-proyecto", shas)
    result = context_map(conn, ctx, index, max_commits=2, max_edges=4)
    _validate(result)
    mp = result["map"]
    drawn = [node["id"] for node in result["nodes"] if node["kind"] == "commit"]
    # Ranking: más citantes primero (sha 4), después columna y SHA (sha 1).
    assert sorted(drawn) == sorted([f"commit:{shas[3]}", f"commit:{shas[0]}"])
    assert mp["more_commits"] == 2
    # Los dos compartidos sin dibujar los citan los pasos 1 y 2.
    assert mp["more_commit_steps"] == [node["id"] for node in result["nodes"] if node["kind"] == "step"][:2]
    cites = [edge for edge in result["edges"] if edge["relation_type"] == "cites"]
    assert len(cites) == 4
    assert sum(mp["hidden_edges"].values()) == 5 - 4


def test_groups_collapse_long_runs_of_quiet_completed_steps(conn):
    ctx = _context(conn, "mi-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    ids = [_step(conn, ctx, n, f"p{n}", "completed", provider="claude" if n != 3 else "codex") for n in range(1, 5)]
    deviated = _step(conn, ctx, 5, "p5", "completed", provider="claude")
    _align(conn, deviated, ctx, "claude", confirmed=0)
    tail = [_step(conn, ctx, n, f"p{n}", "completed", provider="claude") for n in range(6, 8)]
    _step(conn, ctx, 8, "p8", "in_progress", provider="claude")
    conn.commit()
    result = context_map(conn, ctx, CommitIndex([]), max_steps=3)
    _validate(result)
    groups = result["map"]["groups"]
    assert [(g["from_idx"], g["to_idx"], g["count"], g["lane"]) for g in groups] == [(1, 4, 4, "claude"), (6, 7, 2, "claude")]
    assert groups[0]["members"] == [f"step:{i}" for i in ids]
    assert groups[0]["lanes"] == {"claude": 3, "codex": 1}
    assert groups[1]["members"] == [f"step:{i}" for i in tail]
    assert context_map(conn, ctx, CommitIndex([]))["map"]["groups"] == []


def test_the_endpoint_is_scoped_to_the_project(conn, monkeypatch):
    mine = _context(conn, "mi-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    other = _context(conn, "otro-proyecto", "C", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    _step(conn, mine, 1, "a", "completed", provider="claude", notes=sha(7))
    _step(conn, mine, 2, "b", "completed", provider="codex", notes=sha(7))
    _commits(conn, "otro-proyecto", [sha(7)])
    monkeypatch.setattr(work, "_connection", lambda: conn)
    monkeypatch.setattr(work, "_registered_projects", lambda: {"mi-proyecto"})
    api_v1.discover()
    status, payload = api_v1.dispatch(Request("GET", f"/api/v1/projects/mi-proyecto/contexts/{mine}/map"))
    assert status == 200
    _validate(payload)
    # El commit es de otro proyecto: no se verifica para este.
    assert [node for node in payload["nodes"] if node["kind"] == "commit"] == []
    assert payload["map"]["lanes"] == ["claude", "codex"]
    status, _ = api_v1.dispatch(Request("GET", f"/api/v1/projects/mi-proyecto/contexts/{other}/map"))
    assert status == 404
    status, _ = api_v1.dispatch(Request("GET", "/api/v1/projects/mi-proyecto/contexts/0/map"))
    assert status == 400
