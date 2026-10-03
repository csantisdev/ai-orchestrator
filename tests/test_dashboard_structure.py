"""Contratos estructurales del dashboard heredado (spec §24.3.1).

Complementan la instantánea dorada: los IDs que el JS busca existen, los handlers en
línea apuntan a funciones declaradas, cada pestaña tiene su panel y el servidor sirve
la página, `/contexts-html` y `/events`.
"""

from __future__ import annotations

import http.client
import re
import socket
import threading
import time

import pytest

from tests.test_dashboard_equivalence import CONTEXTS, RUNS, _pin_clock, split_page

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
    html, js = split_page(page)
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

    assert tabs == ["actividad", "flujos", "proyectos", "metrics", "datos", "config"]
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
    db._local = threading.local()
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
    assert "Object.assign(window, {" in page


def test_server_serves_the_contexts_fragment(server):
    response, body = _get(server, "/contexts-html")

    assert response.status == 200
    assert response.getheader("Content-Type", "").startswith("text/html")


def test_server_opens_the_event_stream(server):
    response, _ = _get(server, "/events", read=False)

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"
