"""RFC-009 security invariants for the local dashboard."""
import http.client
import json
import re
import socket
import threading
import time

import pytest

POST_ROUTES = ("/run", "/rate-run", "/context/1/delete", "/purge-chroma-docs", "/purge-chroma-responses", "/delete-contexts", "/clean/unmapped", "/clear-imports", "/create-context", "/advance-step", "/skip-step", "/add-project", "/project/rename", "/index-docs", "/pricing/refresh", "/models/refresh", "/config/bcentral", "/sync-cc", "/sync-git", "/sync-codex", "/import-context", "/evaluate-run", "/run-doctor", "/run-fix", "/rates/refresh", "/pick-folder", "/chroma-stats/refresh")


def _wait(port):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        try:
            with socket.create_connection(("127.0.0.1", port), .1): return
        except OSError: time.sleep(.02)
    raise AssertionError("server did not start")


@pytest.fixture
def dashboard_server(tmp_path, monkeypatch):
    import orchestrator.db as db
    import orchestrator.paths as paths
    from orchestrator.server import serve
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "runs.db")
    db._local = threading.local(); db.init_db()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    servers = []
    thread = threading.Thread(
        target=serve,
        args=(port, None, False, {}),
        kwargs={"on_server_ready": servers.append, "start_background": False},
        daemon=True,
    )
    thread.start(); _wait(port)
    def request(method, path, body=None, headers=None):
        all_headers = {"Host": f"localhost:{port}"}; all_headers.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request(method, path, body, all_headers); response = conn.getresponse(); data = response.read(); conn.close()
        return response, data
    _, page = request("GET", "/")
    token = re.search(r'orchestrator-session" content="([^"]+)', page.decode()).group(1)
    yield port, request, token
    servers[0].shutdown()
    thread.join(timeout=3)


def _headers(token=None, **extra):
    result = {"Content-Type": "application/json"}
    if token is not None: result["X-Orchestrator-Session"] = token
    result.update(extra); return result


def _security(response):
    assert response.getheader("X-Frame-Options") == "DENY"
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert "frame-ancestors 'none'" in response.getheader("Content-Security-Policy", "")


def test_i1_posts_are_gated_before_effects(dashboard_server, monkeypatch):
    """All 27 routes reject missing/bogus sessions before their handlers run."""
    import subprocess
    import tkinter.filedialog
    from orchestrator.db import _conn
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("picker invoked"))
    monkeypatch.setattr(tkinter.filedialog, "askdirectory", lambda *a, **k: pytest.fail("picker invoked"))
    _, request, _ = dashboard_server
    before = {table: _conn().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("contexts", "steps", "runs", "alignments")}
    for supplied in (None, "invalid"):
        for route in POST_ROUTES:
            response, body = request("POST", route, b"{}", _headers(supplied))
            assert response.status == 403, route
            assert json.loads(body)["reason"] == "session_expired"
    after = {table: _conn().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
             for table in before}
    assert after == before


@pytest.mark.parametrize("method", ("GET", "POST", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT", "UNKNOWN"))
@pytest.mark.parametrize("host", ("attacker.example:80", "localhost", "localhost:9", "LOCALHOST", "[::1]:80"))
def test_i2_host_matrix_precedes_dispatch(dashboard_server, method, host):
    port, request, _ = dashboard_server
    value = f"LOCALHOST:{port}" if host == "LOCALHOST" else host
    response, _ = request(method, "/", b"{}" if method == "POST" else None, {"Host": value})
    if host == "LOCALHOST": assert response.status == (403 if method == "POST" else 200 if method == "GET" else 405)
    else: assert response.status == 421


@pytest.mark.parametrize("headers", ("", "Host: localhost:1\r\nHost: localhost:1\r\n"))
def test_i2_host_missing_or_duplicate_is_421(dashboard_server, headers):
    port, _, _ = dashboard_server
    with socket.create_connection(("127.0.0.1", port)) as raw:
        raw.sendall(("GET / HTTP/1.1\r\n" + headers + "Connection: close\r\n\r\n").encode())
        assert b" 421 " in raw.recv(256)


def test_i3_json_essence(dashboard_server):
    _, request, token = dashboard_server
    for ct in ("text/plain; x=application/json", "application/x-www-form-urlencoded"):
        assert request("POST", "/rates/refresh", b"{}", _headers(token, **{"Content-Type": ct}))[0].status == 415


def test_i4_get_picker_does_not_launch(dashboard_server, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("picker invoked"))
    assert dashboard_server[1]("GET", "/pick-folder")[0].status == 405


def test_i5_gets_are_cache_only(dashboard_server, monkeypatch):
    import orchestrator.rag as rag
    monkeypatch.setattr(rag, "chroma_stats_isolated", lambda: pytest.fail("GET started chroma"))
    for route in ("/rates", "/inspect", "/metrics", "/integrations/status", "/pricing", "/clean-preview"):
        assert dashboard_server[1]("GET", route)[0].status == 200


def test_i6_token_never_leaks(dashboard_server, caplog):
    _, request, token = dashboard_server
    _, page = request("GET", "/"); assert page.decode().count(token) == 1
    for route in ("/rates", "/inspect", "/metrics", "/integrations/status", "/models", "/agents"):
        assert token not in request("GET", route)[1].decode(errors="replace")
    assert token not in caplog.text


def test_i7_frontend_contract(dashboard_server):
    _, request, token = dashboard_server
    assert request("POST", "/create-context", b"{}", _headers(token))[0].status not in (403, 415, 421)
    from orchestrator.dashboard_js import _build_js
    js = _build_js(); assert "refreshStaleRateOnLoad()" in js and "Cuenta:" not in js


def test_i8_origin_and_fetch_site(dashboard_server):
    _, request, token = dashboard_server
    for extra in ({"Origin": "http://attacker.example"}, {"Sec-Fetch-Site": "cross-site"}):
        assert request("POST", "/rates/refresh", b"{}", _headers(token, **extra))[0].status == 403
    assert request("POST", "/rates/refresh", b"{}", _headers(token))[0].status not in (403, 415, 421)


@pytest.mark.parametrize(("values", "server_port", "allowed"), (
    (["localhost"], 80, True), (["127.0.0.1"], 80, True), (["LOCALHOST:80"], 80, True),
    (["localhost"], 8080, False), (["127.0.0.1"], 8080, False), (["[::1]:80"], 80, False),
    (["localhost.:80"], 80, False), (["localhost:abc"], 80, False),
    (["localhost:80", "localhost:80"], 80, False), ([], 80, False),
))
def test_host_allowed(values, server_port, allowed):
    from orchestrator.server import _host_allowed
    assert _host_allowed(values, server_port) is allowed


@pytest.mark.parametrize(("origin", "server_port", "allowed"), (
    (None, 80, True), ("http://localhost", 80, True), ("http://127.0.0.1", 80, True),
    ("http://LOCALHOST:80", 80, True), ("http://localhost", 8080, False),
    ("http://127.0.0.1", 8080, False), ("http://[::1]:80", 80, False),
    ("http://localhost.", 80, False), ("http://localhost:abc", 80, False),
    ("https://localhost:80", 80, False), ("null", 80, False),
))
def test_origin_allowed(origin, server_port, allowed):
    from orchestrator.server import _origin_allowed
    assert _origin_allowed(origin, server_port) is allowed


def test_i5_invalid_origin_port_is_403(dashboard_server):
    _, request, token = dashboard_server
    assert request("POST", "/rates/refresh", b"{}", _headers(token, Origin="http://localhost:abc"))[0].status == 403


def test_i4_chroma_stats_failure_is_json_500(dashboard_server, monkeypatch):
    import orchestrator.rag as rag
    monkeypatch.setattr(rag, "chroma_stats_isolated", lambda: (_ for _ in ()).throw(RuntimeError("chroma failed")))
    _, request, token = dashboard_server
    response, body = request("POST", "/chroma-stats/refresh", b"{}", _headers(token))
    assert response.status == 500
    assert json.loads(body) == {"error": "chroma failed"}


def test_i9_security_headers_and_414(dashboard_server):
    port, request, token = dashboard_server
    for args in (("GET", "/", None, {}), ("POST", "/rates/refresh", b"{}", _headers()), ("GET", "/pick-folder", None, {}), ("POST", "/rates/refresh", b"{}", _headers(token, **{"Content-Type":"text/plain"})), ("GET", "/static/docs-theme.css", None, {})):
        _security(request(*args)[0])
    with socket.create_connection(("127.0.0.1", port)) as raw:
        raw.settimeout(3)
        raw.sendall(b"G" * 65537 + b"\r\n"); result = raw.recv(4096).decode("iso-8859-1")
    assert " 414 " in result
    for name in ("X-Frame-Options", "X-Content-Type-Options", "Content-Security-Policy"): assert name in result


def test_i10_unsupported_verbs_are_405(dashboard_server):
    _, request, _ = dashboard_server
    for method in ("HEAD", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT", "UNKNOWN"):
        response, _ = request(method, "/"); assert response.status == 405; _security(response)


def test_i11_old_token_is_session_expired(dashboard_server):
    # Session values are generated inside serve(), not persisted in the DB/config.
    _, request, token = dashboard_server
    assert request("POST", "/rates/refresh", b"{}", _headers(token + "old"))[0].status == 403


def test_i12_no_bcentral_username(dashboard_server):
    _, request, _ = dashboard_server
    assert "user" not in json.loads(request("GET", "/integrations/status")[1]).get("bcentral", {})


def _fetch_calls(source):
    pos = 0
    while (start := source.find("fetch(", pos)) >= 0:
        depth, quote, escaped, pos = 0, None, False, start + 5
        while pos < len(source):
            char = source[pos]
            if quote:
                if escaped: escaped = False
                elif char == "\\": escaped = True
                elif char == quote: quote = None
            elif char in "'\"`": quote = char
            elif char == "(": depth += 1
            elif char == ")":
                depth -= 1
                if not depth: pos += 1; break
            pos += 1
        yield start, source[start:pos]


def test_i13_fetch_posts_only_live_in_post_json():
    from orchestrator.dashboard_js import _build_js
    js = _build_js(); begin = js.index("function postJson"); end = js.index("function _fmtRunTs", begin)
    for start, call in _fetch_calls(js):
        if re.search(r"method\s*:\s*['\"](?!GET['\"])[^'\"]+", call) or "/pick-folder" in call:
            assert begin <= start < end


def test_i14_script_json_cannot_close_script():
    from orchestrator.dashboard import _json_for_script
    payload = "</script><script>alert(1)</script><!--\u2028"
    encoded = _json_for_script({"task_preview": payload, "project": payload})
    assert "</script" not in encoded and json.loads(encoded)["task_preview"] == payload


@pytest.mark.parametrize("sink", ("X01", "X02", "X03", "X06"))
def test_i15_xss_data_sinks_are_encoded(sink):
    from orchestrator.dashboard import _build_contexts_section, _json_for_script
    payload = "</script><img src=x onerror=alert(1)>\"'"
    if sink in ("X01", "X02"): assert "</script" not in _json_for_script(payload)
    else:
        html = _build_contexts_section([{"id":"1", "title":payload, "status":"active", "steps":[{"id":"2", "order_idx":payload}]}])
        assert payload not in html


def _js_function(source, name):
    start = source.index(f"function {name}(")
    depth = 0
    for pos in range(start, len(source)):
        if source[pos] == "{": depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0: return source[start:pos + 1]
    raise AssertionError(f"unterminated function {name}")


def test_i15_x04_contexts_html_escapes_titles(dashboard_server):
    payload = "<img src=x onerror=alert(1)>"
    _, request, token = dashboard_server
    assert request("POST", "/create-context", json.dumps({"project": "demo", "title": payload}).encode(), _headers(token))[0].status == 201
    response, body = request("GET", "/contexts-html")
    assert response.status == 200 and payload not in body.decode()


def test_i15_x05_rename_aliases_use_data_attributes_and_delegation():
    from orchestrator.dashboard_js import _build_js
    js = _build_js(); start = js.index("if (!window.__regDelegated)")
    fragment = js[start:js.index("const regSection2", start)]
    assert "const ae = escHtml(alias)" in js
    assert "data-alias=\"' + ae + '\"" in fragment
    assert 'document.addEventListener("click"' in fragment
    for handler in ("startRenameProject", "confirmRenameProject", "cancelRenameProject"):
        assert f'onclick="{handler}(' not in js


def test_i15_x07_detail_fields_are_escaped_or_numeric():
    from orchestrator.dashboard_js import _build_js
    js = _build_js(); context_detail = _js_function(js, "openContextDetail"); run_detail = _js_function(js, "openDetail")
    for field in ("data.title", "s.title", "a.checkpoint", "tc.tool_name"):
        assert f"escHtml({field}" in context_detail or f"escHtml({field}" in run_detail
    for field in ("data.id", "s.order_idx", "tc.duration_ms"):
        assert f"safeNumber({field}" in context_detail or f"safeNumber({field}" in run_detail


def test_i15_x08_sse_timestamp_is_escaped():
    from orchestrator.dashboard_js import _build_js
    assert "escHtml(_fmtTs(d.ts))" in _js_function(_build_js(), "_handleTrace")


def test_i15_x09_status_label_fallback_is_escaped():
    from orchestrator.dashboard_js import _build_js
    js = _build_js(); start = js.index("const STATUS_LABELS")
    assert "escHtml(STATUS_LABELS[s] || s)" in js[start:js.index("}).join('')", start)]


def test_i15_x10_index_preview_count_is_numeric():
    from orchestrator.dashboard_js import _build_js
    assert "escHtml(String(Number(f.file_count) || 0))" in _js_function(_build_js(), "_renderPreflightPanel")


def test_i15_x11_javascript_error_uses_text_content():
    from orchestrator.dashboard import build_html
    html = build_html([], selected_project="", projects_extra=[], session_token="token")
    start = html.index("catch(e) {"); error_handler = html[start:html.index("</script>", start)]
    assert "errorBox.textContent" in error_handler
    assert "e.message" in error_handler and "e.stack" in error_handler
    assert "errorBox.insertAdjacentHTML" not in error_handler and "errorBox.innerHTML" not in error_handler


def test_i15_r2_post_json_session_expired_notice_is_once():
    from orchestrator.dashboard_js import _build_js
    fragment = _js_function(_build_js(), "postJson")
    assert "!window.__sessionExpiredNotified" in fragment
    assert "window.__sessionExpiredNotified = true" in fragment


def test_i15_r2_refreshes_missing_rate_on_load():
    from orchestrator.dashboard_js import _build_js
    assert "!rate || rate.rate == null || rate.stale" in _js_function(_build_js(), "refreshStaleRateOnLoad")
