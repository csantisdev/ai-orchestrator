"""Trabajos y presupuesto de los comandos de la UI (RFC-010 §3.3, §3.5): I7, I13, I14, I15."""

import json
import uuid

import pytest

from orchestrator import commands
from orchestrator.commands import budget, catalog, jobs
from orchestrator.commands.catalog import Command
from orchestrator.commands.policy import write_ui_config
from orchestrator.db import _conn
from orchestrator.mcp_governance import ExecutionIdentity

PROJECT = "mi-proyecto"


def _identity(profile="admin", projects=(PROJECT,)):
    return ExecutionIdentity("dashboard", "http", None, profile, frozenset(projects))


def _body(args, **extra):
    return {"request_id": str(uuid.uuid4()), "args": args, **extra}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Proyecto registrado, UI admin sobre él y trabajos que no arrancan solos."""
    import orchestrator.index as index_module
    import orchestrator.paths as paths
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(index_module, "list_projects", lambda: {PROJECT: str(tmp_path)})
    write_ui_config("admin", [PROJECT])
    pending = []
    monkeypatch.setattr(jobs, "_spawn", pending.append)
    monkeypatch.setattr(jobs, "start_heartbeat", lambda: None)
    events = []
    from orchestrator.sse import BUS
    monkeypatch.setattr(BUS, "publish", lambda kind, data: events.append((kind, json.loads(data))))
    _orphan_all()
    yield {"pending": pending, "events": events, "monkeypatch": monkeypatch}
    _orphan_all()


def _orphan_all():
    """Deja los trabajos activos de otros tests como de un ejecutor muerto y los reconcilia."""
    _conn().execute("UPDATE jobs SET executor='muerto', heartbeat_at='2000-01-01T00:00:00+00:00' "
                    "WHERE status IN ('queued', 'running')")
    _conn().commit()
    jobs.reconcile()


def _as_dead_executor(*job_ids):
    for job_id in job_ids:
        _conn().execute("UPDATE jobs SET executor='servidor-muerto', heartbeat_at='2000-01-01T00:00:00+00:00' "
                        "WHERE id=?", (job_id,))
    _conn().commit()


def _fake_job(monkeypatch, name="fake_job", resources=("shared",), calls=None, fail=False, **extra):
    calls = [] if calls is None else calls

    def work(job, args, project):
        job.stage("working")
        calls.append(args)
        if fail:
            raise RuntimeError("falla del trabajo")
        return {"counts": {"items": 3}}

    command = Command(
        name=name, category=extra.pop("category", "maintenance"),
        schema={"type": "object", "properties": {"n": {"type": "integer"}, "context_id": {"type": "integer"}}},
        owner=extra.pop("owner", None), job=work,
        resources=lambda args, project: list(resources), **extra,
    )
    monkeypatch.setitem(catalog.CATALOG, name, command)
    return calls


def _drain(pending):
    while pending:
        pending.pop(0)()


def _job(job_id):
    return _conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def _record(request_id):
    return _conn().execute("SELECT * FROM ui_commands WHERE request_id=?", (request_id,)).fetchone()


def _reservation(request_id):
    return _conn().execute("SELECT * FROM budget_reservations WHERE request_id=?", (request_id,)).fetchone()


# ── Ciclo de un trabajo ──────────────────────────────────────────────────────

def test_job_is_accepted_runs_once_and_leaves_its_receipt(env):
    calls = _fake_job(env["monkeypatch"])
    body = _body({"n": 1})
    status, payload = commands.execute("fake_job", body, _identity())
    assert status == 202 and payload["status"] == "accepted" and payload["job_id"]
    job_id = payload["job_id"]
    assert _job(job_id)["status"] == "queued" and _record(body["request_id"])["status"] == "queued"

    again = commands.execute("fake_job", body, _identity())
    assert again[0] == 202 and again[1]["job_id"] == job_id

    _drain(env["pending"])
    assert calls == [{"n": 1}]
    job, record = _job(job_id), _record(body["request_id"])
    assert job["status"] == "done" and job["started_at"] and job["finished_at"]
    assert record["status"] == "ok" and record["receipt_hash"] == job["receipt_hash"]

    status, replay = commands.execute("fake_job", body, _identity())
    assert status == 200 and replay["receipt"]["replayed"] and replay["receipt"]["receipt_hash"] == job["receipt_hash"]
    assert calls == [{"n": 1}]

    stages = [(event["status"], event["stage"]) for kind, event in env["events"] if kind == "job_stage"]
    assert stages == [("queued", None), ("running", None), ("running", "working"), ("done", None)]


def test_failed_job_records_an_error_without_its_message(env):
    _fake_job(env["monkeypatch"], fail=True)
    body = _body({})
    job_id = commands.execute("fake_job", body, _identity())[1]["job_id"]
    _drain(env["pending"])
    assert _job(job_id)["status"] == "failed"
    record = _record(body["request_id"])
    assert record["status"] == "error" and record["reason_code"] == "execution_error"
    replay = commands.execute("fake_job", body, _identity())[1]
    assert "falla" not in json.dumps(replay)


# ── I14: recursos ────────────────────────────────────────────────────────────

def test_same_resource_is_busy_and_runs_once_when_resent(env):
    calls = _fake_job(env["monkeypatch"])
    first = commands.execute("fake_job", _body({"n": 1}), _identity())[1]["job_id"]

    second = _body({"n": 2})
    status, payload = commands.execute("fake_job", second, _identity())
    assert status == 409 and payload["status"] == "busy" and payload["reason_code"] == "resource_busy"
    assert payload["job_id"] == first
    assert _record(second["request_id"])["status"] == "not_admitted"
    assert commands.execute("fake_job", second, _identity())[1]["status"] == "busy"

    _drain(env["pending"])
    status, payload = commands.execute("fake_job", second, _identity())
    assert status == 202 and payload["job_id"] != first
    _drain(env["pending"])
    assert calls == [{"n": 1}, {"n": 2}]
    assert commands.execute("fake_job", second, _identity())[0] == 200
    assert calls == [{"n": 1}, {"n": 2}]
    attempts = _conn().execute(
        "SELECT status FROM ui_command_attempts WHERE request_id=? ORDER BY id", (second["request_id"],)
    ).fetchall()
    assert [row[0] for row in attempts] == ["busy", "busy", "accepted", "ok"]


def test_disjoint_resources_run_side_by_side(env):
    _fake_job(env["monkeypatch"], "job_a", resources=("a",))
    _fake_job(env["monkeypatch"], "job_b", resources=("b",))
    assert commands.execute("job_a", _body({}), _identity())[0] == 202
    assert commands.execute("job_b", _body({}), _identity())[0] == 202


# ── I13: TOCTOU ──────────────────────────────────────────────────────────────

@pytest.fixture
def context_id():
    conn = _conn()
    row_id = conn.execute(
        "INSERT INTO contexts (ts, updated_at, project, title, status) VALUES ('x', 'x', ?, 'c', 'active')",
        (PROJECT,),
    ).lastrowid
    conn.commit()
    return row_id


def _versioned_job(env):
    return _fake_job(env["monkeypatch"], category="workflow_mutation", owner=("context", "context_id"),
                     versioned=True)


def test_version_changed_before_start_ends_in_conflict_without_effects(env, context_id):
    calls = _versioned_job(env)
    version = _conn().execute("SELECT version FROM contexts WHERE id=?", (context_id,)).fetchone()[0]
    body = _body({"context_id": context_id}, expected_version=version)
    job_id = commands.execute("fake_job", body, _identity())[1]["job_id"]
    _conn().execute("UPDATE contexts SET title='otro' WHERE id=?", (context_id,))
    _conn().commit()
    _drain(env["pending"])
    assert calls == []
    assert _job(job_id)["status"] == "conflict"
    assert tuple(_record(body["request_id"])[key] for key in ("status", "reason_code")) == ("conflict", "version_conflict")


def test_scope_changed_before_start_ends_in_conflict_without_effects(env, context_id):
    calls = _versioned_job(env)
    version = _conn().execute("SELECT version FROM contexts WHERE id=?", (context_id,)).fetchone()[0]
    body = _body({"context_id": context_id}, expected_version=version)
    job_id = commands.execute("fake_job", body, _identity())[1]["job_id"]
    write_ui_config("admin", ["otro-proyecto"])
    _drain(env["pending"])
    assert calls == [] and _job(job_id)["status"] == "conflict"
    assert _record(body["request_id"])["reason_code"] == "scope_changed"


def test_profile_lowered_before_start_ends_in_conflict(env):
    calls = _fake_job(env["monkeypatch"])
    job_id = commands.execute("fake_job", _body({}), _identity())[1]["job_id"]
    write_ui_config("workflow_operator", [PROJECT])
    _drain(env["pending"])
    assert calls == [] and _job(job_id)["status"] == "conflict"


# ── I7: reinicio ─────────────────────────────────────────────────────────────

def test_reconcile_leaves_no_job_running_and_does_not_retry_runs(env):
    _fake_job(env["monkeypatch"], "job_a", resources=("a",))
    _fake_job(env["monkeypatch"], "job_b", resources=("b",))
    queued_body, running_body = _body({}), _body({})
    queued = commands.execute("job_a", queued_body, _identity())[1]["job_id"]
    running = commands.execute("job_b", running_body, _identity())[1]["job_id"]
    run_id = _conn().execute(
        "INSERT INTO runs (ts, project, provider, model, status, task) VALUES ('x', ?, '?', '?', 'pending', 't')",
        (PROJECT,),
    ).lastrowid
    _conn().execute("UPDATE jobs SET status='running', run_id=? WHERE id=?", (run_id, running))
    _conn().commit()
    env["pending"].clear()

    assert jobs.reconcile() == 0, "los trabajos de este proceso están vivos"
    _as_dead_executor(queued, running)
    assert jobs.reconcile() == 2
    assert _conn().execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0] == 0
    for job_id, body in ((queued, queued_body), (running, running_body)):
        assert _job(job_id)["status"] == "interrupted"
        assert tuple(_record(body["request_id"])[key] for key in ("status", "reason_code")) == ("interrupted", "server_restart")
    assert _conn().execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "failed"

    status, payload = commands.execute("job_b", running_body, _identity())
    assert status == 200 and payload["status"] == "interrupted" and env["pending"] == []
    assert jobs.reconcile() == 0


def test_jobs_of_a_live_executor_are_not_interrupted(env):
    _fake_job(env["monkeypatch"])
    body = _body({})
    job_id = commands.execute("fake_job", body, _identity())[1]["job_id"]
    _conn().execute("UPDATE jobs SET executor='otro-servidor-vivo', heartbeat_at=? WHERE id=?",
                    (jobs._now(), job_id))
    _conn().commit()
    assert jobs.reconcile() == 0
    assert _job(job_id)["status"] == "queued"
    _as_dead_executor(job_id)


def test_a_reconciled_job_is_not_overwritten_when_its_thread_finishes(env):
    """Si otro proceso lo dio por muerto, el hilo original no lo pisa al terminar."""
    reconciled = []

    def work(job, args, project):
        _as_dead_executor(job.job_id)
        reconciled.append(jobs.reconcile())
        return {}

    env["monkeypatch"].setitem(catalog.CATALOG, "slow_job", Command(
        name="slow_job", category="maintenance", schema={"type": "object"}, owner=None, job=work))
    body = _body({})
    job_id = commands.execute("slow_job", body, _identity())[1]["job_id"]
    _drain(env["pending"])
    assert reconciled == [1]
    assert _job(job_id)["status"] == "interrupted"
    assert _record(body["request_id"])["status"] == "interrupted"


def test_a_job_owned_by_another_executor_is_not_started_here(env):
    calls = _fake_job(env["monkeypatch"])
    job_id = commands.execute("fake_job", _body({}), _identity())[1]["job_id"]
    _conn().execute("UPDATE jobs SET executor='otro' WHERE id=?", (job_id,))
    _conn().commit()
    _drain(env["pending"])
    assert calls == [] and _job(job_id)["status"] == "queued"
    _as_dead_executor(job_id)


def test_heartbeat_renews_only_this_executors_lease(env):
    _fake_job(env["monkeypatch"], "job_a", resources=("a",))
    _fake_job(env["monkeypatch"], "job_b", resources=("b",))
    mine = commands.execute("job_a", _body({}), _identity())[1]["job_id"]
    other = commands.execute("job_b", _body({}), _identity())[1]["job_id"]
    old = "2000-01-01T00:00:00+00:00"
    _conn().execute("UPDATE jobs SET heartbeat_at=? WHERE id IN (?, ?)", (old, mine, other))
    _conn().execute("UPDATE jobs SET executor='otro' WHERE id=?", (other,))
    _conn().commit()
    jobs.heartbeat()
    assert _job(mine)["heartbeat_at"] != old and _job(other)["heartbeat_at"] == old


def test_server_startup_reconciles_and_keeps_its_lease():
    import inspect

    from orchestrator import server
    source = inspect.getsource(server.serve)
    assert "_jobs.reconcile()" in source and "_jobs.start_heartbeat()" in source


# ── I15: presupuesto y proveedor ─────────────────────────────────────────────

@pytest.fixture
def provider_calls(env):
    """`background._worker` simulado: marca el run como hecho con un costo real."""
    from orchestrator import background
    calls = []

    def worker(run_id, project, task, config, model, ctx, step_id=None, still_owned=None):
        calls.append({"run_id": run_id, "model": model, "owned": still_owned()})
        _conn().execute("UPDATE runs SET status='done', cost_usd=0.25 WHERE id=?", (run_id,))
        _conn().commit()

    env["monkeypatch"].setattr(background, "_worker", worker)
    return calls


def _limit(env, limit, estimate):
    env["monkeypatch"].setattr(budget, "daily_limit", lambda project, config: limit)
    env["monkeypatch"].setattr(budget, "estimate_run_usd", lambda config, provider: estimate)


def test_run_over_budget_is_denied_before_any_call(env, provider_calls):
    _limit(env, 1.0, 2.0)
    runs_before = _conn().execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    body = _body({"project": PROJECT, "task": "t"})
    status, payload = commands.execute("run_task", body, _identity("observability"))
    assert status == 403 and payload["reason_code"] == "budget_exceeded"
    assert env["pending"] == [] and provider_calls == []
    assert _reservation(body["request_id"]) is None
    assert _conn().execute("SELECT COUNT(*) FROM jobs WHERE request_id=?", (body["request_id"],)).fetchone()[0] == 0
    assert _conn().execute("SELECT COUNT(*) FROM runs").fetchone()[0] == runs_before


def test_open_reservations_count_against_the_budget(env, provider_calls):
    _limit(env, 5.0, 3.0)
    first = commands.execute("run_task", _body({"project": PROJECT, "task": "a"}), _identity("observability"))
    assert first[0] == 202
    second = commands.execute("run_task", _body({"project": PROJECT, "task": "b"}), _identity("observability"))
    assert second[0] == 403 and second[1]["reason_code"] == "budget_exceeded"


def test_run_reserves_then_settles_with_the_real_cost(env, provider_calls):
    _limit(env, 100.0, 1.5)
    body = _body({"project": PROJECT, "task": "t", "provider": "deepseek"})
    job_id = commands.execute("run_task", body, _identity("observability"))[1]["job_id"]
    reservation = _reservation(body["request_id"])
    assert reservation["status"] == "reserved" and reservation["estimated_usd"] == 1.5
    assert reservation["period"] == budget.period()

    _drain(env["pending"])
    assert len(provider_calls) == 1 and provider_calls[0]["model"] == "deepseek"
    assert provider_calls[0]["owned"] is True
    run_id = _job(job_id)["run_id"]
    assert run_id == provider_calls[0]["run_id"]
    reservation = _reservation(body["request_id"])
    assert reservation["status"] == "settled" and reservation["actual_usd"] == 0.25
    replay = commands.execute("run_task", body, _identity("observability"))[1]
    assert replay["status"] == "ok"
    assert any(kind == "job_stage" and event.get("run_id") == run_id for kind, event in env["events"])


def test_failed_run_releases_its_reservation(env, monkeypatch):
    from orchestrator import background
    _limit(env, 100.0, 1.0)
    monkeypatch.setattr(background, "_worker", lambda run_id, *a, **k: background.fail_run(run_id, "x"))
    body = _body({"project": PROJECT, "task": "t"})
    job_id = commands.execute("run_task", body, _identity("observability"))[1]["job_id"]
    _drain(env["pending"])
    assert _job(job_id)["status"] == "failed"
    assert _reservation(body["request_id"])["status"] == "released"


def test_run_task_goes_through_the_egress_gated_worker(env, monkeypatch):
    """El trabajo usa el mismo worker que /run, que fija la política de egress antes de llamar."""
    import inspect

    from orchestrator import background
    source = inspect.getsource(background._worker)
    assert source.index("egress.set_policy") < source.index("complete_stream")
    _limit(env, 100.0, 1.0)
    seen = []
    monkeypatch.setattr(background, "_worker",
                        lambda run_id, project, *a, **k: (seen.append(project), background.fail_run(run_id, "x")))
    commands.execute("run_task", _body({"project": PROJECT, "task": "t"}), _identity("observability"))
    _drain(env["pending"])
    assert seen == [PROJECT]


def test_estimate_uses_the_most_expensive_candidate_plus_the_router():
    config = {"providers": {"cheap": {"model": "deepseek-chat"}, "pricey": {"model": "claude-opus-4-8"}},
              "router": {"provider": "cheap"},
              "budgets": {"reservation_input_tokens": 1_000_000, "reservation_output_tokens": 0,
                          "reservation_router_input_tokens": 1_000_000, "reservation_router_output_tokens": 0}}
    assert budget.estimate_run_usd(config, None) == pytest.approx(5.0 + 0.14)
    assert budget.estimate_run_usd(config, "cheap") == pytest.approx(0.14)
    unknown = {"providers": {"x": {"model": "modelo-sin-precio"}},
               "budgets": {"reservation_input_tokens": 1_000_000, "reservation_output_tokens": 0}}
    assert budget.estimate_run_usd(unknown, None) >= 5.0


# ── Trabajos reales del catálogo ─────────────────────────────────────────────

def test_sync_sessions_is_global_and_admin_only(env, monkeypatch):
    import orchestrator.git_scanner as git_scanner
    monkeypatch.setattr(git_scanner, "scan_and_import", lambda config, quiet: ["a", "b"])
    denied = commands.execute("sync_sessions", _body({"source": "git"}), _identity("workflow_operator"))
    assert denied[0] == 403
    body = _body({"source": "git"})
    status, payload = commands.execute("sync_sessions", body, _identity("admin", projects=()))
    assert status == 202
    assert json.loads(_job(payload["job_id"])["resources"]) == ["imports"]
    _drain(env["pending"])
    assert _record(body["request_id"])["status"] == "ok"


def test_index_project_docs_takes_the_project_rag_resource(env, monkeypatch):
    import orchestrator.rag as rag
    monkeypatch.setattr(rag, "index_project_isolated", lambda project, path, **kw: {"chunks": 4})
    body = _body({"project": PROJECT})
    job_id = commands.execute("index_project_docs", body, _identity())[1]["job_id"]
    assert json.loads(_job(job_id)["resources"]) == [f"project:{PROJECT}:rag"]
    _drain(env["pending"])
    assert _job(job_id)["status"] == "done"
    unknown = commands.execute("index_project_docs", _body({"project": "no-registrado"}), _identity())
    assert unknown[0] == 404 and unknown[1]["reason_code"] == "not_found"


def test_jobs_execution_migration_is_idempotent():
    import sqlite3

    from orchestrator.migrate import RFC010_TABLES, _run_script, _table_columns, apply_rfc010_jobs_execution
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY)")
    _run_script(conn, RFC010_TABLES)
    assert "run_id" not in _table_columns(conn, "jobs")
    apply_rfc010_jobs_execution(conn)
    apply_rfc010_jobs_execution(conn)
    assert {"run_id", "executor", "heartbeat_at"} <= _table_columns(conn, "jobs")


def test_daily_cost_counts_the_router(env):
    from orchestrator.db import daily_cost
    project = "proyecto-con-router"
    _conn().execute(
        "INSERT INTO runs (ts, project, provider, model, status, task, cost_usd, router_cost_usd) "
        "VALUES (?, ?, 'p', 'm', 'done', 't', 0.5, 0.25)",
        (jobs._now(), project),
    )
    _conn().execute(
        "INSERT INTO runs (ts, project, provider, model, status, task, router_cost_usd) "
        "VALUES (?, ?, 'p', 'm', 'failed', 't', 0.125)",
        (jobs._now(), project),
    )
    _conn().commit()
    assert daily_cost(project) == pytest.approx(0.875)


def _pending_run(project=PROJECT):
    run_id = _conn().execute(
        "INSERT INTO runs (ts, project, provider, model, status, task) VALUES (?, ?, '?', '?', 'pending', 't')",
        (jobs._now(), project),
    ).lastrowid
    _conn().commit()
    return run_id


def test_fenced_update_keeps_a_reconciled_run_failed_but_records_its_cost():
    from orchestrator.db import update_run
    from orchestrator.providers.base import CompletionResult
    run_id = _pending_run()
    _conn().execute("UPDATE runs SET status='failed', response='interrupted' WHERE id=?", (run_id,))
    _conn().commit()
    result = CompletionResult(text="respuesta tardía", provider="p", model="m")
    assert update_run(run_id, result, 10, "r", cost_usd=0.5, router_cost_usd=0.1, only_if_pending=True) is False
    row = _conn().execute("SELECT status, response, cost_usd, router_cost_usd FROM runs WHERE id=?", (run_id,)).fetchone()
    assert tuple(row) == ("failed", "interrupted", 0.5, 0.1)

    other = _pending_run()
    assert update_run(other, result, 10, "r", cost_usd=0.5, only_if_pending=True) is True
    assert _conn().execute("SELECT status FROM runs WHERE id=?", (other,)).fetchone()[0] == "done"


def test_worker_does_not_route_or_call_a_provider_once_the_job_is_lost(monkeypatch, tmp_path):
    from orchestrator import background
    import orchestrator.index as index_module
    monkeypatch.setattr(index_module, "get_project_path", lambda alias: tmp_path)
    import orchestrator.providers.factory as factory
    import orchestrator.router as router

    def forbidden(*args, **kwargs):
        raise AssertionError("no debe llamarse")

    monkeypatch.setattr(router, "decide_provider", forbidden)
    monkeypatch.setattr(router, "force_provider", forbidden)
    monkeypatch.setattr(factory, "build_provider", forbidden)
    run_id = _pending_run()
    background._worker(run_id, PROJECT, "t", {}, "deepseek", None, None, still_owned=lambda: False)
    assert _conn().execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "pending"


def test_job_owned_reflects_reconciliation(env):
    seen = []

    def work(job, args, project):
        seen.append(job.owned())
        _as_dead_executor(job.job_id)
        seen.append(job.owned())
        return {}

    env["monkeypatch"].setitem(catalog.CATALOG, "probe_job", Command(
        name="probe_job", category="maintenance", schema={"type": "object"}, owner=None, job=work))
    commands.execute("probe_job", _body({}), _identity())
    _drain(env["pending"])
    assert seen == [True, False]
