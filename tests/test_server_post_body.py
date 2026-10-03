"""Un POST válido nunca pierde su respuesta aunque el handler no lea el cuerpo.

El servidor es HTTP/1.0 y cierra después de cada respuesta. En Windows, cerrar un
socket con bytes de la petición sin leer envía un RST y el cliente ve la conexión
anulada en lugar de la respuesta ya escrita. Varios handlers (sync, refresh, doctor,
pick-folder, borrado de contexto) no leen el cuerpo, así que el servidor lo lee entero
antes de despachar.
"""

from __future__ import annotations

import http.client
import io
import json
import re
import socket
import threading
import time

import pytest


@pytest.fixture
def server(tmp_path, monkeypatch):
    import orchestrator.db as db
    import orchestrator.paths as paths
    import orchestrator.rates as rates
    from orchestrator.server import serve

    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db, "_local", threading.local())
    monkeypatch.setattr(rates, "refresh_rate", lambda config: {"rate": 1.0})
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
    until = time.monotonic() + 3
    while time.monotonic() < until:
        try:
            socket.create_connection(("127.0.0.1", port), 0.1).close()
            break
        except OSError:
            time.sleep(0.02)

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body, {"Host": f"localhost:{port}", **(headers or {})})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    _, page = request("GET", "/")
    token = re.search(rb'orchestrator-session" content="([^"]+)', page).group(1).decode()
    yield request, token, port
    servers[0].shutdown()
    thread.join(timeout=3)


def test_handler_that_ignores_the_body_still_returns_its_response(server):
    request, token, _ = server
    body = json.dumps({"pad": "x" * 900_000}).encode()
    headers = {"Content-Type": "application/json", "X-Orchestrator-Session": token}

    results = [request("POST", "/rates/refresh", body, headers) for _ in range(40)]

    assert [status for status, _ in results] == [200] * 40
    assert all(json.loads(data) == {"rate": 1.0} for _, data in results)


def test_handlers_that_read_the_body_still_receive_it(server):
    request, token, _ = server
    headers = {"Content-Type": "application/json", "X-Orchestrator-Session": token}
    payload = {"project": "mi-proyecto", "title": "Flujo de prueba", "steps": ["uno"]}

    status, data = request("POST", "/create-context", json.dumps(payload).encode(), headers)

    assert status == 201, data
    assert json.loads(data)["title"] == "Flujo de prueba"
    assert [step["title"] for step in json.loads(data)["steps"]] == ["uno"]


def test_a_body_shorter_than_its_content_length_is_rejected(server):
    _, token, port = server
    with socket.create_connection(("127.0.0.1", port)) as raw:
        raw.settimeout(10)
        raw.sendall(
            f"POST /rates/refresh HTTP/1.1\r\nHost: localhost:{port}\r\n"
            f"Content-Type: application/json\r\nX-Orchestrator-Session: {token}\r\n"
            "Content-Length: 100\r\n\r\n{}".encode()
        )
        raw.shutdown(socket.SHUT_WR)
        response = io.BytesIO()
        while chunk := raw.recv(4096):
            response.write(chunk)

    assert b" 400 " in response.getvalue().split(b"\r\n", 1)[0]
