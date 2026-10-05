"""ChangeWatcher detecta escrituras de conexiones y procesos externos."""

import json
import sqlite3
import subprocess
import sys
import threading
import time

from orchestrator.change_watch import ChangeWatcher, activity_fingerprint
from orchestrator.server import _watch_changes_enabled


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
        "runs": "id INTEGER PRIMARY KEY",
        "tool_calls": "id INTEGER PRIMARY KEY",
        "alignments": "id INTEGER PRIMARY KEY",
        "egress_decisions": "id INTEGER PRIMARY KEY",
        "contexts": "id INTEGER PRIMARY KEY, updated_at TEXT",
        "steps": "id INTEGER PRIMARY KEY, started_at TEXT, completed_at TEXT",
        "mcp_invocations": "id INTEGER PRIMARY KEY, tool_category TEXT",
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
