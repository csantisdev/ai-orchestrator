"""Un POST válido nunca pierde su respuesta aunque el handler no lea el cuerpo.

El servidor es HTTP/1.0 y cierra después de cada respuesta. En Windows, cerrar un
socket con bytes de la petición sin leer envía un RST y el cliente ve la conexión
anulada en lugar de la respuesta ya escrita. Varios handlers (sync, refresh, doctor,
pick-folder, borrado de contexto) no leen el cuerpo, así que el servidor lo lee entero
después de validar la sesión y antes de despachar.
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

SECURITY_HEADERS = (b"X-Frame-Options: DENY", b"X-Content-Type-Options: nosniff")


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
    servers = []
    ready = threading.Event()

    def on_ready(srv):
        servers.append(srv)
        ready.set()

    thread = threading.Thread(
        target=serve, args=(0, None, False, {}),
        kwargs={"on_server_ready": on_ready, "start_background": False}, daemon=True,
    )
    thread.start()
    assert ready.wait(5), "el servidor no arrancó"
    port = servers[0].server_address[1]

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


def _raw(port, payload: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port)) as raw:
        raw.settimeout(15)
        raw.sendall(payload)
        raw.shutdown(socket.SHUT_WR)
        response = io.BytesIO()
        while chunk := raw.recv(4096):
            response.write(chunk)
    return response.getvalue()


def _post_head(port, token, extra=""):
    return (
        f"POST /rates/refresh HTTP/1.1\r\nHost: localhost:{port}\r\n"
        f"Content-Type: application/json\r\nX-Orchestrator-Session: {token}\r\n{extra}"
    )


def test_handler_that_ignores_the_body_still_returns_its_response(server):
    request, token, _ = server
    body = json.dumps({"pad": "x" * 900_000}).encode()
    headers = {"Content-Type": "application/json", "X-Orchestrator-Session": token}

    results = [request("POST", "/rates/refresh", body, headers) for _ in range(40)]

    assert [status for status, _ in results] == [200] * 40
    assert all(json.loads(data) == {"rate": 1.0} for _, data in results)


def test_rejections_with_a_large_body_still_return_their_response(server):
    request, token, _ = server
    body = json.dumps({"pad": "x" * 900_000}).encode()
    cases = [
        ({"Content-Type": "application/json"}, 403),
        ({"Content-Type": "application/json", "X-Orchestrator-Session": "otro"}, 403),
        ({"Content-Type": "application/json", "X-Orchestrator-Session": token, "Origin": "http://evil.example"}, 403),
        ({"Content-Type": "text/plain", "X-Orchestrator-Session": token}, 415),
    ]

    for headers, expected in cases:
        assert [request("POST", "/rates/refresh", body, headers)[0] for _ in range(10)] == [expected] * 10


def test_handlers_that_read_the_body_receive_it_unchanged(server):
    request, token, _ = server
    headers = {"Content-Type": "application/json", "X-Orchestrator-Session": token}
    payload = {"project": "mi-proyecto", "title": "Flujo ñandú ✓", "steps": ["uno"]}

    status, data = request("POST", "/create-context", json.dumps(payload, ensure_ascii=False).encode(), headers)

    assert status == 201, data
    assert json.loads(data)["title"] == "Flujo ñandú ✓"
    assert [step["title"] for step in json.loads(data)["steps"]] == ["uno"]


def test_a_body_shorter_than_its_content_length_is_a_400_that_closes(server):
    _, token, port = server

    response = _raw(port, (_post_head(port, token, "Content-Length: 100\r\n") + "\r\n{}").encode())

    head = response.split(b"\r\n\r\n", 1)[0]
    assert b" 400 " in head.split(b"\r\n", 1)[0]
    assert b"Connection: close" in head
    assert all(header in head for header in SECURITY_HEADERS)


def test_an_unauthenticated_post_does_not_wait_for_its_body(server):
    """El cuerpo se lee después de validar la sesión: un cliente sin token que declara
    500 KB y no los envía recibe su 403 sin que el servidor espere el buffer."""
    _, _, port = server
    with socket.create_connection(("127.0.0.1", port)) as raw:
        raw.settimeout(15)
        raw.sendall(
            f"POST /rates/refresh HTTP/1.1\r\nHost: localhost:{port}\r\n"
            "Content-Type: application/json\r\nContent-Length: 500000\r\n\r\n".encode()
        )
        started = time.monotonic()
        first = raw.recv(4096)
        elapsed = time.monotonic() - started

    assert b" 403 " in first.split(b"\r\n", 1)[0]
    assert elapsed < 3, elapsed


@pytest.mark.parametrize("framing, body", [
    ("Content-Length: 2\r\nContent-Length: 50\r\n", "{}"),
    ("Content-Length: 2\r\nContent-Length: 2\r\n", "{}"),
    ("Content-Length: 2\r\nTransfer-Encoding: chunked\r\n", "{}"),
    ("Content-Length: 1_0\r\n", '{"a": 123}'),
    ("Content-Length: +2\r\n", "{}"),
])
def test_ambiguous_framing_is_rejected(server, framing, body):
    _, token, port = server

    response = _raw(port, (_post_head(port, token, framing) + "\r\n" + body).encode())

    status_line = response.split(b"\r\n", 1)[0]
    assert b" 400 " in status_line
    assert b"Connection: close" in response.split(b"\r\n\r\n", 1)[0]
