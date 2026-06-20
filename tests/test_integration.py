"""Test de integración: db, costs, similarity."""
import threading
import tempfile
from pathlib import Path


def _close_db(db_mod):
    if hasattr(db_mod._local, "conn") and db_mod._local.conn:
        db_mod._local.conn.close()
        db_mod._local.conn = None


def test_db_lifecycle():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()

        from orchestrator.providers.base import CompletionResult
        run_id = db_mod.insert_run("proj", "crear tests", "claude", "claude-sonnet-4-6")
        assert isinstance(run_id, int)

        result = CompletionResult(
            text="respuesta",
            provider="claude",
            model="claude-sonnet-4-6",
            raw_response={"usage": {"input_tokens": 500, "output_tokens": 200}},
            cache_creation_tokens=0,
            cache_read_tokens=50,
        )
        db_mod.update_run(run_id, result, duration_ms=1000, routing_reason="router", cost_usd=0.005)

        rows = db_mod.read_runs()
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "done"
        assert row["provider"] == "claude"
        assert row["cost_usd"] == 0.005
        assert row["cache_read_tokens"] == 50

        cost = db_mod.daily_cost("proj")
        assert abs(cost - 0.005) < 1e-9

    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_cost_calculation():
    from orchestrator.providers.base import CompletionResult
    from orchestrator.costs import calculate_cost, DEFAULT_PRICING

    result = CompletionResult(
        text="r",
        provider="claude",
        model="claude-sonnet-4-6",
        raw_response={"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}},
    )
    cost = calculate_cost(result, DEFAULT_PRICING)
    assert cost is not None
    assert abs(cost - (3.00 + 15.00)) < 0.001


def test_similarity_fts5_fallback():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod
    import orchestrator.similarity as sim_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()
    sim_mod._backend_cache = None

    try:
        db_mod.init_db()
        backend = sim_mod.get_backend(tmp_path)
        assert isinstance(backend, sim_mod.FTS5Backend)
        backend.upsert(1, "crear tests para modelo User")
        result = backend.query("tests modelo")
        assert isinstance(result, list)
    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        sim_mod._backend_cache = None
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
