"""Migraciones one-shot: JSONL → SQLite, indexado en ChromaDB."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

import orchestrator.paths as _paths
_migration_lock = threading.Lock()


def _runs_jsonl():
    return _paths.HOME_DIR / "runs.jsonl"


def _already_applied(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM _migrations WHERE name=?", (name,)
    ).fetchone()
    return row is not None


def _mark_applied(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO _migrations (name, applied_at) VALUES (?, ?)",
        (name, datetime.now(timezone.utc).isoformat()),
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    return {
        row[1] for row in conn.execute(f"PRAGMA table_info({name})").fetchall()
    }


def recover_mcp_payload_rebuild(conn: sqlite3.Connection) -> None:
    """Promote a legacy replacement table left by an interrupted table swap."""
    source = "mcp_invocations"
    replacement = "mcp_invocations_without_payload"
    if _table_exists(conn, source) or not _table_exists(conn, replacement):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"ALTER TABLE {replacement} RENAME TO {source}")
        # The pre-atomic migration copied legacy plain output hashes. They
        # cannot be made keyed without the original payload, so remove them.
        conn.execute(f"UPDATE {source} SET output_hash='redacted'")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _remove_mcp_result_payloads(conn: sqlite3.Connection) -> None:
    """Atomically rebuild the invocation table, recovering old partial rebuilds."""
    source = "mcp_invocations"
    replacement = "mcp_invocations_without_payload"
    source_exists = _table_exists(conn, source)
    replacement_exists = _table_exists(conn, replacement)
    recovered_replacement = False

    # A previous non-atomic implementation could stop after dropping the source.
    # The replacement is already complete at that boundary, so promote it first.
    if not source_exists and replacement_exists:
        conn.execute(f"ALTER TABLE {replacement} RENAME TO {source}")
        source_exists = True
        replacement_exists = False
        recovered_replacement = True
    elif source_exists and replacement_exists:
        # The source remains authoritative until the atomic swap commits.
        conn.execute(f"DROP TABLE {replacement}")
        replacement_exists = False

    if not source_exists:
        raise sqlite3.OperationalError("mcp_invocations is missing during payload-removal migration")

    if "result_json" in _table_columns(conn, source):
        conn.execute(f"""
            CREATE TABLE {replacement} (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ts                  TEXT NOT NULL,
                request_id          TEXT NOT NULL UNIQUE,
                correlation_id      TEXT,
                server_instance_id  TEXT NOT NULL,
                client_surface      TEXT NOT NULL,
                transport           TEXT NOT NULL,
                actor_id            TEXT,
                capability_profile  TEXT NOT NULL,
                tool_name           TEXT NOT NULL,
                tool_category       TEXT NOT NULL,
                project             TEXT,
                input_hash          TEXT NOT NULL,
                output_hash         TEXT NOT NULL,
                is_error            INTEGER NOT NULL DEFAULT 0,
                request_source      TEXT NOT NULL DEFAULT 'generated',
                replay_safe         INTEGER NOT NULL DEFAULT 0,
                status              TEXT NOT NULL,
                reason_code         TEXT,
                duration_ms         INTEGER,
                error_code          TEXT,
                created_at          TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            INSERT INTO {replacement} (
                id, ts, request_id, correlation_id, server_instance_id,
                client_surface, transport, actor_id, capability_profile,
                tool_name, tool_category, project, input_hash, output_hash,
                is_error, request_source, replay_safe, status, reason_code,
                duration_ms, error_code, created_at
            )
            SELECT
                id, ts, request_id, correlation_id, server_instance_id,
                client_surface, transport, actor_id, capability_profile,
                tool_name, tool_category, project, input_hash, 'redacted',
                is_error, request_source, replay_safe, status, reason_code,
                duration_ms, error_code, created_at
            FROM {source}
        """)
        conn.execute(f"DROP TABLE {source}")
        conn.execute(f"ALTER TABLE {replacement} RENAME TO {source}")
    elif recovered_replacement:
        conn.execute(f"UPDATE {source} SET output_hash='redacted'")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mcp_invocations_project_ts
        ON mcp_invocations(project, ts DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mcp_invocations_tool_ts
        ON mcp_invocations(tool_name, ts DESC)
    """)


def _migrate_jsonl(conn: sqlite3.Connection) -> int:
    runs_jsonl = _runs_jsonl()
    if not runs_jsonl.exists():
        return 0

    count = 0
    for line in runs_jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue

        task_preview = r.get("task_preview", "")
        conn.execute(
            """INSERT OR IGNORE INTO runs
               (ts, project, provider, model, status,
                task, task_preview, response,
                duration_ms, input_tokens, output_tokens,
                routing_reason)
               VALUES (?, ?, ?, ?, 'done', ?, ?, '', ?, ?, ?, ?)""",
            (
                r.get("ts", datetime.now(timezone.utc).isoformat()),
                r.get("project", ""),
                r.get("provider", ""),
                r.get("model", ""),
                task_preview,
                task_preview,
                r.get("duration_ms"),
                r.get("input_tokens"),
                r.get("output_tokens"),
                r.get("routing_reason", ""),
            ),
        )
        count += 1

    if count:
        runs_jsonl = _runs_jsonl()
        migrated = runs_jsonl.with_suffix(".jsonl.migrated")
        runs_jsonl.rename(migrated)

    return count


def _index_existing_runs(conn: sqlite3.Connection) -> int:
    try:
        from orchestrator.similarity import get_backend
        backend = get_backend()
        rows = conn.execute(
            "SELECT id, task FROM runs WHERE status='done' AND task != '' ORDER BY id"
        ).fetchall()
        count = 0
        for row in rows:
            backend.upsert(row[0], row[1])
            count += 1
        return count
    except Exception:
        return 0


# RFC-010 (comandos gobernados desde la UI e identidad de proyectos), PR 1: solo esquema.
# `version` de contextos y pasos sube con triggers en cualquier mutación (UI, MCP, CLI o SQL a
# mano), así `expected_version` (RFC-010 §3.2, I6) no depende de que cada UPDATE la recuerde:
# - si el UPDATE no toca `version`, el trigger AFTER la sube en uno (WHEN NEW = OLD, así el
#   UPDATE interno no se encadena aunque `recursive_triggers` esté activo);
# - si la toca, solo se acepta exactamente la siguiente (OLD + 1): ni retrocesos ni saltos.
# `INSERT OR REPLACE` sobre estas tablas reiniciaría la versión; el código no lo usa y un test
# estático lo impide (tests/test_rfc010_schema.py).
RFC010_VERSION_TRIGGERS = """
    CREATE TRIGGER IF NOT EXISTS trg_contexts_version_guard BEFORE UPDATE OF version ON contexts
    WHEN NEW.version <> OLD.version AND NEW.version <> OLD.version + 1
    BEGIN
        SELECT RAISE(ABORT, 'version de contexts solo avanza de a uno');
    END;
    CREATE TRIGGER IF NOT EXISTS trg_contexts_version AFTER UPDATE ON contexts
    WHEN NEW.version = OLD.version
    BEGIN
        UPDATE contexts SET version = OLD.version + 1 WHERE id = NEW.id;
    END;
    CREATE TRIGGER IF NOT EXISTS trg_steps_version_guard BEFORE UPDATE OF version ON steps
    WHEN NEW.version <> OLD.version AND NEW.version <> OLD.version + 1
    BEGIN
        SELECT RAISE(ABORT, 'version de steps solo avanza de a uno');
    END;
    CREATE TRIGGER IF NOT EXISTS trg_steps_version AFTER UPDATE ON steps
    WHEN NEW.version = OLD.version
    BEGIN
        UPDATE steps SET version = OLD.version + 1 WHERE id = NEW.id;
    END;
"""

RFC010_TABLES = """
    -- Proyectos canónicos (§3.4.1): el alias y, para repos anidados, su proyecto padre.
    CREATE TABLE IF NOT EXISTS projects (
        alias           TEXT PRIMARY KEY,
        parent_alias    TEXT REFERENCES projects(alias),
        created_at      TEXT NOT NULL,
        CHECK (parent_alias IS NULL OR parent_alias <> alias)
    );

    -- Qué ruta pertenece a qué proyecto (§3.4.1). Una ruta es de un solo alias; un alias puede
    -- tener varias rutas (su carpeta registrada, sus worktrees, sus clones).
    CREATE TABLE IF NOT EXISTS project_identities (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        alias           TEXT NOT NULL REFERENCES projects(alias),
        kind            TEXT NOT NULL CHECK (kind IN ('registered', 'worktree', 'clone', 'folder')),
        status          TEXT NOT NULL CHECK (status IN ('confirmed', 'proposed')),
        path            TEXT NOT NULL UNIQUE,
        git_common_dir  TEXT,
        remote          TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_project_identities_alias ON project_identities(alias);
    CREATE INDEX IF NOT EXISTS idx_project_identities_common ON project_identities(git_common_dir);

    -- Registro lógico de cada comando de la UI (§3.2): uno por request_id, sin texto libre.
    CREATE TABLE IF NOT EXISTS ui_commands (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id      TEXT NOT NULL UNIQUE,
        command         TEXT NOT NULL,
        category        TEXT NOT NULL,
        project         TEXT,
        capability_profile TEXT NOT NULL,
        input_hash      TEXT NOT NULL,
        status          TEXT NOT NULL CHECK (status IN (
                            'not_admitted', 'queued', 'running', 'ok', 'denied',
                            'conflict', 'error', 'interrupted')),
        reason_code     TEXT,
        receipt_hash    TEXT,
        result_version  INTEGER,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ui_commands_project ON ui_commands(project, created_at);

    -- Cada intento HTTP de un comando (§3.2, I3): solo se agrega, nunca se cambia ni se borra.
    CREATE TABLE IF NOT EXISTS ui_command_attempts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id      TEXT NOT NULL REFERENCES ui_commands(request_id),
        ts              TEXT NOT NULL,
        status          TEXT NOT NULL,
        reason_code     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ui_command_attempts_request ON ui_command_attempts(request_id, ts);
    CREATE TRIGGER IF NOT EXISTS trg_ui_command_attempts_no_update BEFORE UPDATE ON ui_command_attempts
    BEGIN SELECT RAISE(ABORT, 'ui_command_attempts es solo de agregar'); END;
    CREATE TRIGGER IF NOT EXISTS trg_ui_command_attempts_no_delete BEFORE DELETE ON ui_command_attempts
    BEGIN SELECT RAISE(ABORT, 'ui_command_attempts es solo de agregar'); END;

    -- Trabajos (§3.3): el comando que los creó, los recursos que toman, etapa y estado; nunca
    -- 'running' tras un reinicio (I7, lo reconcilia el PR 4). El trabajo de un comando se
    -- encuentra por request_id (no hay copia del id en ui_commands).
    CREATE TABLE IF NOT EXISTS jobs (
        id              TEXT PRIMARY KEY,
        request_id      TEXT NOT NULL UNIQUE REFERENCES ui_commands(request_id),
        kind            TEXT NOT NULL,
        resources       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(resources) AND json_type(resources) = 'array'),
        status          TEXT NOT NULL CHECK (status IN (
                            'queued', 'running', 'done', 'failed', 'conflict', 'interrupted')),
        stage           TEXT,
        receipt_hash    TEXT,
        created_at      TEXT NOT NULL,
        started_at      TEXT,
        finished_at     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

    -- Intenciones durables de operaciones que no caben en una transacción SQLite (§3.4.3):
    -- reescribir el índice YAML o migrar ChromaDB después de una fusión. El payload es JSON
    -- mínimo por tipo (alias y conteos), nunca argumentos de UI, resultados ni contenido RAG.
    CREATE TABLE IF NOT EXISTS durable_intents (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id      TEXT NOT NULL REFERENCES ui_commands(request_id),
        kind            TEXT NOT NULL CHECK (kind IN ('index_yaml', 'rag_migration')),
        payload         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload) AND json_type(payload) = 'object'),
        status          TEXT NOT NULL CHECK (status IN ('pending', 'done')),
        created_at      TEXT NOT NULL,
        done_at         TEXT,
        UNIQUE (request_id, kind)
    );
    CREATE INDEX IF NOT EXISTS idx_durable_intents_pending ON durable_intents(status, kind);

    -- Reservas de presupuesto previas a llamar a un proveedor (§3.5, I15).
    CREATE TABLE IF NOT EXISTS budget_reservations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id      TEXT NOT NULL UNIQUE REFERENCES ui_commands(request_id),
        project         TEXT NOT NULL,
        period          TEXT NOT NULL,
        estimated_usd   REAL NOT NULL CHECK (estimated_usd >= 0),
        actual_usd      REAL CHECK (actual_usd IS NULL OR actual_usd >= 0),
        status          TEXT NOT NULL CHECK (status IN ('reserved', 'settled', 'released')),
        created_at      TEXT NOT NULL,
        settled_at      TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_budget_reservations_period ON budget_reservations(project, period, status);
"""


def _run_script(conn: sqlite3.Connection, script: str) -> None:
    """Ejecuta un script SQL sentencia por sentencia, sin el COMMIT implícito de executescript
    (así todo queda en la transacción de la migración). Si queda SQL sin terminar, falla."""
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            conn.execute(buffer)
            buffer = ""
    leftover = "\n".join(line for line in buffer.splitlines() if not line.strip().startswith("--"))
    if leftover.strip():
        raise ValueError(f"SQL incompleto al final del script: {leftover.strip()[:80]}")


def apply_rfc010_schema(conn: sqlite3.Connection) -> None:
    """Columnas `version`, triggers y tablas de RFC-010 (idempotente)."""
    for table in ("contexts", "steps"):
        if "version" not in _table_columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
    _run_script(conn, RFC010_VERSION_TRIGGERS)
    _run_script(conn, RFC010_TABLES)


def apply_rfc010_jobs_run_id(conn: sqlite3.Connection) -> None:
    """RFC-010 PR 4: el run que creó un trabajo `run_task`, para marcarlo interrumpido al
    reconciliar (§3.3). Idempotente."""
    if "run_id" not in _table_columns(conn, "jobs"):
        conn.execute("ALTER TABLE jobs ADD COLUMN run_id INTEGER REFERENCES runs(id)")


def _with_lock_retry(apply, attempts: int = 3, wait: float = 1.0) -> None:
    """Reintenta una migración si otro proceso (un servidor MCP, la CLI) retiene la escritura
    más allá de `busy_timeout`; si no se libera, falla con un mensaje que dice qué pasa."""
    import time

    for attempt in range(1, attempts + 1):
        try:
            apply()
            return
        except sqlite3.OperationalError as error:
            if "locked" not in str(error).lower() or attempt == attempts:
                if "locked" in str(error).lower():
                    raise sqlite3.OperationalError(
                        "La base está bloqueada por otro proceso (un servidor MCP o la CLI con una "
                        "escritura abierta); cerralo y volvé a intentar.") from error
                raise
            time.sleep(wait * attempt)


def run_migrations() -> None:
    with _migration_lock:
        from orchestrator.db import _conn, _write_lock
        conn = _conn()
        with _write_lock:
            if not _already_applied(conn, "jsonl_to_sqlite"):
                n = _migrate_jsonl(conn)
                _mark_applied(conn, "jsonl_to_sqlite")
                conn.commit()
                if n:
                    import logging
                    logging.getLogger(__name__).info(
                        "Migración JSONL→SQLite: %d runs importados.", n
                    )

        with _write_lock:
            if not _already_applied(conn, "add_session_id_column"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN session_id TEXT")
                except Exception:
                    pass
                _mark_applied(conn, "add_session_id_column")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_session_id_v2"):
                cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()]
                if "session_id" not in cols:
                    try:
                        conn.execute("ALTER TABLE runs ADD COLUMN session_id TEXT")
                    except Exception:
                        pass
                try:
                    conn.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_session_id"
                        " ON runs(session_id) WHERE session_id IS NOT NULL"
                    )
                except Exception:
                    pass
                _mark_applied(conn, "add_session_id_v2")
                conn.commit()

        if not _already_applied(conn, "index_chroma"):
            n = _index_existing_runs(conn)
            with _write_lock:
                _mark_applied(conn, "index_chroma")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_contexts_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS contexts (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts          TEXT    NOT NULL,
                        updated_at  TEXT    NOT NULL,
                        project     TEXT    NOT NULL,
                        title       TEXT    NOT NULL DEFAULT '',
                        description TEXT    NOT NULL DEFAULT '',
                        status      TEXT    NOT NULL DEFAULT 'active',
                        metadata    TEXT    NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_contexts_project ON contexts(project);
                    CREATE INDEX IF NOT EXISTS idx_contexts_status  ON contexts(status);
                """)
                _mark_applied(conn, "create_contexts_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_steps_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS steps (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        context_id   INTEGER NOT NULL REFERENCES contexts(id),
                        order_idx    INTEGER NOT NULL,
                        title        TEXT    NOT NULL DEFAULT '',
                        description  TEXT    NOT NULL DEFAULT '',
                        status       TEXT    NOT NULL DEFAULT 'pending',
                        provider     TEXT    NOT NULL DEFAULT '',
                        started_at   TEXT,
                        completed_at TEXT,
                        notes        TEXT    NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_steps_context_order  ON steps(context_id, order_idx);
                    CREATE INDEX IF NOT EXISTS idx_steps_context_status ON steps(context_id, status);
                """)
                _mark_applied(conn, "create_steps_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_tool_calls_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts          TEXT    NOT NULL,
                        step_id     INTEGER NOT NULL REFERENCES steps(id),
                        context_id  INTEGER NOT NULL REFERENCES contexts(id),
                        tool_name   TEXT    NOT NULL DEFAULT '',
                        input       TEXT    NOT NULL DEFAULT '{}',
                        output      TEXT    NOT NULL DEFAULT '',
                        status      TEXT    NOT NULL DEFAULT 'ok',
                        duration_ms INTEGER
                    );
                    CREATE INDEX IF NOT EXISTS idx_tool_calls_step    ON tool_calls(step_id, ts);
                    CREATE INDEX IF NOT EXISTS idx_tool_calls_context ON tool_calls(context_id, ts);
                """)
                _mark_applied(conn, "create_tool_calls_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_alignments_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS alignments (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts         TEXT    NOT NULL,
                        step_id    INTEGER NOT NULL REFERENCES steps(id),
                        context_id INTEGER NOT NULL REFERENCES contexts(id),
                        agent      TEXT    NOT NULL DEFAULT '',
                        confirmed  INTEGER NOT NULL DEFAULT 1,
                        checkpoint TEXT    NOT NULL DEFAULT '',
                        message    TEXT    NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_alignments_step    ON alignments(step_id);
                    CREATE INDEX IF NOT EXISTS idx_alignments_context ON alignments(context_id, ts);
                """)
                _mark_applied(conn, "create_alignments_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_step_id_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN step_id INTEGER REFERENCES steps(id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_step ON runs(step_id)")
                except Exception:
                    pass
                _mark_applied(conn, "add_step_id_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_chunks_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS chunks (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        project     TEXT    NOT NULL,
                        source_path TEXT    NOT NULL,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        ts          TEXT    NOT NULL,
                        collection  TEXT    NOT NULL DEFAULT 'docs',
                        UNIQUE(project, source_path)
                    );
                    CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);
                """)
                _mark_applied(conn, "create_chunks_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_parent_step_id_to_contexts"):
                try:
                    conn.execute("ALTER TABLE contexts ADD COLUMN parent_step_id INTEGER REFERENCES steps(id)")
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_contexts_parent_step ON contexts(parent_step_id)"
                        " WHERE parent_step_id IS NOT NULL"
                    )
                except Exception:
                    pass
                _mark_applied(conn, "add_parent_step_id_to_contexts")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_context_hits_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS context_hits (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                        collection TEXT    NOT NULL DEFAULT 'docs',
                        source     TEXT    NOT NULL DEFAULT '',
                        chunk_idx  INTEGER,
                        score      REAL,
                        ts         TEXT    NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_context_hits_run ON context_hits(run_id);
                """)
                _mark_applied(conn, "create_context_hits_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_egress_decisions_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS egress_decisions (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts          TEXT NOT NULL,
                        project     TEXT NOT NULL,
                        provider    TEXT NOT NULL,
                        phase       TEXT NOT NULL,
                        decision    TEXT NOT NULL,
                        reason_code TEXT NOT NULL,
                        sensitivity TEXT,
                        clearance   TEXT,
                        run_id      INTEGER REFERENCES runs(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_egress_project_ts ON egress_decisions(project, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_egress_decision ON egress_decisions(decision, phase);
                """)
                _mark_applied(conn, "create_egress_decisions_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_rating_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN rating TEXT")
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_runs_rating ON runs(rating)"
                        " WHERE rating IS NOT NULL"
                    )
                except Exception:
                    pass
                _mark_applied(conn, "add_rating_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_exchange_rates_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS exchange_rates (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        date       TEXT    NOT NULL,
                        currency   TEXT    NOT NULL DEFAULT 'USD_CLP',
                        rate       REAL    NOT NULL,
                        source     TEXT    NOT NULL DEFAULT 'bcentral',
                        fetched_at TEXT    NOT NULL,
                        UNIQUE(date, currency)
                    );
                    CREATE INDEX IF NOT EXISTS idx_rates_date ON exchange_rates(date DESC);
                """)
                _mark_applied(conn, "create_exchange_rates_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_router_cost_usd_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN router_cost_usd REAL")
                except Exception:
                    pass
                _mark_applied(conn, "add_router_cost_usd_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_cost_pricing_key_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN cost_pricing_key TEXT")
                except Exception:
                    pass
                _mark_applied(conn, "add_cost_pricing_key_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_file_hash_to_chunks"):
                try:
                    conn.execute("ALTER TABLE chunks ADD COLUMN file_hash TEXT")
                except Exception:
                    pass
                _mark_applied(conn, "add_file_hash_to_chunks")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_agent_preset_to_steps"):
                try:
                    conn.execute("ALTER TABLE steps ADD COLUMN agent_preset TEXT")
                except Exception:
                    pass
                _mark_applied(conn, "add_agent_preset_to_steps")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_routing_source_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN routing_source TEXT")
                except Exception:
                    pass
                _mark_applied(conn, "add_routing_source_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_evaluation_fields_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN task_class TEXT")
                except Exception:
                    pass
                try:
                    conn.execute(
                        "ALTER TABLE runs ADD COLUMN verification_result TEXT"
                    )
                except Exception:
                    pass
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_runs_evaluation
                    ON runs(task_class, verification_result)
                    WHERE task_class IS NOT NULL
                """)
                _mark_applied(conn, "add_evaluation_fields_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_mcp_idempotency_results"):
                columns = {
                    row[1] for row in conn.execute(
                        "PRAGMA table_info(mcp_invocations)"
                    ).fetchall()
                }
                for name, definition in (
                    ("is_error", "INTEGER NOT NULL DEFAULT 0"),
                    ("request_source", "TEXT NOT NULL DEFAULT 'generated'"),
                    ("replay_safe", "INTEGER NOT NULL DEFAULT 0"),
                ):
                    if name not in columns:
                        conn.execute(
                            f"ALTER TABLE mcp_invocations ADD COLUMN {name} {definition}"
                        )
                _mark_applied(conn, "add_mcp_idempotency_results")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "remove_mcp_result_payloads"):
                conn.execute("PRAGMA secure_delete=ON")
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    _remove_mcp_result_payloads(conn)
                    _mark_applied(conn, "remove_mcp_result_payloads")
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        with _write_lock:
            if not _already_applied(conn, "add_runs_instant_indexes"):
                # runs.ts mixes offsets (git keeps the committer's), so queries
                # order and filter by julianday(ts). These expression indexes
                # let SQLite serve those queries without a full sort. julianday()
                # rounds to milliseconds, so ts (same offset within a run source)
                # breaks ties at microsecond precision before falling back to id.
                conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_instant ON runs(julianday(ts), ts)")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_runs_project_instant ON runs(project, julianday(ts), ts)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_runs_status_instant ON runs(status, julianday(ts), ts)"
                )
                _mark_applied(conn, "add_runs_instant_indexes")
                conn.commit()

            if not _already_applied(conn, "redact_legacy_mcp_output_hashes"):
                # Existing values predate keyed commitments and cannot safely be
                # upgraded without the removed payload. Clear them once before
                # new invocations can write HMAC commitments.
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("UPDATE mcp_invocations SET output_hash='redacted'")
                    _mark_applied(conn, "redact_legacy_mcp_output_hashes")
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        with _write_lock:
            if not _already_applied(conn, "rfc010_command_schema"):
                def apply() -> None:
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        apply_rfc010_schema(conn)
                        _mark_applied(conn, "rfc010_command_schema")
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise

                _with_lock_retry(apply)

        with _write_lock:
            if not _already_applied(conn, "rfc010_jobs_run_id"):
                def apply_run_id() -> None:
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        apply_rfc010_jobs_run_id(conn)
                        _mark_applied(conn, "rfc010_jobs_run_id")
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise

                _with_lock_retry(apply_run_id)
