"""Tests para Content-Type validation en server.py y lógica de skip en rag.py."""
import json
import shutil
import tempfile
import threading
import time
import http.client
from pathlib import Path


# ── rag._scan_files skip logic ──────────────────────────────────────────────

def test_scan_files_skips_single_part_dir():
    from orchestrator.rag import _scan_files
    tmp = tempfile.mkdtemp()
    try:
        p = Path(tmp)
        (p / "node_modules").mkdir()
        (p / "node_modules" / "pkg.js").write_text("code", encoding="utf-8")
        (p / "app.py").write_text("code", encoding="utf-8")
        names = {f.name for f in _scan_files(p)}
        assert "app.py" in names
        assert "pkg.js" not in names
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_scan_files_skips_multipart_builtin_paths():
    from orchestrator.rag import _scan_files
    tmp = tempfile.mkdtemp()
    try:
        p = Path(tmp)
        for d in ("storage/logs", "bootstrap/cache", "public/build"):
            (p / d).mkdir(parents=True)
            (p / d / "noise.log").write_text("data", encoding="utf-8")
        (p / "app.py").write_text("import os", encoding="utf-8")
        names = {f.name for f in _scan_files(p)}
        assert "app.py" in names
        assert "noise.log" not in names
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_scan_files_extra_skip_multipart():
    from orchestrator.rag import _scan_files
    tmp = tempfile.mkdtemp()
    try:
        p = Path(tmp)
        (p / "custom" / "cache").mkdir(parents=True)
        (p / "custom" / "cache" / "data.json").write_text("{}", encoding="utf-8")
        (p / "app.py").write_text("import os", encoding="utf-8")
        names = {f.name for f in _scan_files(p, extra_skip=frozenset({"custom/cache"}))}
        assert "app.py" in names
        assert "data.json" not in names
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_scan_files_code_extensions_expanded():
    from orchestrator.rag import _scan_files, _CODE_EXTENSIONS
    for ext in (".php", ".ts", ".tsx", ".java", ".go", ".rs"):
        assert ext in _CODE_EXTENSIONS, f"{ext} missing from _CODE_EXTENSIONS"


# ── server Content-Type validation ──────────────────────────────────────────

def _wait_for_port(port: int, timeout: float = 3.0) -> bool:
    import socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def test_server_post_requires_json_ct():
    """All POST endpoints return 415 when Content-Type is not application/json."""
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod
    from orchestrator.server import serve

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    orig_home = paths_mod.HOME_DIR
    orig_db = paths_mod.DB_PATH
    port = 19977

    def _run():
        paths_mod.HOME_DIR = tmp_path
        paths_mod.DB_PATH = tmp_path / "runs.db"
        db_mod._local = threading.local()
        db_mod.init_db()
        serve(port, None, False, {})

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    try:
        assert _wait_for_port(port), "server did not start in time"

        mutating_endpoints = [
            "/run",
            "/rate-run",
            "/purge-chroma-docs",
            "/purge-chroma-responses",
            "/delete-contexts",
            "/clean/unmapped",
            "/clear-imports",
            "/create-context",
            "/advance-step",
            "/skip-step",
            "/add-project",
            "/index-docs",
            "/pricing/refresh",
            "/models/refresh",
        ]
        for ep in mutating_endpoints:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            payload = b'{"test":1}'
            conn.request("POST", ep, body=payload, headers={
                "Content-Type": "text/plain",
                "Content-Length": str(len(payload)),
            })
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 415, (
                f"{ep} should return 415 for text/plain Content-Type, got {resp.status}"
            )
            conn.close()

        # Correct Content-Type must not return 415
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        body = json.dumps({"project": "x", "task": "y"}).encode()
        conn.request("POST", "/run", body=body, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        resp.read()
        assert resp.status != 415, (
            f"/run with application/json should not return 415, got {resp.status}"
        )
        conn.close()

    finally:
        paths_mod.HOME_DIR = orig_home
        paths_mod.DB_PATH = orig_db
        db_mod._local = threading.local()
        shutil.rmtree(tmp, ignore_errors=True)


def test_pricing_endpoints(monkeypatch):
    """GET /pricing y POST /pricing/refresh devuelven la tabla efectiva y su fuente."""
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod
    import orchestrator.catalog as catalog_mod
    from orchestrator.server import serve

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    orig_home = paths_mod.HOME_DIR
    orig_db = paths_mod.DB_PATH
    monkeypatch.setattr(catalog_mod, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")
    port = 19978

    def _run():
        paths_mod.HOME_DIR = tmp_path
        paths_mod.DB_PATH = tmp_path / "runs.db"
        db_mod._local = threading.local()
        db_mod.init_db()
        serve(port, None, False, {})

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    try:
        assert _wait_for_port(port), "server did not start in time"

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/pricing")
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        assert resp.status == 200
        assert data["source"] in ("config", "cache", "remote", "static", "default")
        assert "claude-sonnet-4-6" in data["pricing"]

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        body = b"{}"
        conn.request("POST", "/pricing/refresh", body=body, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        assert resp.status == 200
        assert data["source"] in ("config", "cache", "remote", "static", "default")

    finally:
        paths_mod.HOME_DIR = orig_home
        paths_mod.DB_PATH = orig_db
        db_mod._local = threading.local()
        shutil.rmtree(tmp, ignore_errors=True)


def test_models_endpoints(monkeypatch):
    """GET /models y POST /models/refresh no rompen el servidor sin proveedores configurados."""
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod
    import orchestrator.model_discovery as model_discovery_mod
    from orchestrator.server import serve

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    orig_home = paths_mod.HOME_DIR
    orig_db = paths_mod.DB_PATH
    monkeypatch.setattr(model_discovery_mod, "MODELS_CACHE_PATH", tmp_path / "models-cache.json")
    port = 19979

    def _run():
        paths_mod.HOME_DIR = tmp_path
        paths_mod.DB_PATH = tmp_path / "runs.db"
        db_mod._local = threading.local()
        db_mod.init_db()
        serve(port, None, False, {})

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    try:
        assert _wait_for_port(port), "server did not start in time"

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/models")
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        assert resp.status == 200
        assert data["models"] == []

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        body = b"{}"
        conn.request("POST", "/models/refresh", body=body, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        assert resp.status == 200
        assert data["providers"] == {}

    finally:
        paths_mod.HOME_DIR = orig_home
        paths_mod.DB_PATH = orig_db
        db_mod._local = threading.local()
        shutil.rmtree(tmp, ignore_errors=True)


def test_router_cost_persisted():
    """router_cost_usd se persiste en el run cuando el router calcula su costo."""
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    orig_home = paths_mod.HOME_DIR
    orig_db = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH = tmp_path / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()
        from orchestrator.providers.base import CompletionResult

        run_id = db_mod.insert_run("proj", "tarea", "deepseek", "deepseek-v4-flash")
        result = CompletionResult(
            text="respuesta",
            provider="deepseek",
            model="deepseek-v4-flash",
            raw_response={"usage": {"input_tokens": 200, "output_tokens": 100}},
        )
        db_mod.update_run(
            run_id, result,
            duration_ms=500,
            routing_reason="auto",
            cost_usd=0.001,
            router_cost_usd=0.000042,
        )
        row = db_mod.get_run(run_id)
        assert row["router_cost_usd"] == 0.000042
        assert row["cost_usd"] == 0.001
    finally:
        db_mod._local = threading.local()
        paths_mod.HOME_DIR = orig_home
        paths_mod.DB_PATH = orig_db
        shutil.rmtree(tmp, ignore_errors=True)
