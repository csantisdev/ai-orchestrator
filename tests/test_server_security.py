"""Invariantes básicas de seguridad del servidor del dashboard (RFC-009)."""

import http.client
import json
import re
import threading
import time


def _wait(port):
    import socket
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), .1):
                return
        except OSError:
            time.sleep(.05)
    raise AssertionError("server did not start")


def test_i2_i3_i4_i6_i8_i9_i10_i11_dashboard_session_and_rejections(tmp_path, monkeypatch):
    """I2, I3, I4, I6, I8, I9, I10 e I11: pipeline HTTP central."""
    import orchestrator.db as db
    import orchestrator.paths as paths
    from orchestrator.server import serve
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "runs.db")
    db._local = threading.local()
    db.init_db()
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    threading.Thread(target=serve, args=(port, None, False, {}), daemon=True).start()
    _wait(port)

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse(); data = response.read(); conn.close()
        return response, data

    response, page = request("GET", "/")
    assert response.status == 200
    token = re.search(r'orchestrator-session" content="([^"]+)', page.decode()).group(1)
    for header in ("X-Frame-Options", "X-Content-Type-Options", "Content-Security-Policy"):
        assert response.getheader(header)
    response, _ = request("PUT", "/", headers={"Host": f"localhost:{port}"})
    assert response.status == 405
    response, _ = request("GET", "/", headers={"Host": "attacker.example:80"})
    assert response.status == 421
    response, _ = request("GET", "/pick-folder")
    assert response.status == 405
    payload = b"{}"
    base = {"Content-Type": "application/json", "Content-Length": "2"}
    response, data = request("POST", "/rates/refresh", payload, base)
    assert response.status == 403 and json.loads(data)["reason"] == "session_expired"
    base["X-Orchestrator-Session"] = token
    base["Content-Type"] = "text/plain; x=application/json"
    response, _ = request("POST", "/rates/refresh", payload, base)
    assert response.status == 415
    base["Content-Type"] = "application/json"
    base["Origin"] = "http://attacker.example"
    response, _ = request("POST", "/rates/refresh", payload, base)
    assert response.status == 403


def test_i1_all_mutating_routes_are_gated_before_dispatch(tmp_path, monkeypatch):
    """Every D0 POST rejects absent and bogus session tokens before its handler."""
    import orchestrator.db as db
    import orchestrator.paths as paths
    from orchestrator.server import serve
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "runs.db")
    db._local = threading.local(); db.init_db()
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    threading.Thread(target=serve, args=(port, None, False, {}), daemon=True).start(); _wait(port)
    routes = ["/run", "/rate-run", "/context/1/delete", "/purge-chroma-docs", "/purge-chroma-responses", "/delete-contexts",
              "/clean/unmapped", "/clear-imports", "/create-context", "/advance-step", "/skip-step",
              "/add-project", "/project/rename", "/index-docs", "/pricing/refresh", "/models/refresh",
              "/config/bcentral", "/sync-cc", "/sync-git", "/sync-codex", "/import-context",
              "/evaluate-run", "/run-doctor", "/run-fix", "/rates/refresh", "/pick-folder", "/chroma-stats/refresh"]
    for token in (None, "wrong"):
        for route in routes:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            headers = {"Content-Type": "application/json"}
            if token: headers["X-Orchestrator-Session"] = token
            conn.request("POST", route, b"{}", headers)
            response = conn.getresponse(); data = json.loads(response.read()); conn.close()
            assert response.status == 403 and data["reason"] == "session_expired", route


def test_i5_gets_are_cache_only_and_chroma_pending_is_explicit(tmp_path, monkeypatch):
    import orchestrator.db as db
    import orchestrator.paths as paths
    import orchestrator.rag as rag
    from orchestrator.server import serve
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path); monkeypatch.setattr(paths, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(rag, "chroma_stats_isolated", lambda: (_ for _ in ()).throw(AssertionError("GET launched chroma")))
    db._local = threading.local(); db.init_db()
    import socket
    with socket.socket() as s: s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    threading.Thread(target=serve, args=(port, None, False, {}), daemon=True).start(); _wait(port)
    for route in ("/rates", "/inspect", "/metrics", "/integrations/status", "/pricing", "/clean-preview"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3); conn.request("GET", route)
        response = conn.getresponse(); body = response.read(); conn.close(); assert response.status == 200, route
        if route == "/inspect": assert json.loads(body)["chroma"] is None


def test_i7_i13_frontend_uses_explicit_authenticated_post_helper():
    from orchestrator.dashboard_js import _build_js
    js = _build_js()
    assert "window.fetch =" not in js
    assert "function postJson(url, body)" in js
    assert "postJson(\"/pick-folder\"" in js
    assert "refreshStaleRateOnLoad()" in js
    assert not re.search(r"fetch\([^\n]*method\s*:\s*['\"]POST", js)


def test_i12_i14_i15_serializers_and_html_sinks():
    from orchestrator.dashboard import _json_for_script, _build_contexts_section
    payload = "</script><script>alert(1)</script><!--\u2028"
    assert "</script" not in _json_for_script(payload)
    html = _build_contexts_section([{"id": "1", "title": payload, "status": "active", "steps": []}])
    assert payload not in html and "data-ctx-id=\"1\"" in html
