"""Importa historial git de proyectos registrados como runs observables."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


PROVIDER_NAME = "git"
_MAX_DIFF_BYTES = 8_000
_MAX_COMMITS = 200
# `--since` filtra por fecha de COMMIT, no por lo ya importado: un commit
# reescrito con fecha anterior al cutoff (rebase, cherry-pick, metadata
# editada) quedaria excluido para siempre si el cutoff fuera exacto. Este
# buffer resta margen al cutoff para cubrir ese desfasaje tipico (horas, no
# anios) sin volver a escanear el historial completo en cada sync - el
# historial previo a la ventana inicial (`_MAX_COMMITS`) sigue quedando
# excluido a proposito.
_SINCE_SAFETY_BUFFER = timedelta(days=2)

def _session_id(alias: str, commit_hash: str) -> str:
    """session_id con namespace de proyecto para evitar colisiones cross-project."""
    return f"git::{alias}::{commit_hash}"


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _is_git_repo(path: Path) -> bool:
    return bool(_run_git(["rev-parse", "--git-dir"], path))


def _get_commits(path: Path, max_commits: Optional[int] = None, since: Optional[str] = None) -> list[dict]:
    """Retorna commits de todas las ramas, sin merges, ordenados por fecha.

    Con `since`, trae todos los commits desde esa fecha sin techo de cantidad -
    evita perder commits cuando se acumulan mas de `max_commits` entre corridas.
    El llamador (`scan_and_import`) le resta `_SINCE_SAFETY_BUFFER` al cutoff
    real para tolerar commits backdated. Sin `since` (primera sincronizacion
    del proyecto), se limita a los `max_commits` mas recientes como ventana
    inicial.

    La fecha usada (`%ci`, fecha de COMMITTER) es intencional: `git log
    --since` filtra por fecha de committer, no de autor. Usar `%ai` (autor)
    aca desincroniza el cursor guardado del campo que --since realmente
    filtra - un commit con fecha de AUTOR a futuro (rebase, cherry-pick,
    reloj mal configurado) podia entonces "adelantar" el cursor y excluir
    silenciosamente commits reales posteriores.
    """
    sep = "\x1f"
    fmt = f"%H{sep}%s{sep}%ci{sep}%an{sep}%b"
    args = [
        "log",
        "--all",           # todas las ramas locales y remotas
        "--no-merges",     # excluir merge commits (diffs acumulados distorsionan contexto)
        f"--format={fmt}",
    ]
    if since:
        args.append(f"--since={since}")
    else:
        args.append(f"--max-count={max_commits if max_commits is not None else _MAX_COMMITS}")
    raw = _run_git(args, path)
    seen: set[str] = set()
    commits = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(sep, 4)
        if len(parts) < 4:
            continue
        h = parts[0]
        if h in seen:   # git --all puede repetir hashes entre ramas
            continue
        seen.add(h)
        commits.append({
            "hash":    h,
            "subject": parts[1],
            "date":    parts[2],
            "author":  parts[3],
            "body":    parts[4].strip() if len(parts) > 4 else "",
        })
    return commits


def _get_diff(path: Path, commit_hash: str) -> str:
    """Retorna el diff de un commit, truncado a _MAX_DIFF_BYTES."""
    diff = _run_git(
        ["diff", "--stat", "-p", f"{commit_hash}^", commit_hash, "--", "."],
        path,
    )
    if not diff:
        # Puede ser el primer commit sin padre
        diff = _run_git(["show", "--stat", "-p", commit_hash], path)
    if len(diff) > _MAX_DIFF_BYTES:
        diff = diff[:_MAX_DIFF_BYTES] + "\n...[diff truncado]"
    return diff


def _commit_already_imported(conn, alias: str, commit_hash: str) -> bool:
    sid = _session_id(alias, commit_hash)
    row = conn.execute(
        "SELECT 1 FROM runs WHERE session_id=?",
        (sid,),
    ).fetchone()
    return row is not None


def newest_local_commit_date(path: Path) -> Optional[str]:
    """Fecha del commit mas reciente importable en el repo local (chequeo de
    staleness en `doctor`, no dispara ningun import).

    `--no-merges` para que coincida con lo que `_get_commits` realmente trae -
    sin esto, un merge sin commits normales posteriores queda como el mas
    reciente para siempre y `doctor` avisa staleness que ningun sync corrige.
    `%ci` (fecha de committer) para comparar contra la misma magnitud que
    `_newest_imported_commit_date` (que ahora tambien guarda fecha de
    committer, no de autor - ver `_get_commits`).
    """
    if not _is_git_repo(path):
        return None
    raw = _run_git(["log", "--all", "--no-merges", "-1", "--format=%ci"], path)
    return raw or None


def _escape_like(value: str) -> str:
    """Escapa comodines de SQL LIKE (`%`, `_`) para que un alias como
    `team_1` no matchee accidentalmente `teamX1`."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _newest_imported_commit_date(conn, alias: str) -> Optional[str]:
    """Fecha del commit mas reciente ya importado para este alias, o None si
    nunca se sincronizo (primera corrida)."""
    row = conn.execute(
        "SELECT MAX(ts) FROM runs WHERE provider=? AND session_id LIKE ? ESCAPE '\\'",
        (PROVIDER_NAME, f"git::{_escape_like(alias)}::%"),
    ).fetchone()
    return row[0] if row and row[0] else None


def scan_and_import(config: dict, quiet: bool = False) -> list[dict]:
    """Escanea repos git de proyectos registrados e importa commits nuevos."""
    from orchestrator.db import _conn, _write_lock, init_db
    from orchestrator.index import load_index
    from orchestrator.rag import index_response

    init_db()
    conn = _conn()
    index = load_index()
    projects: dict[str, str] = index.get("projects", {})

    imported = []

    for alias, proj_path_str in projects.items():
        proj_path = Path(proj_path_str)
        if not proj_path.exists() or not _is_git_repo(proj_path):
            continue

        cursor = _newest_imported_commit_date(conn, alias)
        since = None
        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor)
                since = (cursor_dt - _SINCE_SAFETY_BUFFER).isoformat()
            except ValueError:
                since = cursor
        commits = _get_commits(proj_path, since=since)
        if not commits:
            continue

        try:
            from orchestrator.tracer import span as _tspan
        except Exception:
            from contextlib import nullcontext as _tspan  # type: ignore[assignment]

        with _tspan(f"git · {alias}", detail=f"{len(commits)} commits"):
            for commit in commits:
                h = commit["hash"]
                if _commit_already_imported(conn, alias, h):
                    continue

                diff = _get_diff(proj_path, h)
                task = commit["subject"]
                if commit["body"]:
                    task = task + "\n\n" + commit["body"]
                response = diff or "(sin diff)"

                ts_raw = commit["date"]
                try:
                    ts = datetime.fromisoformat(ts_raw).isoformat()
                except ValueError:
                    ts = datetime.now(timezone.utc).isoformat()

                preview = task[:150].replace("\n", " ")
                sid = _session_id(alias, h)

                with _write_lock:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO runs
                           (ts, project, provider, model, status,
                            task, task_preview, response,
                            routing_reason, session_id)
                           VALUES (?, ?, ?, ?, 'done', ?, ?, ?, ?, ?)""",
                        (
                            ts, alias, PROVIDER_NAME,
                            commit["author"],
                            task, preview, response,
                            f"git commit · {h[:8]}",
                            sid,
                        ),
                    )
                    if cur.rowcount:
                        run_id: Optional[int] = cur.lastrowid
                    else:
                        # Otro proceso gano la carrera e importo este commit
                        # entre nuestro chequeo y el INSERT OR IGNORE -
                        # cur.lastrowid quedaria apuntando a la ultima fila
                        # insertada por ESTA conexion, no a la real.
                        existing_row = conn.execute(
                            "SELECT id FROM runs WHERE session_id=?", (sid,)
                        ).fetchone()
                        run_id = existing_row[0] if existing_row else None
                    conn.commit()

                if run_id and diff:
                    try:
                        with _tspan(f"git · index · {alias}"):
                            index_response(run_id, alias, task, response)
                    except Exception:
                        pass

                imported.append({
                    "project": alias,
                    "hash":    h[:8],
                    "subject": commit["subject"][:60],
                    "author":  commit["author"],
                })

    return imported
