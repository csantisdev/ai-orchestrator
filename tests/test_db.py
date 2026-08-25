from datetime import datetime, timedelta, timezone

from orchestrator.db import _conn, _write_lock, daily_cost


def _insert(project: str, ts: str, cost_usd: float) -> None:
    conn = _conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO runs (ts, project, status, cost_usd) VALUES (?, ?, 'done', ?)",
            (ts, project, cost_usd),
        )
        conn.commit()


def test_daily_cost_sums_only_local_today(request):
    project = f"daily-cost-{request.node.name}"
    now_utc = datetime.now(timezone.utc)

    _insert(project, now_utc.isoformat(), 1.5)
    _insert(project, (now_utc - timedelta(hours=26)).isoformat(), 100.0)
    _insert(project, (now_utc + timedelta(hours=26)).isoformat(), 200.0)

    assert daily_cost(project) == 1.5


def test_daily_cost_ignores_other_projects(request):
    project = f"daily-cost-iso-{request.node.name}"
    other = f"{project}-other"
    now_utc = datetime.now(timezone.utc)

    _insert(project, now_utc.isoformat(), 3.0)
    _insert(other, now_utc.isoformat(), 999.0)

    assert daily_cost(project) == 3.0


def test_daily_cost_no_runs_returns_zero(request):
    assert daily_cost(f"never-seen-{request.node.name}") == 0.0


def test_insert_or_ignore_race_lastrowid_points_elsewhere(request):
    """Regresion: tras un INSERT OR IGNORE ignorado (rowcount=0), lastrowid
    de esa conexion apunta a la ULTIMA fila que esa conexion inserto, no al
    registro real con ese session_id. git_scanner/watcher/codex_watcher
    deben resolver el run_id real via SELECT por session_id en ese caso."""
    project = f"race-{request.node.name}"
    sid = f"race::{request.node.name}"
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()

    with _write_lock:
        cur_real = conn.execute(
            "INSERT INTO runs (ts, project, status, session_id) VALUES (?, ?, 'done', ?)",
            (now, project, sid),
        )
        real_id = cur_real.lastrowid
        conn.commit()

        # Insercion no relacionada en la MISMA conexion, deja lastrowid
        # apuntando a una fila ajena antes del reintento.
        cur_unrelated = conn.execute(
            "INSERT INTO runs (ts, project, status) VALUES (?, ?, 'done')",
            (now, project),
        )
        unrelated_id = cur_unrelated.lastrowid
        conn.commit()
        assert unrelated_id != real_id

        # Reintento del mismo session_id (lo que hace el scanner tras perder
        # una carrera con otro proceso): no inserta nada.
        cur_retry = conn.execute(
            "INSERT OR IGNORE INTO runs (ts, project, status, session_id) VALUES (?, ?, 'done', ?)",
            (now, project, sid),
        )
        assert cur_retry.rowcount == 0
        # El bug: confiar en lastrowid aca devolveria la fila ajena.
        assert cur_retry.lastrowid == unrelated_id

        # El fix: resolver por session_id en vez de lastrowid.
        resolved = conn.execute(
            "SELECT id FROM runs WHERE session_id=?", (sid,)
        ).fetchone()
        assert resolved["id"] == real_id
