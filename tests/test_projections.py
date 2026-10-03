import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from orchestrator import projections
from orchestrator.projections import (
    CommitIndex,
    activity,
    context_graph,
    extract_references,
    normalize_agent,
    step_references,
    to_utc,
)

SCHEMAS = Path(projections.__file__).parent / "schemas"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

SHA_A = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_B = "b1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_C1 = "c0ffee1234567890abcdef1234567890abcdef12"
SHA_C2 = "c0ffee1299999999abcdef1234567890abcdef12"


def _schema(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _validate(instance, name):
    jsonschema.validate(
        instance, _schema(name), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )


@pytest.fixture
def conn():
    """Base vacía con el esquema real de la aplicación (sin datos de otros tests)."""
    from orchestrator.db import _conn

    source = _conn()
    target = sqlite3.connect(":memory:")
    for (sql,) in source.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
    ).fetchall():
        target.execute(sql)
    yield target
    target.close()


def _context(conn, project="mi-proyecto", status="active"):
    cur = conn.execute(
        "INSERT INTO contexts (ts, updated_at, project, title, status) VALUES (?, ?, ?, ?, ?)",
        ("2026-05-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00", project, "titulo privado", status),
    )
    return cur.lastrowid


def _step(conn, context_id, order_idx, provider="", notes="", status="completed",
          started_at=None, completed_at=None):
    cur = conn.execute(
        "INSERT INTO steps (context_id, order_idx, title, status, provider, notes, started_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (context_id, order_idx, "titulo de paso", status, provider, notes, started_at, completed_at),
    )
    return cur.lastrowid


def _commit(conn, sha, alias="mi-proyecto"):
    conn.execute(
        "INSERT INTO runs (ts, project, provider, status, session_id) VALUES (?, ?, 'git', 'done', ?)",
        ("2026-05-01T00:00:00-03:00", alias, f"git::{alias}::{sha}"),
    )


def _mcp(conn, ts, request_id, tool_name, category, surface):
    conn.execute(
        "INSERT INTO mcp_invocations (ts, request_id, server_instance_id, client_surface, transport, "
        "capability_profile, tool_name, tool_category, project, input_hash, output_hash, status, "
        "created_at) VALUES (?, ?, 'srv', ?, 'stdio', 'workflow_operator', ?, ?, 'mi-proyecto', "
        "'h', 'h', 'ok', ?)",
        (ts, request_id, surface, tool_name, category, ts),
    )


class TestTimestamps:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("2026-06-01T09:00:00-03:00", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01T08:00:00-04:00", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01T12:00:00Z", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01T12:00:00", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01T12:00:00.123456+00:00", "2026-06-01T12:00:00.123456+00:00"),
        ],
    )
    def test_converts_offsets_and_naive_values_to_utc(self, raw, expected):
        assert to_utc(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "no es fecha", "2026-02-30T00:00:00", 12345,
                                     "0001-01-01T00:00:00+14:00"])
    def test_returns_none_for_unparseable_values(self, raw):
        assert to_utc(raw) is None


class TestAgents:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("claude", "claude"),
            ("claude-code", "claude"),
            ("Claude_Code", "claude"),
            ("codex", "codex"),
            ("codex-cli", "codex"),
            ("copilot", "copilot"),
            ("copilot-cli", "copilot"),
            ("github-copilot", "copilot"),
            ("gemini", "gemini"),
        ],
    )
    def test_maps_known_aliases_to_the_catalog(self, raw, expected):
        assert normalize_agent(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "deepseek", "texto libre de otra cosa", 7])
    def test_unknown_values_fall_into_no_agent(self, raw):
        assert normalize_agent(raw) == "sin agente"


class TestReferences:
    def test_sha_grammar(self):
        notes = (
            "Commits 5BE88D0 y 7d03e1b; repetido 5be88d0. "
            "deadbeef no tiene dígitos, 1234567 no tiene letras, "
            "x7d03e1c pegado a una letra no cuenta, abc123 es corto, "
            f"completo {SHA_A}."
        )

        refs = extract_references(notes)

        assert refs["sha_candidates"] == ["5be88d0", "7d03e1b", SHA_A]

    def test_ignores_tokens_longer_than_a_sha(self):
        assert extract_references("a" * 20 + "1" * 21)["sha_candidates"] == []

    def test_pr_grammar(self):
        refs = extract_references("PR #29, pr29, PR 30, Pr#31 y de nuevo PR #29. PRs #40 no cuenta.")

        assert refs["prs"] == [29, 30, 31]

    @pytest.mark.parametrize(
        "notes, expected",
        [("Suite: 536 passed", True), ("corrí pytest", True), ("agregué un test", True),
         ("sin verificación", False), ("contest", False), (None, False)],
    )
    def test_mentions_tests(self, notes, expected):
        assert extract_references(notes)["mentions_tests"] is expected


class TestCommitIndex:
    def test_resolves_a_unique_prefix_and_rejects_an_ambiguous_one(self):
        index = CommitIndex([SHA_A, SHA_C1, SHA_C2])

        assert index.resolve("a1b2c3d") == SHA_A
        assert index.resolve("A1B2C3D") == SHA_A
        assert index.resolve("c0ffee1") is None
        assert index.resolve("c0ffee12345") == SHA_C1
        assert index.resolve("fffffff") is None

    def test_reads_imported_commits_from_runs(self, conn):
        _commit(conn, SHA_A)
        _commit(conn, SHA_A, alias="otro-proyecto")
        conn.execute("INSERT INTO runs (ts, project, session_id) VALUES ('2026-05-01', 'p', 'git::roto')")
        conn.execute("INSERT INTO runs (ts, project, session_id) VALUES ('2026-05-01', 'p', 'sesion-claude')")

        index = CommitIndex.from_db(conn)

        assert index.resolve("a1b2c3d") == SHA_A

    def test_step_references_split_verified_and_unverified(self):
        refs = step_references(f"commits a1b2c3d, {SHA_A}, c0ffee1 y 9f9f9f9; PR #12; tests ok",
                               CommitIndex([SHA_A, SHA_C1, SHA_C2]))

        assert refs == {
            "verified_commits": [SHA_A],
            "unverified_shas": ["c0ffee1", "9f9f9f9"],
            "prs": [12],
            "mentions_tests": True,
        }


class TestContextGraph:
    def _build(self, conn):
        ctx = _context(conn)
        s1 = _step(conn, ctx, 1, provider="claude-code", notes=f"Hecho en {SHA_A[:7]}. PR #5. pytest ok")
        s2 = _step(conn, ctx, 2, provider="", notes=f"Sigue {SHA_A[:9]} y {SHA_B[:8]}; c0ffee1 ambiguo")
        s3 = _step(conn, ctx, 2, provider="texto dañado con datos privados", notes="sin referencias",
                   status="pending")
        conn.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint) "
                     "VALUES ('2026-05-02T00:00:00Z', ?, ?, 'codex', 1, 'checkpoint privado')", (s2, ctx))
        conn.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint) "
                     "VALUES ('2026-05-02T00:01:00Z', ?, ?, 'github-copilot', 0, 'x')", (s2, ctx))
        conn.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint) "
                     "VALUES ('2026-05-02T00:02:00Z', ?, ?, 'codex-cli', 1, 'y')", (s1, ctx))
        conn.execute("INSERT INTO runs (ts, project, provider, status, cost_usd, step_id, task, response) "
                     "VALUES ('2026-05-02T00:00:00Z', 'mi-proyecto', 'claude', 'done', 1.25, ?, "
                     "'tarea privada', 'respuesta privada')", (s1,))
        conn.execute("INSERT INTO runs (ts, project, provider, status, cost_usd, step_id) "
                     "VALUES ('2026-05-02T00:00:00Z', 'mi-proyecto', 'claude', 'done', 0.75, ?)", (s1,))
        index = CommitIndex([SHA_A, SHA_B, SHA_C1, SHA_C2])
        return ctx, (s1, s2, s3), index

    def test_projects_steps_lanes_counts_and_verified_commits(self, conn):
        ctx, (s1, s2, s3), index = self._build(conn)

        graph = context_graph(conn, ctx, commits=index, now=NOW)

        _validate(graph, "project_graph.schema.json")
        nodes = {node["id"]: node for node in graph["nodes"]}
        assert graph["metadata"] == {"project": "mi-proyecto", "context_id": ctx,
                                     "generated_at": "2026-06-01T12:00:00+00:00"}
        assert [n["id"] for n in graph["nodes"] if n["kind"] == "step"] == [
            f"step:{s1}", f"step:{s2}", f"step:{s3}"]
        assert nodes[f"step:{s1}"]["attrs"] == {
            "idx": 1, "order_idx": 1, "lane": "claude", "secondary": ["codex"],
            "alignments": 1, "deviations": 0, "runs": 2, "cost_usd": 2.0,
            "prs": [5], "unverified_shas": 0, "mentions_tests": True,
        }
        step2 = nodes[f"step:{s2}"]["attrs"]
        assert (step2["lane"], step2["secondary"], step2["deviations"]) == ("codex", ["copilot"], 1)
        assert step2["unverified_shas"] == 1
        assert nodes[f"step:{s3}"]["attrs"]["lane"] == "sin agente"
        assert nodes[f"step:{s3}"]["state"] == "pending"

    def test_shared_commit_is_one_node_with_one_edge_per_citing_step(self, conn):
        ctx, (s1, s2, _), index = self._build(conn)

        graph = context_graph(conn, ctx, commits=index, now=NOW)

        commits = [n for n in graph["nodes"] if n["kind"] == "commit"]
        assert commits == [
            {"id": f"commit:{SHA_A}", "kind": "commit", "label": SHA_A[:7]},
            {"id": f"commit:{SHA_B}", "kind": "commit", "label": SHA_B[:7]},
        ]
        cites = [(e["source"], e["target"]) for e in graph["edges"] if e["relation_type"] == "cites"]
        assert cites == [
            (f"step:{s1}", f"commit:{SHA_A}"),
            (f"step:{s2}", f"commit:{SHA_A}"),
            (f"step:{s2}", f"commit:{SHA_B}"),
        ]
        assert {e["origin"] for e in graph["edges"] if e["relation_type"] == "cites"} == {"verified_reference"}

    def test_contains_no_free_text(self, conn):
        ctx, _, index = self._build(conn)

        payload = json.dumps(context_graph(conn, ctx, commits=index, now=NOW), ensure_ascii=False)

        for text in ("titulo privado", "titulo de paso", "Hecho en", "checkpoint privado",
                     "tarea privada", "respuesta privada", "texto dañado"):
            assert text not in payload

    def test_unknown_context_returns_none(self, conn):
        assert context_graph(conn, 999, commits=CommitIndex([]), now=NOW) is None

    def test_builds_the_commit_index_from_the_database_by_default(self, conn):
        _commit(conn, SHA_B)
        ctx = _context(conn)
        _step(conn, ctx, 1, notes=f"ver {SHA_B[:7]}")

        graph = context_graph(conn, ctx, now=NOW)

        assert f"commit:{SHA_B}" in {n["id"] for n in graph["nodes"]}


class TestActivity:
    def _seed(self, conn):
        ctx = _context(conn)
        other = _context(conn, project="otro-proyecto")
        step = _step(conn, ctx, 1, provider="codex", started_at="2026-06-01T08:30:00",
                     completed_at="2026-06-01T09:10:00-03:00")
        _step(conn, other, 1, started_at="2026-06-01T11:00:00Z")
        ids = {}
        ids["run"] = conn.execute(
            "INSERT INTO runs (ts, project, provider, model, status, step_id, task) VALUES "
            "('2026-06-01T09:00:00-03:00', 'mi-proyecto', 'claude', 'opus', 'done', ?, 'tarea privada')",
            (step,)).lastrowid
        ids["git"] = conn.execute(
            "INSERT INTO runs (ts, project, provider, status) VALUES "
            "('2026-06-01T08:59:00-04:00', 'mi-proyecto', 'git', 'done')").lastrowid
        conn.execute("INSERT INTO runs (ts, project, provider, status) VALUES "
                     "('2026-06-01T11:30:00+00:00', 'otro-proyecto', 'claude', 'done')")
        conn.execute("INSERT INTO runs (ts, project, provider, status) VALUES "
                     "('no es fecha', 'mi-proyecto', 'claude', 'done')")
        conn.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint) VALUES "
                     "('2026-06-01T12:00:00Z', ?, ?, 'claude-code', 0, 'checkpoint privado')", (step, ctx))
        conn.execute("INSERT INTO tool_calls (ts, step_id, context_id, tool_name, status) VALUES "
                     "('2026-06-01T12:00:00Z', ?, ?, 'pytest', 'ok')", (step, ctx))
        conn.execute("INSERT INTO egress_decisions (ts, project, provider, phase, decision, reason_code) VALUES "
                     "('2026-06-01T12:00:00Z', 'mi-proyecto', 'claude', 'pre', 'allow', 'policy_ok')")
        _mcp(conn, "2026-06-01T11:45:00Z", "r1", "advance_step", "workflow", "claude-code")
        _mcp(conn, "2026-06-01T11:46:00Z", "r2", "get_context", "read", "codex")
        return ctx, step, ids

    def test_orders_by_utc_instant_across_offsets_and_sources(self, conn):
        self._seed(conn)

        result = activity(conn, "mi-proyecto", now=NOW)

        _validate(result, "activity.schema.json")
        assert [(e["kind"], e["ts"]) for e in result["events"]] == [
            ("run", "2026-06-01T12:59:00+00:00"),
            ("step_completed", "2026-06-01T12:10:00+00:00"),
            ("run", "2026-06-01T12:00:00+00:00"),
            ("egress_decision", "2026-06-01T12:00:00+00:00"),
            ("tool_call", "2026-06-01T12:00:00+00:00"),
            ("alignment", "2026-06-01T12:00:00+00:00"),
            ("mcp_invocation", "2026-06-01T11:45:00+00:00"),
            ("step_started", "2026-06-01T08:30:00+00:00"),
        ]
        assert result["metadata"]["skipped_invalid_ts"] == 1
        assert result["metadata"]["truncated"] is False

    def test_event_fields_carry_references_without_free_text(self, conn):
        ctx, step, ids = self._seed(conn)

        result = activity(conn, "mi-proyecto", now=NOW)
        events = {e["id"]: e for e in result["events"]}

        assert events[f"run:{ids['run']}"] == {
            "id": f"run:{ids['run']}", "kind": "run", "ts": "2026-06-01T12:00:00+00:00",
            "ref": f"step:{step}", "context_id": None, "agent": "claude",
            "label": "claude/opus", "state": "done",
        }
        alignment = next(e for e in result["events"] if e["kind"] == "alignment")
        assert (alignment["agent"], alignment["state"], alignment["context_id"]) == ("claude", "deviation", ctx)
        assert next(e for e in result["events"] if e["kind"] == "mcp_invocation")["agent"] == "claude"
        payload = json.dumps(result, ensure_ascii=False)
        assert "tarea privada" not in payload
        assert "checkpoint privado" not in payload

    def test_window_is_inclusive_since_and_exclusive_until_by_instant(self, conn):
        self._seed(conn)

        result = activity(conn, "mi-proyecto", since="2026-06-01T08:00:00-04:00",
                          until="2026-06-01T12:59:00Z", now=NOW)

        assert [e["kind"] for e in result["events"]] == [
            "step_completed", "run", "egress_decision", "tool_call", "alignment"]
        assert result["metadata"]["since"] == "2026-06-01T12:00:00+00:00"
        assert result["metadata"]["until"] == "2026-06-01T12:59:00+00:00"

    def test_limit_truncates_and_reports_it(self, conn):
        self._seed(conn)

        result = activity(conn, "mi-proyecto", limit=3, now=NOW)

        assert len(result["events"]) == 3
        assert result["metadata"]["truncated"] is True

    @pytest.mark.parametrize("bad", [{"since": "ayer"}, {"until": "2026-13-01"}])
    def test_rejects_invalid_window_bounds(self, conn, bad):
        with pytest.raises(ValueError):
            activity(conn, "mi-proyecto", **bad)

    def test_unknown_project_is_empty(self, conn):
        self._seed(conn)

        result = activity(conn, "sin-datos", now=NOW)

        assert result["events"] == []
        _validate(result, "activity.schema.json")
