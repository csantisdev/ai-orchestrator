"""Importa historial git de proyectos registrados como runs observables."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROVIDER_NAME = "git"
_MAX_DIFF_BYTES = 8_000
_MAX_COMMITS = 200

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


def _get_commits(path: Path, max_commits: int = _MAX_COMMITS) -> list[dict]:
    """Retorna commits de todas las ramas, sin merges, ordenados por fecha."""
    sep = "\x1f"
    fmt = f"%H{sep}%s{sep}%ai{sep}%an{sep}%b"
    raw = _run_git(
        [
            "log",
            "--all",           # todas las ramas locales y remotas
            "--no-merges",     # excluir merge commits (diffs acumulados distorsionan contexto)
            f"--max-count={max_commits}",
            f"--format={fmt}",
        ],
        path,
    )
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

        commits = _get_commits(proj_path)
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
                    conn.commit()
                run_id: Optional[int] = cur.lastrowid if cur.lastrowid else None

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
