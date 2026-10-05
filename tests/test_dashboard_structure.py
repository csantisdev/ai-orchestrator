"""Contratos estructurales del dashboard heredado (spec §24.3.1).

Complementan la instantánea dorada: los IDs que el JS busca existen, los handlers en
línea apuntan a funciones declaradas, cada pestaña tiene su panel y el servidor sirve
la página, `/contexts-html` y `/events`.
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from tests.test_dashboard_equivalence import CONTEXTS, RUNS, _pin_clock

LITERAL_ID_LOOKUP = re.compile(r"getElementById\(\s*[\"']([A-Za-z0-9_-]+)[\"']\s*\)")
ID_ATTRIBUTE = re.compile(r"\bid\s*=\s*\\?[\"']([A-Za-z0-9_-]+)")
ID_PROPERTY = re.compile(r"\.id\s*=\s*[\"']([A-Za-z0-9_-]+)")
INLINE_HANDLER = re.compile(r"\bon[a-z]+=\\?[\"']([A-Za-z_$][\w$]*)\(")
FUNCTION = re.compile(r"^(?:async )?function ([\w$]+)\(", re.M)
TAB_BUTTON = re.compile(r"switchTab\('(\w+)'\)")


@pytest.fixture
def page_and_script(monkeypatch):
    from orchestrator.dashboard import _build_contexts_section, build_html

    _pin_clock(monkeypatch)
    page = build_html(RUNS, session_token="token-fijo")
    from orchestrator.dashboard_js import _build_js

    html, js = page, _build_js()
    return html + _build_contexts_section(CONTEXTS), js


# Faltantes conocidos del código heredado: `clearImports` lee estos IDs, pero ningún
# elemento los declara ni la función se llama desde la página. Se conservan tal cual
# en la separación mecánica; cualquier faltante nuevo hace fallar el test.
KNOWN_MISSING_IDS = {"imp-clear-project", "imp-clear-provider", "imp-clear-status"}


def test_every_literal_element_lookup_has_a_matching_id(page_and_script):
    html, js = page_and_script
    looked_up = set(LITERAL_ID_LOOKUP.findall(html + js))
    declared = set(ID_ATTRIBUTE.findall(html + js)) | set(ID_PROPERTY.findall(js))

    assert looked_up, "no se encontró ningún getElementById literal"
    assert looked_up - declared == KNOWN_MISSING_IDS


def test_every_inline_handler_calls_a_declared_function(page_and_script):
    html, js = page_and_script
    handlers = set(INLINE_HANDLER.findall(html + js))
    functions = set(FUNCTION.findall(js))

    assert handlers, "no se encontró ningún handler en línea"
    assert sorted(handlers - functions) == []


def test_every_tab_button_has_its_panel(page_and_script):
    html, _ = page_and_script
    tabs = TAB_BUTTON.findall(html)

    assert tabs == ["actividad", "flujos", "proyectos", "datos", "config"]
    for tab in tabs:
        assert f'id="tab-btn-{tab}"' in html and f'<div id="tab-{tab}"' in html


def _wait(port):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.1):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError("server did not start")


@pytest.fixture
def server(tmp_path, monkeypatch):
    import orchestrator.db as db
    import orchestrator.paths as paths
    from orchestrator.server import serve

    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db, "_local", threading.local())
    db.init_db()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    servers = []
    thread = threading.Thread(
        target=serve, args=(port, None, False, {}),
        kwargs={"on_server_ready": servers.append, "start_background": False}, daemon=True,
    )
    thread.start()
    _wait(port)
    yield port
    servers[0].shutdown()
    thread.join(timeout=3)


def _get(port, path, read=True):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path, headers={"Host": f"localhost:{port}"})
    response = conn.getresponse()
    body = response.read() if read else b""
    conn.close()
    return response, body


def test_server_serves_the_page_with_every_tab(server):
    response, body = _get(server, "/")
    page = body.decode("utf-8")

    assert response.status == 200
    assert all(f'<div id="tab-{tab}"' in page for tab in TAB_BUTTON.findall(page))
    assert re.search(r"/static/dashboard/[0-9a-f]{12}/legacy/startup.js", page)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado (D1 lo agrega al CI)")
def test_switch_tab_shows_one_panel_activates_its_button_and_loads_once():
    harness = Path(__file__).parent / "js" / "switch_tab_harness.mjs"
    core = Path(__file__).parent.parent / "orchestrator" / "static" / "dashboard" / "legacy" / "core.js"

    steps = json.loads(subprocess.run(
        ["node", str(harness), str(core)], capture_output=True, text=True, check=True, timeout=30,
    ).stdout)

    for step in steps:
        assert step["visible"] == [step["tab"]] and step["active"] == [step["tab"]], step
    first_visit = {step["tab"]: step["calls"] for step in steps[:5]}
    assert first_visit == {"actividad": [], "flujos": ["_refreshContexts"], "proyectos": ["loadProyectos"],
                           "datos": ["loadDatos"], "config": ["loadConfig"]}
    second_visit = {step["tab"]: step["calls"] for step in steps[5:]}
    assert second_visit == {"proyectos": [], "datos": [], "config": [],
                            "flujos": ["_refreshContexts"], "actividad": []}


def test_contexts_fragment_keeps_its_ids_and_handlers(server):
    from orchestrator.db import _conn

    conn = _conn()
    conn.execute(
        "INSERT INTO contexts (ts, updated_at, project, title, status) VALUES "
        "('2026-06-01T00:00:00+00:00', '2026-06-01T00:00:00+00:00', 'mi-proyecto', ?, 'active')",
        ("Flujo <b>'beta'</b>",),
    )
    ctx_id = conn.execute("SELECT max(id) FROM contexts").fetchone()[0]
    conn.execute("INSERT INTO steps (context_id, order_idx, title, status) VALUES (?, 1, 'Paso', 'in_progress')",
                 (ctx_id,))
    conn.commit()

    response, body = _get(server, "/contexts-html")
    fragment = body.decode("utf-8")

    assert response.status == 200
    assert response.getheader("Content-Type", "").startswith("text/html")
    assert f'data-ctx-id="{ctx_id}"' in fragment
    assert 'onclick="deleteContextFromButton(this)"' in fragment
    assert "<b>'beta'</b>" not in fragment and "&lt;b&gt;" in fragment
    assert set(INLINE_HANDLER.findall(fragment)) <= set(FUNCTION.findall(_build_js_text()))


def _build_js_text():
    from orchestrator.dashboard_js import _build_js

    return _build_js()


def test_event_stream_delivers_published_events(server):
    from orchestrator.sse import BUS

    def subscribers():
        with BUS._lock:
            return len(BUS._subscribers)

    def wait_until(condition, seconds=3.0):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if condition():
                return True
            time.sleep(0.02)
        return False

    baseline = subscribers()
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("GET", "/events", headers={"Host": f"localhost:{server}"})
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"
    assert wait_until(lambda: subscribers() > baseline), "el handler SSE no se suscribió"

    BUS.publish("run_update", '{"id": 42}')
    frame = []
    try:
        while not frame or frame[-1] != b"\n":
            line = response.fp.readline()
            if not line:
                break
            if line.startswith(b":") and not frame:
                continue
            frame.append(line if line.strip() else b"\n")
    finally:
        response.close()
        conn.close()
        # El handler sigue esperando en q.get(); un evento más lo hace escribir en el
        # socket cerrado, salir y desuscribirse, sin dejar estado en el BUS global.
        assert wait_until(lambda: BUS.publish("noop", "{}") or subscribers() == baseline), \
            "el handler SSE no liberó su suscripción"

    text = b"".join(frame).decode("utf-8")
    assert "event: run_update" in text and 'data: {"id": 42}' in text


def test_project_selector_groups_registered_and_detected_aliases():
    from orchestrator.dashboard import _project_select_options

    html = _project_select_options(["mi-proyecto", "<x>&\"", "suelto"], {"mi-proyecto"}, "suelto")
    assert html.index('<optgroup label="Registrados">') < html.index('value="mi-proyecto"')
    assert html.index('<optgroup label="Otros alias detectados">') < html.index('value="suelto"')
    assert 'value="suelto" selected' in html
    assert "<x>" not in html and "&lt;x&gt;&amp;&quot;" in html
    plain = _project_select_options(["a", "b"], {"a", "b"}, "")
    assert "optgroup" not in plain and plain.count("<option") == 3
