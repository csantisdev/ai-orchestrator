import tempfile
import threading
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_db(monkeypatch):
    import orchestrator.db as db
    import orchestrator.paths as paths
    root = Path(tempfile.mkdtemp())
    monkeypatch.setattr(paths, "HOME_DIR", root)
    monkeypatch.setattr(paths, "DB_PATH", root / "runs.db")
    monkeypatch.setattr(db, "_local", threading.local())
    db.init_db()
    return db


def _commit(db, project, task, sha, ts="2026-01-02T00:00:00+00:00"):
    db._conn().execute("""INSERT INTO runs (ts, project, provider, task, session_id)
                          VALUES (?, ?, 'git', ?, ?)""", (ts, project, task, f"git::{project}::{sha}"))
    db._conn().commit()


def test_suggestions_match_explicit_step_and_ignore_other_context_id(isolated_db):
    from orchestrator.step_suggestions import suggest_step_commits
    first = isolated_db.insert_context("demo", "One")
    step = isolated_db.insert_step(first, 1, "Do work")
    other = isolated_db.insert_context("demo", "Other", status="programado")
    other_step = isolated_db.insert_step(other, 1, "Other")
    _commit(isolated_db, "demo", f"feat: finish step {step}", "abcdef123")
    _commit(isolated_db, "demo", f"fix: step {other_step}", "fedcba321")

    found = suggest_step_commits(isolated_db._conn(), "demo")

    assert found == [{"step_id": step, "title": "Do work", "commits": [{"sha": "abcdef12", "date": "2026-01-02T00:00:00+00:00", "subject": f"feat: finish step {step}", "reason": f"referencia explícita al paso #{step}", "strength": "fuerte"}]}]


def test_suggestions_match_ticket_and_exclude_unrelated_commits(isolated_db):
    from orchestrator.step_suggestions import suggest_step_commits
    context = isolated_db.insert_context("demo", "One")
    step = isolated_db.insert_step(context, 1, "Implement T-066", "Handle T-066")
    _commit(isolated_db, "demo", "feat: T-066 support", "abcdef123")
    _commit(isolated_db, "demo", "docs: unrelated", "fedcba321")

    found = suggest_step_commits(isolated_db._conn(), "demo")

    assert found[0]["step_id"] == step
    assert found[0]["commits"][0]["reason"] == "ticket compartido: T-066"
    assert found[0]["commits"][0]["strength"] == "fuerte"


def test_suggestions_ignore_description_tickets_and_bare_issue_numbers(isolated_db):
    from orchestrator.step_suggestions import suggest_step_commits
    context = isolated_db.insert_context("demo", "One")
    step = isolated_db.insert_step(context, 1, "Implement API", "Related to T-066")
    _commit(isolated_db, "demo", "Merge pull request #1 T-066", "abcdef123")
    _commit(isolated_db, "demo", "feat: step #1 complete", "fedcba321")

    found = suggest_step_commits(isolated_db._conn(), "demo")

    assert found[0]["commits"] == [{"sha": "fedcba32", "date": "2026-01-02T00:00:00+00:00", "subject": "feat: step #1 complete", "reason": "referencia explícita al paso #1", "strength": "fuerte"}]
