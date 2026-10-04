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
    step_lanes,
    step_references,
    to_utc,
)

SCHEMAS = Path(projections.__file__).parent / "schemas"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

SHA_A = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_B = "b1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_C1 = "c0ffee1234567890abcdef1234567890abcdef12"
SHA_C2 = "c0ffee1299999999abcdef1234567890abcdef12"
SHA_256 = "d" * 10 + "0123456789abcdef" * 3 + "e" * 6


def _schema(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _validate(instance, name):
    jsonschema.validate(
        instance, _schema(name), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )


def _empty_db():
    """Base en memoria con el esquema real de la aplicación y sin datos."""
    from orchestrator.db import _conn

    target = sqlite3.connect(":memory:")
    for (sql,) in _conn().execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
    ).fetchall():
        target.execute(sql)
    return target


@pytest.fixture
def conn():
    db = _empty_db()
    yield db
    db.close()


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


def _alignment(conn, step_id, context_id, agent, ts="2026-05-02T00:00:00Z", confirmed=1):
    return conn.execute(
        "INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint) "
        "VALUES (?, ?, ?, ?, ?, 'checkpoint privado')",
        (ts, step_id, context_id, agent, confirmed),
    ).lastrowid


def _commit(conn, sha, alias="mi-proyecto"):
    conn.execute(
        "INSERT INTO runs (ts, project, provider, status, session_id) VALUES (?, ?, 'git', 'done', ?)",
        ("2026-05-01T00:00:00-03:00", alias, f"git::{alias}::{sha}"),
    )


def _mcp(conn, ts, request_id, tool_name, category, surface, project="mi-proyecto"):
    return conn.execute(
        "INSERT INTO mcp_invocations (ts, request_id, server_instance_id, client_surface, transport, "
        "capability_profile, tool_name, tool_category, project, input_hash, output_hash, status, "
        "created_at) VALUES (?, ?, 'srv', ?, 'stdio', 'workflow_operator', ?, ?, ?, 'h', 'h', "
        "'success', ?)",
        (ts, request_id, surface, tool_name, category, project, ts),
    ).lastrowid


class TestTimestamps:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("2026-06-01T09:00:00-03:00", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01T08:00:00-04:00", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01T12:00:00Z", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01T12:00:00", "2026-06-01T12:00:00+00:00"),
            ("2026-06-01 12:00:00-03:00", "2026-06-01T15:00:00+00:00"),
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
            ("claude", "claude"), ("claude-code", "claude"), ("claude_code", "claude"),
            ("  Claude-Code ", "claude"), ("codex", "codex"), ("CODEX_CLI", "codex"),
            ("copilot", "copilot"), ("copilot-cli", "copilot"), ("github-copilot", "copilot"),
            ("deepseek", "otros"), ("openai", "otros"), ("gemini", "otros"),
        ],
    )
    def test_maps_the_section_21_1_aliases_exactly(self, raw, expected):
        assert normalize_agent(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "codex-cli", "claude code", "my-claude-bot", "other",
                                     "texto dañado con datos", 7])
    def test_anything_outside_the_catalog_is_no_agent(self, raw):
        assert normalize_agent(raw) == "sin agente"


class TestStepLanes:
    def test_provider_in_catalog_wins(self):
        lane, secondary = step_lanes("codex", [("2026-05-02T00:00:00Z", 1, "claude"),
                                               ("2026-05-02T00:01:00Z", 2, "claude")])

        assert (lane, secondary) == ("codex", ["claude"])

    def test_most_alignments_wins_without_provider(self):
        lane, secondary = step_lanes("", [("2026-05-02T00:00:00Z", 1, "copilot"),
                                          ("2026-05-02T00:01:00Z", 2, "codex"),
                                          ("2026-05-02T00:02:00Z", 3, "codex")])

        assert (lane, secondary) == ("codex", ["copilot"])

    def test_tie_goes_to_the_first_alignment_by_instant_then_id(self):
        alignments = [
            ("2026-05-02T00:00:00-03:00", 1, "claude"),
            ("2026-05-02T01:00:00Z", 2, "copilot"),
        ]

        assert step_lanes(None, alignments)[0] == "copilot"
        assert step_lanes(None, list(reversed(alignments)))[0] == "copilot"
        same_instant = [("2026-05-02T00:00:00Z", 9, "codex"), ("2026-05-02T00:00:00Z", 4, "claude")]
        assert step_lanes(None, same_instant)[0] == "claude"

    def test_unknown_provider_is_ignored_and_no_alignments_is_no_agent(self):
        assert step_lanes("texto dañado", []) == ("sin agente", [])


class TestReferences:
    def test_sha_grammar(self):
        notes = (
            "Commits 5BE88D0 y 7d03e1b; repetido 5be88d0. "
            "deadbeef no tiene dígitos, 1234567 no tiene letras, "
            "x7d03e1c pegado a una letra no cuenta, abc123 es corto, "
            f"completo {SHA_A}."
        )

        assert extract_references(notes)["sha_candidates"] == ["5be88d0", "7d03e1b", SHA_A]

    def test_ignores_tokens_longer_than_40(self):
        assert extract_references("a" * 20 + "1" * 21)["sha_candidates"] == []

    def test_pr_grammar(self):
        refs = extract_references("PR #29, pr29, PR 30, Pr#31 y de nuevo PR #29. PRs #40 no cuenta.")

        assert refs["prs"] == [29, 30, 31]

    def test_pr_numbers_longer_than_nine_digits_are_ignored(self):
        refs = extract_references("PR #" + "9" * 5000 + " y PR #1234567890, pero PR #123456789 sí")

        assert refs["prs"] == [123456789]

    @pytest.mark.parametrize(
        "notes, expected",
        [("Suite: 536 passed", True), ("corrí pytest", True), ("agregué un test", True),
         ("sin verificación", False), ("contest", False), (None, False)],
    )
    def test_mentions_tests(self, notes, expected):
        assert extract_references(notes)["mentions_tests"] is expected


class TestCommitIndex:
    def test_resolves_a_unique_prefix_and_rejects_an_ambiguous_one(self):
        index = CommitIndex([SHA_A, SHA_C1, SHA_C2, SHA_256])

        assert index.resolve("a1b2c3d") == SHA_A
        assert index.resolve("A1B2C3D") == SHA_A
        assert index.resolve("c0ffee1") is None
        assert index.resolve("c0ffee12345") == SHA_C1
        assert index.resolve(SHA_256[:12]) == SHA_256
        assert index.resolve("fffffff") is None

    def test_only_accepts_full_hex_shas(self):
        index = CommitIndex([SHA_A, "a1b2c3d", "texto libre", SHA_A.upper(), "g" * 40, None])

        assert len(index) == 1

    def test_reads_imported_commits_from_runs_and_skips_malformed_session_ids(self, conn):
        _commit(conn, SHA_A)
        _commit(conn, SHA_A, alias="otro-proyecto")
        _commit(conn, SHA_B, alias="equipo::web")
        _commit(conn, SHA_256)
        for session_id in ("git::roto", "git::p::texto libre privado", "git::::" + SHA_C2,
                           "git::a::b::" + SHA_C2, "git::otro::" + SHA_C2, "sesion-claude"):
            conn.execute("INSERT INTO runs (ts, project, provider, session_id) "
                         "VALUES ('2026-05-01', 'p', 'git', ?)", (session_id,))
        conn.execute("INSERT INTO runs (ts, project, provider, session_id) "
                     "VALUES ('2026-05-01', 'mi-proyecto', 'claude-code', ?)", (f"git::mi-proyecto::{SHA_C1}",))

        index = CommitIndex.from_db(conn)

        assert len(index) == 3
        assert index.resolve("a1b2c3d") == SHA_A
        assert index.resolve(SHA_B[:7]) == SHA_B
        assert index.resolve(SHA_C2) is None
        assert index.resolve(SHA_C1) is None

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
        _alignment(conn, s2, ctx, "codex", ts="2026-05-02T00:00:00Z")
        _alignment(conn, s2, ctx, "github-copilot", ts="2026-05-02T00:01:00Z", confirmed=0)
        _alignment(conn, s1, ctx, "codex_cli", ts="2026-05-02T00:02:00Z")
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

    def test_duplicate_order_idx_is_broken_by_step_id(self, conn):
        ctx = _context(conn)
        later = _step(conn, ctx, 5)
        first = _step(conn, ctx, 1)
        same = _step(conn, ctx, 5)

        graph = context_graph(conn, ctx, commits=CommitIndex([]), now=NOW)

        steps = [n for n in graph["nodes"] if n["kind"] == "step"]
        assert [n["id"] for n in steps] == [f"step:{first}", f"step:{later}", f"step:{same}"]
        assert [n["attrs"]["idx"] for n in steps] == [1, 2, 3]

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

    def test_contains_no_free_text(self, conn):
        ctx, _, index = self._build(conn)
        conn.execute("UPDATE contexts SET status = 'estado con texto libre' WHERE id = ?", (ctx,))

        graph = context_graph(conn, ctx, commits=index, now=NOW)
        payload = json.dumps(graph, ensure_ascii=False)

        for text in ("titulo privado", "titulo de paso", "Hecho en", "checkpoint privado",
                     "tarea privada", "respuesta privada", "texto dañado", "texto libre"):
            assert text not in payload
        assert graph["nodes"][0]["state"] == "otro"
        _validate(graph, "project_graph.schema.json")

    def test_context_without_steps(self, conn):
        ctx = _context(conn)

        graph = context_graph(conn, ctx, commits=CommitIndex([]), now=NOW)

        assert [n["kind"] for n in graph["nodes"]] == ["context"]
        assert graph["edges"] == []
        _validate(graph, "project_graph.schema.json")

    def test_unknown_context_returns_none(self, conn):
        assert context_graph(conn, 999, commits=CommitIndex([]), now=NOW) is None

    def test_negative_or_infinite_costs_do_not_break_the_schema(self, conn):
        ctx = _context(conn)
        step = _step(conn, ctx, 1)
        for cost in (2.5, -1.25, 9e999, -9e999, 1000000000000001.0, None, "texto"):
            conn.execute("INSERT INTO runs (ts, project, status, cost_usd, step_id) "
                         "VALUES ('2026-05-02T00:00:00Z', 'mi-proyecto', 'done', ?, ?)", (cost, step))

        graph = context_graph(conn, ctx, commits=CommitIndex([]), now=NOW)

        attrs = graph["nodes"][1]["attrs"]
        assert (attrs["runs"], attrs["cost_usd"]) == (7, 1000000000000003.5)
        _validate(graph, "project_graph.schema.json")

    def test_a_sum_that_overflows_is_null_and_still_valid_json(self, conn):
        ctx = _context(conn)
        step = _step(conn, ctx, 1)
        for _ in range(2):
            conn.execute("INSERT INTO runs (ts, project, status, cost_usd, step_id) "
                         "VALUES ('2026-05-02T00:00:00Z', 'mi-proyecto', 'done', 1e308, ?)", (step,))

        graph = context_graph(conn, ctx, commits=CommitIndex([]), now=NOW)

        assert graph["nodes"][1]["attrs"]["cost_usd"] is None
        json.dumps(graph, allow_nan=False)
        _validate(graph, "project_graph.schema.json")

    def test_builds_the_commit_index_from_the_database_by_default(self, conn):
        _commit(conn, SHA_B)
        ctx = _context(conn)
        _step(conn, ctx, 1, notes=f"ver {SHA_B[:7]}")

        graph = context_graph(conn, ctx, now=NOW)

        assert f"commit:{SHA_B}" in {n["id"] for n in graph["nodes"]}

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda g: g["nodes"].append({"id": f"commit:{SHA_A}", "kind": "commit", "label": "a1b2c3d",
                                         "attrs": {}}),
            lambda g: g["nodes"].append({"id": "step:1", "kind": "step", "label": "Paso 1"}),
            lambda g: g["nodes"].append({"id": "commit:texto", "kind": "commit", "label": "texto"}),
            lambda g: g["nodes"][0].update(label="titulo privado"),
            lambda g: g["metadata"].update(extra="x"),
            lambda g: g.update(map={}),
            lambda g: g["edges"].append({"source": "step:1", "target": "portal:otro", "relation_type": "cites",
                                         "origin": "verified_reference", "confidence": 1.0,
                                         "evidence_ref": "steps.notes"}),
        ],
    )
    def test_schema_rejects_contract_violations(self, conn, mutate):
        ctx, _, index = self._build(conn)
        graph = context_graph(conn, ctx, commits=index, now=NOW)

        mutate(graph)

        with pytest.raises(jsonschema.ValidationError):
            _validate(graph, "project_graph.schema.json")


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
        _alignment(conn, step, ctx, "claude-code", ts="2026-06-01T12:00:00Z", confirmed=0)
        conn.execute("INSERT INTO tool_calls (ts, step_id, context_id, tool_name, status) VALUES "
                     "('2026-06-01T12:00:00Z', ?, ?, 'pytest', 'ok')", (step, ctx))
        conn.execute("INSERT INTO egress_decisions (ts, project, provider, phase, decision, reason_code) VALUES "
                     "('2026-06-01T12:00:00Z', 'mi-proyecto', 'claude', 'pre', 'allow', 'policy_ok')")
        _mcp(conn, "2026-06-01T11:45:00Z", "r1", "advance_step", "workflow_transition", "claude_code")
        _mcp(conn, "2026-06-01T11:46:00Z", "r2", "get_context", "read", "codex_cli")
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

    def test_free_text_in_identifier_columns_never_reaches_the_dto(self, conn):
        ctx = _context(conn)
        step = _step(conn, ctx, 1, provider="texto dañado del proveedor",
                     started_at="2026-06-01T10:00:00Z")
        conn.execute("INSERT INTO runs (ts, project, provider, model, status) VALUES "
                     "('2026-06-01T10:00:01Z', 'mi-proyecto', 'proveedor con espacios', "
                     "'modelo <script>', 'estado libre privado')")
        conn.execute("INSERT INTO tool_calls (ts, step_id, context_id, tool_name, status) VALUES "
                     "('2026-06-01T10:00:02Z', ?, ?, 'Revisé el archivo privado', 'hecho a mano')",
                     (step, ctx))
        conn.execute("INSERT INTO egress_decisions (ts, project, provider, phase, decision, reason_code) VALUES "
                     "('2026-06-01T10:00:03Z', 'mi-proyecto', 'x', 'fase libre', 'deny', 'motivo libre')")
        _mcp(conn, "2026-06-01T10:00:04Z", "r", "herramienta inventada!", "workflow_mutation", "otro cliente")

        result = activity(conn, "mi-proyecto", now=NOW)

        _validate(result, "activity.schema.json")
        payload = json.dumps(result, ensure_ascii=False)
        for text in ("dañado", "espacios", "script", "libre", "privado", "inventada", "otro cliente"):
            assert text not in payload
        labels = {e["kind"]: (e["label"], e["state"]) for e in result["events"]}
        assert labels["run"] == ("run", "otro")
        assert labels["tool_call"] == ("tool_call", "otro")
        assert labels["egress_decision"] == ("egress", "deny")
        assert labels["mcp_invocation"] == ("mcp", "success")

    def test_imported_commit_label_does_not_carry_the_author(self, conn):
        conn.execute("INSERT INTO runs (ts, project, provider, model, status, session_id) VALUES "
                     "('2026-06-01T10:00:00Z', 'mi-proyecto', 'git', 'autor-privado', 'done', ?)",
                     (f"git::mi-proyecto::{SHA_A}",))

        event = activity(conn, "mi-proyecto", now=NOW)["events"][0]

        assert event["label"] == "git"
        assert "autor-privado" not in json.dumps(event)

    def test_window_is_inclusive_since_and_exclusive_until_by_instant(self, conn):
        self._seed(conn)

        result = activity(conn, "mi-proyecto", since="2026-06-01T08:00:00-04:00",
                          until="2026-06-01T12:59:00Z", now=NOW)

        assert [e["kind"] for e in result["events"]] == [
            "step_completed", "run", "egress_decision", "tool_call", "alignment"]
        assert result["metadata"]["since"] == "2026-06-01T12:00:00+00:00"
        assert result["metadata"]["until"] == "2026-06-01T12:59:00+00:00"
        assert result["metadata"]["skipped_invalid_ts"] == 1

    def test_negative_or_non_integer_order_idx_keeps_the_label_inside_the_schema(self, conn):
        ctx = _context(conn)
        _step(conn, ctx, -1, started_at="2026-06-01T10:00:00Z")
        _step(conn, ctx, "x", started_at="2026-06-01T10:00:01Z")

        result = activity(conn, "mi-proyecto", now=NOW)

        _validate(result, "activity.schema.json")
        assert [e["label"] for e in result["events"]] == ["paso", "paso"]

    def test_every_row_is_either_returned_or_counted_as_invalid(self, conn):
        for ts in ("2026-06-01T12:00:00Z", "20260601T120000+0000", "2026-06-01 12:00:00", "mal"):
            conn.execute("INSERT INTO runs (ts, project, status) VALUES (?, 'mi-proyecto', 'done')", (ts,))

        result = activity(conn, "mi-proyecto", now=NOW)

        assert len(result["events"]) + result["metadata"]["skipped_invalid_ts"] == 4
        assert result["metadata"]["skipped_invalid_ts"] >= 1

    def test_ties_are_deterministic_regardless_of_insertion_order(self):
        def build(reverse):
            db = _empty_db()
            ctx = _context(db)
            step = _step(db, ctx, 1, completed_at="2026-06-01T12:00:00Z")
            inserts = [
                lambda: db.execute("INSERT INTO runs (id, ts, project, status) VALUES "
                                   "(7, '2026-06-01T09:00:00-03:00', 'mi-proyecto', 'done')"),
                lambda: db.execute("INSERT INTO runs (id, ts, project, status) VALUES "
                                   "(3, '2026-06-01T12:00:00Z', 'mi-proyecto', 'done')"),
                lambda: _alignment(db, step, ctx, "codex", ts="2026-06-01T08:00:00-04:00"),
                lambda: _mcp(db, "2026-06-01T12:00:00Z", "r", "add_step", "workflow_mutation", "codex_cli"),
            ]
            for insert in (reversed(inserts) if reverse else inserts):
                insert()
            events = [e["id"] for e in activity(db, "mi-proyecto", now=NOW)["events"]]
            db.close()
            return events

        expected = ["run:7", "run:3", "alignment:1", "mcp_invocation:1", "step_completed:1"]
        assert build(False) == expected
        assert build(True) == expected

    def test_limit_truncates_and_reports_it(self, conn):
        self._seed(conn)

        result = activity(conn, "mi-proyecto", limit=3, now=NOW)

        assert len(result["events"]) == 3
        assert result["metadata"]["truncated"] is True

    def test_cursor_pages_through_ties_without_losing_or_repeating_events(self, conn):
        self._seed(conn)
        full = [e["id"] for e in activity(conn, "mi-proyecto", now=NOW)["events"]]

        pages, cursor = [], None
        while True:
            page = activity(conn, "mi-proyecto", limit=3, cursor=cursor, now=NOW)
            _validate(page, "activity.schema.json")
            pages.append([e["id"] for e in page["events"]])
            cursor = page["metadata"]["next_cursor"]
            if cursor is None:
                break

        assert [len(p) for p in pages] == [3, 3, 2]
        assert pages[0][2].startswith("run:") and pages[1][0].startswith("egress_decision:")
        assert [i for p in pages for i in p] == full

    def test_step_events_use_the_same_lane_as_the_context_graph(self, conn):
        ctx = _context(conn)
        step = _step(conn, ctx, 1, provider="texto dañado", started_at="2026-06-01T10:00:00Z",
                     completed_at="2026-06-01T11:00:00Z")
        _alignment(conn, step, ctx, "copilot", ts="2026-06-01T10:30:00Z")
        _alignment(conn, step, ctx, "codex_cli", ts="2026-06-01T10:10:00Z")

        events = activity(conn, "mi-proyecto", now=NOW)["events"]
        graph = context_graph(conn, ctx, commits=CommitIndex([]), now=NOW)

        lane = graph["nodes"][1]["attrs"]["lane"]
        assert lane == "codex"
        assert {e["agent"] for e in events if e["kind"].startswith("step_")} == {lane}

    def test_egress_events_carry_the_normalized_provider(self, conn):
        self._seed(conn)

        event = next(e for e in activity(conn, "mi-proyecto", now=NOW)["events"]
                     if e["kind"] == "egress_decision")

        assert event["agent"] == "claude"

    @pytest.mark.parametrize("bad", ["x", "2026-06-01T12:00:00Z|run", "ayer|run|1",
                                     "2026-06-01T12:00:00Z|otro|1", "2026-06-01T12:00:00Z|run|-1"])
    def test_rejects_an_invalid_cursor(self, conn, bad):
        with pytest.raises(ValueError):
            activity(conn, "mi-proyecto", cursor=bad)

    @pytest.mark.parametrize("bad", [{"since": "ayer"}, {"until": "2026-13-01"}])
    def test_rejects_invalid_window_bounds(self, conn, bad):
        with pytest.raises(ValueError):
            activity(conn, "mi-proyecto", **bad)

    def test_unknown_project_is_empty(self, conn):
        self._seed(conn)

        result = activity(conn, "sin-datos", now=NOW)

        assert result["events"] == []
        _validate(result, "activity.schema.json")


def test_sha256_citations_are_candidates_but_41_to_63_hex_characters_are_not():
    sha = "e" * 8 + "0123456789abcdef" * 3 + "f" * 8
    assert extract_references(f"commit {sha}")["sha_candidates"] == [sha]
    assert extract_references("a" * 20 + "1" * 43)["sha_candidates"] == []
