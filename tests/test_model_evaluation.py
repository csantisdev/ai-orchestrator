import sqlite3
import threading

import pytest

from orchestrator import db as db_module
from orchestrator.eval import local_model_eval


@pytest.fixture
def evaluation_db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE runs (
            id INTEGER PRIMARY KEY,
            project TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            task TEXT NOT NULL,
            response TEXT NOT NULL,
            task_class TEXT,
            verification_result TEXT,
            rating TEXT,
            cost_usd REAL,
            duration_ms INTEGER
        )"""
    )
    monkeypatch.setattr(db_module, "_conn", lambda: conn)
    yield conn
    conn.close()


def _insert_run(conn, **overrides):
    values = {
        "project": "private-project",
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "status": "done",
        "task": "private task payload",
        "response": "private response payload",
        "task_class": "unit",
        "verification_result": "passed",
        "rating": "useful",
        "cost_usd": 0.02,
        "duration_ms": 1200,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO runs ({columns}) VALUES ({placeholders})",
        list(values.values()),
    )
    conn.commit()
    return cur.lastrowid


def test_local_model_eval_returns_only_aggregates(evaluation_db):
    _insert_run(evaluation_db)
    _insert_run(
        evaluation_db,
        model="claude-sonnet-4-6",
        task_class="regression",
        verification_result="manual_review",
        rating="partial",
        cost_usd=0.04,
        duration_ms=2400,
    )
    _insert_run(evaluation_db, task_class=None, verification_result=None)

    report = local_model_eval()

    assert report["evaluated_runs"] == 2
    assert report["rated_runs"] == 2
    assert report["rating_coverage"] == 1.0
    assert len(report["groups"]) == 2
    forbidden = {"project", "task", "response", "task_preview"}
    assert all(forbidden.isdisjoint(group) for group in report["groups"])


def test_local_model_eval_filters_task_class(evaluation_db):
    _insert_run(evaluation_db, task_class="unit")
    _insert_run(evaluation_db, task_class="schema")

    report = local_model_eval(task_class="schema")

    assert report["evaluated_runs"] == 1
    assert report["groups"][0]["task_class"] == "schema"


def test_local_model_eval_rejects_unknown_task_class():
    with pytest.raises(ValueError, match="task_class inválido"):
        local_model_eval(task_class="ad_hoc")


def test_record_run_evaluation_validates_controlled_labels(evaluation_db):
    run_id = _insert_run(
        evaluation_db,
        task_class=None,
        verification_result=None,
        rating=None,
    )

    db_module.record_run_evaluation(run_id, "integration", "passed", "useful")

    row = evaluation_db.execute(
        """SELECT task_class, verification_result, rating
           FROM runs WHERE id=?""",
        (run_id,),
    ).fetchone()
    assert dict(row) == {
        "task_class": "integration",
        "verification_result": "passed",
        "rating": "useful",
    }


def test_record_run_evaluation_rejects_invalid_labels(evaluation_db):
    run_id = _insert_run(evaluation_db)

    with pytest.raises(ValueError, match="task_class inválido"):
        db_module.record_run_evaluation(run_id, "free-text", "passed")
    with pytest.raises(ValueError, match="verification_result inválido"):
        db_module.record_run_evaluation(run_id, "unit", "green")
    with pytest.raises(ValueError, match="rating inválido"):
        db_module.record_run_evaluation(run_id, "unit", "passed", "excellent")


def test_init_db_migrates_evaluation_fields_to_local_database(tmp_path, monkeypatch):
    import orchestrator.paths as paths_module

    original_local = db_module._local
    monkeypatch.setattr(paths_module, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths_module, "DB_PATH", tmp_path / "runs.db")
    db_module._local = threading.local()
    try:
        db_module.init_db()
        columns = {
            row["name"]
            for row in db_module._conn().execute("PRAGMA table_info(runs)")
        }
        assert {"task_class", "verification_result"} <= columns
    finally:
        db_module._local = original_local
