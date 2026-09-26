import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator import watcher
from orchestrator.db import _conn


def _write_session(
    path: Path,
    session_id: str,
    cwd: str,
    turns: int,
    base: datetime,
    minutes_per_turn: int = 5,
) -> None:
    """Escribe un archivo .jsonl minimo compatible con _parse_session, con
    `turns` pares user/assistant separados por `minutes_per_turn`."""
    lines = []
    for i in range(turns):
        ts_user = (base + timedelta(minutes=i * minutes_per_turn)).isoformat().replace("+00:00", "Z")
        ts_assistant = (base + timedelta(minutes=i * minutes_per_turn + 1)).isoformat().replace("+00:00", "Z")
        lines.append(json.dumps({
            "type": "user",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": ts_user,
            "message": {"content": f"pregunta {i}"},
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": ts_assistant,
            "message": {
                "model": "claude-sonnet-5",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{"type": "text", "text": f"respuesta {i}"}],
            },
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def cc_env(tmp_path, monkeypatch, request):
    projects_dir = tmp_path / "claude-projects"
    projects_dir.mkdir()
    alias = f"cc-project-{request.node.name}"
    proj_path = tmp_path / "proj"
    proj_path.mkdir()
    monkeypatch.setattr(watcher, "CLAUDE_PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(
        "orchestrator.index.load_index",
        lambda: {"projects": {alias: str(proj_path)}},
    )
    monkeypatch.setattr("orchestrator.rag.index_response", lambda *a, **kw: None)
    return alias, str(proj_path), projects_dir


def test_newest_available_mtime_skips_empty_files(cc_env, monkeypatch):
    _alias, _proj, projects_dir = cc_env
    slug_dir = projects_dir / "some-slug"
    slug_dir.mkdir()

    empty = slug_dir / "empty-session.jsonl"
    empty.write_text("", encoding="utf-8")

    real = slug_dir / "real-session.jsonl"
    real.write_text('{"type":"user","timestamp":"2026-01-01T00:00:00Z"}\n', encoding="utf-8")
    import os
    old_time = (datetime(2020, 1, 1)).timestamp()
    os.utime(empty, (old_time, old_time))

    newest = watcher.newest_available_mtime()
    assert newest is not None
    # Si el archivo vacio contara, newest podria diferir segun el orden de
    # iteracion del filesystem - lo relevante es que NO sea la fecha vieja
    # forzada en el vacio (2020) cuando el real es mucho mas nuevo.
    assert newest.year != 2020


_PRICED_CONFIG = {"pricing": {"claude-sonnet-5": {"input": 3.0, "output": 15.0}}}


def test_scan_and_import_refreshes_session_that_grew(cc_env):
    alias, _proj, projects_dir = cc_env
    slug_dir = projects_dir / "slug-1"
    slug_dir.mkdir()
    session_file = slug_dir / "session-a.jsonl"

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _write_session(session_file, "session-a", _proj, turns=1, base=base)

    imported = watcher.scan_and_import(_PRICED_CONFIG, quiet=True)
    assert len(imported) == 1

    row = _conn().execute(
        "SELECT response, duration_ms, cost_usd, cost_pricing_key FROM runs WHERE session_id=?", ("session-a",)
    ).fetchone()
    assert row["cost_usd"] is not None and row["cost_pricing_key"] == "claude-sonnet-5"
    assert row is not None
    first_duration = row["duration_ms"]
    first_response = row["response"]

    # La sesion "sigue activa": se agregan mas turnos (mas tokens, mas
    # duracion) al MISMO archivo.
    _write_session(session_file, "session-a", _proj, turns=3, base=base)

    imported_2 = watcher.scan_and_import(_PRICED_CONFIG, quiet=True)
    assert len(imported_2) == 1  # se re-proceso, no se salteo

    row_2 = _conn().execute(
        "SELECT response, duration_ms, cost_usd, cost_pricing_key FROM runs WHERE session_id=?", ("session-a",)
    ).fetchone()
    assert row_2["cost_usd"] > row["cost_usd"] and row_2["cost_pricing_key"] == "claude-sonnet-5"
    assert row_2["duration_ms"] > first_duration
    assert row_2["response"] != first_response
    assert len(_conn().execute(
        "SELECT id FROM runs WHERE session_id=?", ("session-a",)
    ).fetchall()) == 1  # no duplico la fila, actualizo la existente


def test_scan_and_import_skips_session_without_new_activity(cc_env):
    alias, proj, projects_dir = cc_env
    slug_dir = projects_dir / "slug-2"
    slug_dir.mkdir()
    session_file = slug_dir / "session-b.jsonl"

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _write_session(session_file, "session-b", proj, turns=1, base=base)

    imported = watcher.scan_and_import({}, quiet=True)
    assert len(imported) == 1

    imported_2 = watcher.scan_and_import({}, quiet=True)
    assert imported_2 == []  # mismo contenido, nada que actualizar


def test_scan_and_import_skips_stable_token_session_without_text(cc_env):
    """Una sesion con uso pero sin prompt/respuesta no debe actualizarse
    indefinidamente por los campos vacios que son validos."""
    _alias, proj, projects_dir = cc_env
    slug_dir = projects_dir / "slug-no-text"
    slug_dir.mkdir()
    session_file = slug_dir / "session-no-text.jsonl"
    timestamp = "2026-01-01T00:00:00Z"
    session_file.write_text(
        json.dumps({
            "type": "assistant",
            "sessionId": "session-no-text",
            "cwd": proj,
            "timestamp": timestamp,
            "message": {
                "model": "claude-sonnet-5",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [],
            },
        }) + "\n",
        encoding="utf-8",
    )

    assert len(watcher.scan_and_import({}, quiet=True)) == 1
    assert watcher.scan_and_import({}, quiet=True) == []


def test_scan_and_import_keeps_cache_only_session(cc_env):
    _alias, proj, projects_dir = cc_env
    slug_dir = projects_dir / "slug-cache"
    slug_dir.mkdir()
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    (slug_dir / "session-cache.jsonl").write_text(
        json.dumps({"type": "user", "sessionId": "session-cache", "cwd": proj, "timestamp": ts,
                    "message": {"content": "pregunta"}}) + "\n"
        + json.dumps({"type": "assistant", "sessionId": "session-cache", "cwd": proj, "timestamp": ts,
                      "message": {"model": "claude-sonnet-5",
                                  "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1000},
                                  "content": [{"type": "text", "text": "respuesta"}]}}) + "\n",
        encoding="utf-8",
    )

    assert len(watcher.scan_and_import(_PRICED_CONFIG, quiet=True)) == 1
    row = _conn().execute(
        "SELECT cache_read_tokens, cost_pricing_key FROM runs WHERE session_id=?", ("session-cache",)
    ).fetchone()
    assert (row["cache_read_tokens"], row["cost_pricing_key"]) == (1000, "claude-sonnet-5")
