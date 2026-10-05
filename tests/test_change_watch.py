"""ChangeWatcher detecta escrituras de conexiones y procesos externos."""

import json
import sqlite3
import subprocess
import sys
import threading
import time

from orchestrator.change_watch import ChangeWatcher
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
