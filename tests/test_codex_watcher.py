import json
import sqlite3
import time
from pathlib import Path

import pytest

from orchestrator import codex_watcher
from orchestrator.db import _conn


def _write_rollout(path: Path, turns: int, input_tokens: int = 100, output_tokens: int = 50) -> None:
    lines = []
    for i in range(turns):
        lines.append(json.dumps({
            "type": "response_item",
            "payload": {"role": "assistant", "content": [{"type": "text", "text": f"respuesta {i}"}]},
        }))
        lines.append(json.dumps({
            "type": "event_msg",
            "payload": {"info": {"total_token_usage": {
                "input_tokens": input_tokens * (i + 1),
                "output_tokens": output_tokens * (i + 1),
                "cached_input_tokens": 0,
            }}},
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_state_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY, cwd TEXT, model TEXT, model_provider TEXT,
            created_at_ms INTEGER, updated_at_ms INTEGER,
            first_user_message TEXT, rollout_path TEXT
        )
    """)
    conn.commit()
    return conn


def _upsert_thread(conn, thread_id, cwd, created_ms, updated_ms, first_msg, rollout_path):
    conn.execute(
        """INSERT INTO threads (id, cwd, model, model_provider, created_at_ms, updated_at_ms,
                                 first_user_message, rollout_path)
           VALUES (?, ?, 'claude-sonnet-5', 'anthropic', ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET updated_at_ms=excluded.updated_at_ms""",
        (thread_id, cwd, created_ms, updated_ms, first_msg, rollout_path),
    )
    conn.commit()


@pytest.fixture
def codex_env(tmp_path, monkeypatch, request):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    alias = f"codex-project-{request.node.name}"
    proj_path = tmp_path / "proj"
    proj_path.mkdir()
    monkeypatch.setattr(codex_watcher, "CODEX_HOME", codex_home)
    monkeypatch.setattr(
        "orchestrator.index.load_index",
        lambda: {"projects": {alias: str(proj_path)}},
    )
    monkeypatch.setattr("orchestrator.rag.index_response", lambda *a, **kw: None)

    state_db_path = codex_home / "state_1.sqlite"
    conn = _make_state_db(state_db_path)
    return alias, str(proj_path), conn, tmp_path


_IDLE_MS = 30 * 60 * 1000  # 30 min atras - bien pasado el cutoff de 60s


def test_newest_available_ts_excludes_threads_without_first_message(codex_env):
    _alias, _proj, conn, _tmp = codex_env
    now_ms = int(time.time() * 1000)

    _upsert_thread(conn, "empty-thread", "/nowhere", now_ms - _IDLE_MS - 60_000,
                    now_ms - _IDLE_MS, "", "")
    ts_only_empty = codex_watcher.newest_available_ts()
    assert ts_only_empty is None

    _upsert_thread(conn, "real-thread", "/nowhere", now_ms - _IDLE_MS, now_ms - _IDLE_MS + 1000,
                    "hola", "")
    ts_with_real = codex_watcher.newest_available_ts()
    assert ts_with_real is not None


def test_scan_and_import_refreshes_thread_that_grew(codex_env):
    alias, proj, conn, tmp = codex_env
    now_ms = int(time.time() * 1000)
    rollout = tmp / "rollout.jsonl"
    _write_rollout(rollout, turns=1)

    created_ms = now_ms - _IDLE_MS - 5_000
    updated_ms = now_ms - _IDLE_MS
    _upsert_thread(conn, "thread-a", proj, created_ms, updated_ms, "hola", str(rollout))

    imported = codex_watcher.scan_and_import({}, quiet=True)
    assert len(imported) == 1

    row = _conn().execute(
        "SELECT response, duration_ms FROM runs WHERE session_id=?", ("thread-a",)
    ).fetchone()
    first_duration = row["duration_ms"]
    first_response = row["response"]

    # El thread "sigue activo": mas turnos en el rollout y updated_at_ms
    # avanza (pero sigue pasado el cutoff de 60s para la proxima corrida).
    _write_rollout(rollout, turns=3)
    updated_ms_2 = now_ms - _IDLE_MS + 10_000
    _upsert_thread(conn, "thread-a", proj, created_ms, updated_ms_2, "hola", str(rollout))

    imported_2 = codex_watcher.scan_and_import({}, quiet=True)
    assert len(imported_2) == 1

    row_2 = _conn().execute(
        "SELECT response, duration_ms FROM runs WHERE session_id=?", ("thread-a",)
    ).fetchone()
    assert row_2["duration_ms"] > first_duration
    assert row_2["response"] != first_response
    assert len(_conn().execute(
        "SELECT id FROM runs WHERE session_id=?", ("thread-a",)
    ).fetchall()) == 1


def test_scan_and_import_skips_thread_without_new_activity(codex_env):
    alias, proj, conn, tmp = codex_env
    now_ms = int(time.time() * 1000)
    rollout = tmp / "rollout2.jsonl"
    _write_rollout(rollout, turns=1)

    created_ms = now_ms - _IDLE_MS - 5_000
    updated_ms = now_ms - _IDLE_MS
    _upsert_thread(conn, "thread-b", proj, created_ms, updated_ms, "hola", str(rollout))

    imported = codex_watcher.scan_and_import({}, quiet=True)
    assert len(imported) == 1

    imported_2 = codex_watcher.scan_and_import({}, quiet=True)
    assert imported_2 == []
