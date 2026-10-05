"""Vigilancia liviana de cambios SQLite para refrescar proyecciones."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


_active: Optional["ChangeWatcher"] = None
_active_lock = threading.Lock()


def activity_fingerprint(conn: sqlite3.Connection) -> tuple:
    """Huella barata de lo que muestran las proyecciones: las lecturas MCP no la cambian."""
    return tuple(conn.execute("""
        SELECT
            (SELECT MAX(id) FROM runs),
            (SELECT MAX(id) FROM tool_calls),
            (SELECT MAX(id) FROM alignments),
            (SELECT MAX(id) FROM egress_decisions),
            (SELECT MAX(id) FROM contexts),
            (SELECT MAX(id) FROM steps),
            (SELECT MAX(id) FROM mcp_invocations WHERE tool_category != 'read'),
            (SELECT MAX(updated_at) FROM contexts),
            (SELECT MAX(started_at) FROM steps),
            (SELECT MAX(completed_at) FROM steps),
            (SELECT COUNT(*) FROM steps),
            (SELECT COUNT(*) FROM contexts)
    """).fetchone())


class ChangeWatcher:
    """Publica un evento cuando otra conexión modifica la base observada."""

    def __init__(self, db_path, publish: Callable[[str, str], None], interval: float = 1.0,
                 fingerprint: Callable[[sqlite3.Connection], tuple] | None = None) -> None:
        self.db_path = Path(db_path)
        self.publish = publish
        self.interval = max(0.01, float(interval))
        self.fingerprint = fingerprint
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._generation = 0
        self._thread: Optional[threading.Thread] = None

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def start(self) -> None:
        """Inicia un único hilo daemon; repetir la llamada no crea otro."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="change-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Solicita la detención y espera brevemente al hilo."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 3))

    def _connect(self) -> sqlite3.Connection:
        # autocommit evita que una lectura deje una transacción/snapshot abierto.
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        return sqlite3.connect(uri, uri=True, isolation_level=None)

    @staticmethod
    def _data_version(conn: sqlite3.Connection) -> int:
        return int(conn.execute("PRAGMA data_version").fetchone()[0])

    def _fingerprint(self, conn: sqlite3.Connection) -> tuple | None:
        return self.fingerprint(conn) if self.fingerprint is not None else None

    def _run(self) -> None:
        conn: Optional[sqlite3.Connection] = None
        baseline: Optional[int] = None
        baseline_fingerprint: tuple | None = None
        backoff = 0.05
        while not self._stop.is_set():
            try:
                if conn is None:
                    conn = self._connect()
                    baseline = self._data_version(conn)
                    try:
                        baseline_fingerprint = self._fingerprint(conn)
                    except Exception:
                        # Without a usable schema, the first later write is relevant.
                        baseline_fingerprint = None
                    backoff = 0.05
                else:
                    version = self._data_version(conn)
                    if version != baseline:
                        baseline = version
                        try:
                            fingerprint = self._fingerprint(conn)
                        except Exception:
                            # A schema migration or partial database must not kill the watcher.
                            fingerprint = None
                            relevant = True
                        else:
                            relevant = self.fingerprint is None or fingerprint != baseline_fingerprint
                        baseline_fingerprint = fingerprint
                        if relevant:
                            with self._lock:
                                self._generation += 1
                                generation = self._generation
                            self.publish("db_changed", json.dumps({
                                "generation": generation,
                                "ts": datetime.now(timezone.utc).isoformat(),
                            }))
                self._stop.wait(self.interval)
            except Exception:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = None
                baseline = None
                baseline_fingerprint = None
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 1.0)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def set_current_watcher(watcher: Optional[ChangeWatcher]) -> None:
    """Registra el watcher del servidor para consumidores de caché."""
    global _active
    with _active_lock:
        _active = watcher


def current_generation() -> int:
    """Generación del watcher activo, o cero cuando el servidor no lo usa."""
    with _active_lock:
        watcher = _active
    return watcher.generation if watcher is not None else 0
