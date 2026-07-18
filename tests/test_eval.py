import sqlite3
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from orchestrator import context as context_module
from orchestrator import db as db_module
from orchestrator import index as index_module
from orchestrator.context import ProjectContext
from orchestrator.eval import offline_router_eval
from orchestrator.index import ProjectNotFoundError


_CONFIG = {
    "defaults": {"default_provider": "claude"},
    "providers": {
        "deepseek": {"model": "deepseek-test", "clearance": "restricted"},
        "gemini": {"model": "gemini-test", "clearance": "restricted"},
        "openai": {"model": "openai-test", "clearance": "restricted"},
        "claude": {"model": "claude-test", "clearance": "restricted"},
    },
}


@pytest.fixture
def eval_db(monkeypatch):
    connections = []

    def make(*, routing_source=True):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        extra_column = ", routing_source TEXT" if routing_source else ""
        conn.execute(
            f"""CREATE TABLE runs (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                project TEXT NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                task TEXT NOT NULL,
                rating TEXT,
                router_cost_usd REAL
                {extra_column}
            )"""
        )
        connections.append(conn)
        monkeypatch.setattr(db_module, "_conn", lambda: conn)
        return conn

    yield make
    for conn in connections:
        conn.close()


def _insert_run(
    conn,
    *,
    project="alpha",
    provider="claude",
    task="documentar",
    rating=None,
    router_cost_usd=None,
    routing_source=True,
):
    columns = "ts, project, provider, status, task, rating, router_cost_usd"
    values = ["2026-01-01T00:00:00Z", project, provider, "done", task, rating, router_cost_usd]
    if routing_source:
        columns += ", routing_source"
        values.append("llm_router")
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO runs ({columns}) VALUES ({placeholders})", values)
    conn.commit()


def _contexts(monkeypatch, contexts):
    monkeypatch.setattr(index_module, "get_project_path", lambda alias: Path(alias))
    monkeypatch.setattr(
        context_module,
        "load_context",
        lambda path: contexts[path.name],
    )


def test_offline_eval_never_calls_network(eval_db, monkeypatch):
    conn = eval_db()
    _insert_run(conn)
    _contexts(monkeypatch, {"alpha": ProjectContext(name="alpha", default_provider="claude")})

    with patch.object(httpx.Client, "request") as sync_request, patch.object(
        httpx.AsyncClient, "request"
    ) as async_request:
        report = offline_router_eval(_CONFIG)

    assert report["evaluated_runs"] == 1
    sync_request.assert_not_called()
    async_request.assert_not_called()


def test_offline_eval_computes_agreement_and_coverage_together(eval_db, monkeypatch):
    conn = eval_db()
    _insert_run(conn, provider="claude", rating="useful", router_cost_usd=0.25)
    _insert_run(conn, provider="openai", rating=None, router_cost_usd=None)
    _contexts(monkeypatch, {"alpha": ProjectContext(name="alpha", default_provider="claude")})

    report = offline_router_eval(_CONFIG, project="alpha")

    assert report["evaluated_runs"] == 2
    assert report["agreement_rate"] == 0.5
    assert report["rating_coverage"] == 0.5
    assert report["external_router_spend_usd"] == 0.25
    assert report["router_cost_observed_runs"] == 1
    assert report["router_cost_missing_runs"] == 1


def test_offline_eval_sets_policy_per_project(eval_db, monkeypatch):
    conn = eval_db()
    _insert_run(conn, project="alpha", provider="claude")
    _insert_run(conn, project="beta", provider="deepseek")
    _contexts(
        monkeypatch,
        {
            "alpha": ProjectContext(
                name="alpha",
                default_provider="claude",
                allowed_providers=["claude"],
            ),
            "beta": ProjectContext(
                name="beta",
                default_provider="deepseek",
                allowed_providers=["deepseek"],
            ),
        },
    )

    report = offline_router_eval(_CONFIG)

    assert report["evaluated_runs"] == 2
    assert report["skipped_runs"] == 0
    assert report["agreement_rate"] == 1.0


def test_offline_eval_skips_runs_with_missing_project(eval_db, monkeypatch):
    conn = eval_db()
    _insert_run(conn, project="alpha", provider="claude")
    _insert_run(conn, project="deleted", provider="claude")

    def project_path(alias):
        if alias == "deleted":
            raise ProjectNotFoundError(alias)
        return Path(alias)

    monkeypatch.setattr(index_module, "get_project_path", project_path)
    monkeypatch.setattr(
        context_module,
        "load_context",
        lambda path: ProjectContext(name=path.name, default_provider="claude"),
    )

    report = offline_router_eval(_CONFIG)

    assert report["evaluated_runs"] == 1
    assert report["skipped_runs"] == 1
    assert report["agreement_rate"] == 1.0


def test_offline_eval_falls_back_when_routing_source_column_missing(eval_db, monkeypatch):
    conn = eval_db(routing_source=False)
    _insert_run(conn, routing_source=False)
    _contexts(monkeypatch, {"alpha": ProjectContext(name="alpha", default_provider="claude")})

    report = offline_router_eval(_CONFIG)

    assert report["evaluated_runs"] == 1
    assert report["agreement_rate"] == 1.0
