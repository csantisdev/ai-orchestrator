"""ChangeWatcher detecta escrituras de conexiones y procesos externos."""

import json
import http.client
import sqlite3
import socket
import subprocess
import sys
import threading
import time

from orchestrator.change_watch import ChangeWatcher, activity_fingerprint
from orchestrator.server import _watch_changes_enabled, serve


def _wait(events, count=1, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if len(events) >= count:
            return True
        time.sleep(.02)
    return False


def test_external_process_change_publishes(tmp_path):
    path = tmp_path / "watch.db"
    conn = sqlite3.connect(path); conn.execute("CREATE TABLE events (id INTEGER)"); conn.commit(); conn.close()
    events = []
    watcher = ChangeWatcher(path, lambda kind, data: events.append((kind, json.loads(data))))
    connected = threading.Event()
    original_connect = watcher._connect

    def record_connection():
        conn = original_connect()
        connected.set()
        return conn

    watcher._connect = record_connection
    watcher.start()
    assert connected.wait(3)
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('INSERT INTO events VALUES (1)'); c.commit()", str(path)], check=True)
    write_finished = time.monotonic()
    assert _wait(events, timeout=3)
    assert time.monotonic() - write_finished < 3
    watcher.stop()
    assert events[0][0] == "db_changed" and events[0][1]["generation"] == 1


def test_no_change_stop_and_reconnect_without_false_event(tmp_path, monkeypatch):
    path = tmp_path / "watch.db"
    conn = sqlite3.connect(path); conn.execute("CREATE TABLE events (id INTEGER)"); conn.commit(); conn.close()
    events, attempts = [], []
    watcher = ChangeWatcher(path, lambda kind, data: events.append((kind, data)), .02)
    original = watcher._connect
    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise sqlite3.OperationalError("temporal")
        return original()
    monkeypatch.setattr(watcher, "_connect", flaky)
    watcher.start(); time.sleep(.15)
    assert not events and len(attempts) >= 2
    conn = sqlite3.connect(path); conn.execute("INSERT INTO events VALUES (1)"); conn.commit(); conn.close()
    assert _wait(events)
    watcher.stop()
    assert watcher._thread is not None and not watcher._thread.is_alive()


def test_missing_database_is_not_created_and_later_change_publishes(tmp_path, monkeypatch):
    path = tmp_path / "missing.db"
    events = []
    watcher = ChangeWatcher(path, lambda kind, data: events.append((kind, json.loads(data))), .02)
    connected = threading.Event()
    original_version = watcher._data_version

    # La línea base se toma con la primera lectura de data_version: escribir antes sería una carrera.
    def record_baseline(conn):
        version = original_version(conn)
        connected.set()
        return version

    monkeypatch.setattr(watcher, "_data_version", record_baseline)
    watcher.start()
    time.sleep(.15)
    assert not path.exists()

    conn = sqlite3.connect(path); conn.execute("CREATE TABLE events (id INTEGER)"); conn.commit(); conn.close()
    assert connected.wait(3)
    assert not events
    conn = sqlite3.connect(path); conn.execute("INSERT INTO events VALUES (1)"); conn.commit(); conn.close()
    assert _wait(events)
    watcher.stop()
    assert events[0][0] == "db_changed" and events[0][1]["generation"] == 1


def test_serve_can_disable_the_watcher_explicitly():
    assert not _watch_changes_enabled(True, False)
    assert _watch_changes_enabled(False, True)
    assert not _watch_changes_enabled(False, None)


def _activity_database(path):
    conn = sqlite3.connect(path)
    for table, columns in {
        "runs": "id INTEGER PRIMARY KEY, status TEXT",
        "tool_calls": "id INTEGER PRIMARY KEY, status TEXT",
        "alignments": "id INTEGER PRIMARY KEY",
        "egress_decisions": "id INTEGER PRIMARY KEY, decision TEXT, reason_code TEXT",
        "contexts": "id INTEGER PRIMARY KEY, updated_at TEXT",
        "steps": "id INTEGER PRIMARY KEY, started_at TEXT, completed_at TEXT, status TEXT",
        "mcp_invocations": "id INTEGER PRIMARY KEY, tool_category TEXT, status TEXT, is_error INTEGER, reason_code TEXT",
    }.items():
        conn.execute(f"CREATE TABLE {table} ({columns})")
    conn.commit()
    conn.close()


def test_activity_fingerprint_ignores_read_invocations(tmp_path):
    path = tmp_path / "watch.db"
    _activity_database(path)
    events = []
    watcher = ChangeWatcher(path, lambda kind, data: events.append((kind, json.loads(data))),
                            fingerprint=activity_fingerprint)
    connected = threading.Event()
    original_connect = watcher._connect

    def record_connection():
        conn = original_connect()
        connected.set()
        return conn

    watcher._connect = record_connection
    watcher.start()
    assert connected.wait(3)
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"INSERT INTO mcp_invocations (tool_category) VALUES ('read')\"); c.commit()", str(path)], check=True)
    time.sleep(1.2)
    watcher.stop()
    assert not events


def test_activity_fingerprint_publishes_mutations_and_context_updates(tmp_path):
    path = tmp_path / "watch.db"
    _activity_database(path)
    events = []
    watcher = ChangeWatcher(path, lambda kind, data: events.append((kind, json.loads(data))),
                            fingerprint=activity_fingerprint)
    connected = threading.Event()
    original_connect = watcher._connect

    def record_connection():
        conn = original_connect()
        connected.set()
        return conn

    watcher._connect = record_connection
    watcher.start()
    assert connected.wait(3)
    write_finished = time.monotonic()
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"INSERT INTO mcp_invocations (tool_category) VALUES ('workflow_mutation')\"); c.commit()", str(path)], check=True)
    assert _wait(events, timeout=3)
    assert time.monotonic() - write_finished < 3
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"INSERT INTO contexts (updated_at) VALUES ('first')\"); c.commit()", str(path)], check=True)
    assert _wait(events, count=2, timeout=3)
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"UPDATE contexts SET updated_at='second' WHERE id=1\"); c.commit()", str(path)], check=True)
    assert _wait(events, count=3, timeout=3)
    watcher.stop()
    assert [event[1]["generation"] for event in events] == [1, 2, 3]


def test_activity_fingerprint_publishes_run_status_update(tmp_path):
    path = tmp_path / "watch.db"
    _activity_database(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO runs (status) VALUES ('running')")
    conn.commit(); conn.close()
    events, connected = [], threading.Event()
    watcher = ChangeWatcher(path, lambda kind, data: events.append((kind, json.loads(data))),
                            fingerprint=activity_fingerprint)
    original_connect = watcher._connect

    def record_connection():
        connection = original_connect()
        connected.set()
        return connection

    watcher._connect = record_connection
    watcher.start()
    assert connected.wait(3)
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"UPDATE runs SET status='done' WHERE id=1\"); c.commit()", str(path)], check=True)
    assert _wait(events, timeout=3)
    watcher.stop()
    assert events[0][0] == "db_changed"


def test_activity_fingerprint_publishes_completed_mcp_mutation(tmp_path):
    path = tmp_path / "watch.db"
    _activity_database(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO mcp_invocations (tool_category, status, is_error) VALUES ('workflow_mutation', 'in_progress', 0)")
    conn.commit(); conn.close()
    events, connected = [], threading.Event()
    watcher = ChangeWatcher(path, lambda kind, data: events.append((kind, json.loads(data))),
                            fingerprint=activity_fingerprint)
    original_connect = watcher._connect

    def record_connection():
        connection = original_connect()
        connected.set()
        return connection

    watcher._connect = record_connection
    watcher.start()
    assert connected.wait(3)
    subprocess.run([sys.executable, "-c", "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"UPDATE mcp_invocations SET status='success', is_error=1, reason_code='finished' WHERE id=1\"); c.commit()", str(path)], check=True)
    assert _wait(events, timeout=3)
    watcher.stop()
    assert events[0][0] == "db_changed"


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _sse_connection(port):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    conn.request("GET", "/events", headers={"Host": f"localhost:{port}"})
    response = conn.getresponse()
    assert response.status == 200
    return conn, response


def _read_sse_event(response, timeout):
    response.fp.raw._sock.settimeout(timeout)
    lines = []
    try:
        while True:
            line = response.fp.readline()
            if not line:
                return ""
            lines.append(line.decode("utf-8"))
            if line == b"\n":
                return "".join(lines)
    except (TimeoutError, OSError):
        return ""


def test_live_server_refreshes_external_mutations_but_not_mcp_reads(tmp_path, monkeypatch):
    """El SSE del servidor usa la huella también para escrituras de otro proceso."""
    import orchestrator.db as db
    import orchestrator.paths as paths
    import orchestrator.server as server_module

    db_path = tmp_path / "runs.db"
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", db_path)
    monkeypatch.setattr(server_module, "HOME_DIR", tmp_path)
    monkeypatch.setattr(db, "_local", threading.local())
    db.init_db()
    db._conn().execute("INSERT INTO runs (ts, project, status, task) VALUES ('t', 'p', 'running', 'x')")
    db._conn().commit()
    port, servers, ready = _free_port(), [], threading.Event()

    def on_ready(server):
        servers.append(server)
        ready.set()

    thread = threading.Thread(
        target=serve, args=(port, None, False, {}),
        kwargs={"on_server_ready": on_ready, "start_background": False, "watch_changes": True},
        daemon=True,
    )
    thread.start()
    assert ready.wait(3)
    # El watcher conserva el intervalo por defecto; esperamos su línea base antes de escribir.
    time.sleep(1.1)
    conn, response = _sse_connection(port)
    try:
        time.sleep(.05)
        subprocess.run([
            sys.executable, "-c",
            "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute(\"UPDATE runs SET status='done' WHERE id=1\"); "
            "c.commit()",
            str(db_path),
        ], check=True)
        assert "event: db_changed" in _read_sse_event(response, 3)
    finally:
        conn.close()

    conn, response = _sse_connection(port)
    try:
        time.sleep(.05)
        subprocess.run([
            sys.executable, "-c",
            "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute(\"INSERT INTO mcp_invocations "
            "(ts,request_id,server_instance_id,client_surface,transport,capability_profile,tool_name,tool_category,input_hash,output_hash,status,created_at) "
            "VALUES ('t','read-1','s','c','t','p','read','read','i','o','success','t')\"); c.commit()",
            str(db_path),
        ], check=True)
        assert "event: db_changed" not in _read_sse_event(response, 3.5)
    finally:
        conn.close()
        servers[0].shutdown()
        thread.join(timeout=3)
        assert not thread.is_alive()
