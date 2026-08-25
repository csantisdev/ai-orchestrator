import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator import git_scanner
from orchestrator.db import _conn


def _run(args, cwd, env=None):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                    capture_output=True, env=env)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init"], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test"], path)


def _commit(path: Path, filename: str, message: str, when: datetime) -> None:
    (path / filename).write_text(message, encoding="utf-8")
    _run(["add", filename], path)
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    import os
    env = dict(os.environ, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    _run(["commit", "-m", message], path, env=env)


@pytest.fixture
def synthetic_repo(tmp_path, monkeypatch, request):
    repo = tmp_path / "repo"
    _init_repo(repo)

    alias = f"synthetic-git-project-{request.node.name}"
    monkeypatch.setattr(
        "orchestrator.index.load_index",
        lambda: {"projects": {alias: str(repo)}},
    )
    # Evita que la corrida real de RAG toque red/embeddings en el test.
    monkeypatch.setattr("orchestrator.rag.index_response", lambda *a, **kw: None)

    return alias, repo


def _imported_hashes(alias: str) -> set[str]:
    conn = _conn()
    rows = conn.execute(
        "SELECT session_id FROM runs WHERE session_id LIKE ?",
        (f"git::{alias}::%",),
    ).fetchall()
    return {r["session_id"].split("::", 2)[2] for r in rows}


def test_incremental_sync_does_not_lose_commits_beyond_cap(synthetic_repo, monkeypatch):
    """Un sync incremental (no la primera corrida) no debe perder commits
    aunque se acumulen mas que _MAX_COMMITS entre corridas, y los commits
    anteriores a la ventana inicial siguen quedando excluidos a proposito
    (separados por dias, fuera de _SINCE_SAFETY_BUFFER)."""
    alias, repo = synthetic_repo
    monkeypatch.setattr(git_scanner, "_MAX_COMMITS", 3)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_batch = ["c1", "c2", "c3", "c4", "c5"]
    for i, name in enumerate(first_batch):
        _commit(repo, f"{name}.txt", name, base + timedelta(days=i))

    imported = git_scanner.scan_and_import({}, quiet=True)
    assert len(imported) == 3  # ventana inicial limitada a _MAX_COMMITS

    second_batch = ["c6", "c7", "c8", "c9"]  # 4 commits > _MAX_COMMITS(3)
    for i, name in enumerate(second_batch):
        _commit(repo, f"{name}.txt", name, base + timedelta(days=10 + i))

    imported_2 = git_scanner.scan_and_import({}, quiet=True)
    assert len(imported_2) == 4  # los 4 nuevos entran, sin cap; c1/c2 siguen fuera

    hashes = _imported_hashes(alias)
    log = subprocess.run(
        ["git", "log", "--all", "--format=%H"], cwd=str(repo),
        capture_output=True, text=True,
    ).stdout.split()
    hash_by_subject = dict(zip(["c9", "c8", "c7", "c6", "c5", "c4", "c3", "c2", "c1"], log))

    for name in ["c5", "c6", "c7", "c8", "c9"]:
        assert hash_by_subject[name] in hashes, f"{name} deberia estar importado"


def test_first_sync_uses_max_commits_window(synthetic_repo, monkeypatch):
    alias, repo = synthetic_repo
    monkeypatch.setattr(git_scanner, "_MAX_COMMITS", 2)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, name in enumerate(["c1", "c2", "c3"]):
        _commit(repo, f"{name}.txt", name, base + timedelta(minutes=i))

    imported = git_scanner.scan_and_import({}, quiet=True)
    assert len(imported) == 2


def test_backdated_commit_not_lost_on_incremental_sync(synthetic_repo):
    """Regresion: un commit nuevo con fecha ANTERIOR al ultimo importado
    (rebase, cherry-pick, metadata reescrita) no debe perderse. Con --since
    como cursor de fecha, git lo excluiria para siempre; el sync incremental
    ahora trae el historial completo y dedupea por hash real."""
    alias, repo = synthetic_repo
    base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    _commit(repo, "c1.txt", "c1", base)
    _commit(repo, "c2.txt", "c2", base + timedelta(hours=1))

    imported = git_scanner.scan_and_import({}, quiet=True)
    assert len(imported) == 2

    # Commit nuevo pero con fecha ANTERIOR al cutoff (max ts importado = c2).
    _commit(repo, "c3-backdated.txt", "c3-backdated", base - timedelta(hours=2))

    imported_2 = git_scanner.scan_and_import({}, quiet=True)
    assert [c["subject"] for c in imported_2] == ["c3-backdated"]


def test_alias_with_sql_wildcard_does_not_leak_cursor(monkeypatch, tmp_path, request):
    """Regresion: un alias con '_' (comodin SQL LIKE) no debe heredar el
    cursor de otro alias que matchee el wildcard sin escapar (ej: 'team_1'
    matcheando 'teamX1' via `LIKE 'git::team_1::%'`)."""
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    _init_repo(repo_a)
    _init_repo(repo_b)

    suffix = request.node.name
    alias_a = f"team_1_{suffix}"
    alias_b = f"teamX1_{suffix}"
    monkeypatch.setattr(
        "orchestrator.index.load_index",
        lambda: {"projects": {alias_a: str(repo_a), alias_b: str(repo_b)}},
    )
    monkeypatch.setattr("orchestrator.rag.index_response", lambda *a, **kw: None)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _commit(repo_a, "a1.txt", "a1", base)
    _commit(repo_b, "b1.txt", "b1", base + timedelta(days=5))

    git_scanner.scan_and_import({}, quiet=True)

    cursor_a = git_scanner._newest_imported_commit_date(_conn(), alias_a)
    assert cursor_a is not None and cursor_a.startswith("2026-01-01")


def test_newest_local_commit_date_ignores_merges(synthetic_repo):
    """Regresion: newest_local_commit_date() debe coincidir con lo que
    _get_commits() realmente trae (sin merges) - si no, doctor queda en
    falso-staleness permanente tras un merge sin commits normales despues."""
    alias, repo = synthetic_repo
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    _commit(repo, "c1.txt", "c1", base)
    main_branch = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout.strip()
    _run(["checkout", "-b", "feature"], repo)
    _commit(repo, "c2.txt", "c2", base + timedelta(hours=1))
    _run(["checkout", main_branch], repo)
    merge_env = dict(
        os.environ,
        GIT_AUTHOR_DATE="2026-01-01T03:00:00+00:00",
        GIT_COMMITTER_DATE="2026-01-01T03:00:00+00:00",
    )
    subprocess.run(
        # --no-ff fuerza un merge commit real - sin esto, como "main" no
        # avanzo desde el punto de rama, git hace fast-forward y nunca se
        # crea un merge, dejando el test en falso-verde (nunca ejercita
        # --no-merges porque HEAD termina con un solo padre).
        ["git", "merge", "feature", "--no-ff", "--no-edit"],
        cwd=str(repo), check=True, capture_output=True, env=merge_env,
    )
    parents = subprocess.run(
        ["git", "log", "-1", "--format=%P"], cwd=str(repo),
        capture_output=True, text=True,
    ).stdout.split()
    assert len(parents) == 2, "el merge deberia tener 2 padres (no fast-forward)"

    normal_commit_date = git_scanner._get_commits(repo)[0]["date"]
    assert git_scanner.newest_local_commit_date(repo) == normal_commit_date


def test_insert_or_ignore_race_indexes_correct_run_id(synthetic_repo, monkeypatch):
    """Regresion end-to-end (no solo a nivel SQL, ver test_db.py para eso):
    dos threads corriendo scan_and_import concurrentemente para el mismo
    alias no deben terminar indexando un commit con el run_id de OTRO commit
    ya insertado por la misma conexion. Fuerza la interseccion exacta con
    threading.Event en vez de depender de timing."""
    alias, repo = synthetic_repo
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Orden de creacion normal (sin backdating): "older" es el padre (mas
    # viejo en fecha Y en el grafo), "newer" es HEAD. git log lista HEAD
    # primero, asi que "newer" se procesa primero (insert normal, deja a
    # esta conexion con un lastrowid real y ajeno) y "older" segundo - ahi
    # se fuerza la carrera.
    _commit(repo, "older.txt", "commit-older", base)
    _commit(repo, "newer.txt", "commit-newer", base + timedelta(minutes=1))

    captured_run_ids: list[int] = []
    monkeypatch.setattr(
        "orchestrator.rag.index_response",
        lambda run_id, *a, **kw: captured_run_ids.append(run_id),
    )

    entered = threading.Event()
    release = threading.Event()
    state = {"n": 0}
    real_get_diff = git_scanner._get_diff

    def blocking_get_diff(path, commit_hash):
        state["n"] += 1
        if state["n"] == 2:  # segundo commit de ESTE thread (commit-older)
            entered.set()
            assert release.wait(timeout=5), "release nunca se seteo"
        return real_get_diff(path, commit_hash)

    monkeypatch.setattr(git_scanner, "_get_diff", blocking_get_diff)

    t1 = threading.Thread(target=git_scanner.scan_and_import, args=({},), kwargs={"quiet": True})
    t1.start()
    assert entered.wait(timeout=5), "t1 nunca llego a bloquearse en commit-older"

    # t2 corre completo: no ve commit-newer (ya importado por t1), importa
    # commit-older por su cuenta antes de que t1 reanude.
    t2 = threading.Thread(target=git_scanner.scan_and_import, args=({},), kwargs={"quiet": True})
    t2.start()
    t2.join(timeout=10)

    release.set()
    t1.join(timeout=10)  # t1 reanuda: su INSERT OR IGNORE de commit-older ya no inserta nada

    log = subprocess.run(
        ["git", "log", "--all", "--format=%H\x1f%s"], cwd=str(repo),
        capture_output=True, text=True,
    ).stdout.strip().split("\n")
    hash_by_subject = {}
    for line in log:
        h, s = line.split("\x1f", 1)
        hash_by_subject[s] = h

    conn = _conn()
    row_newer = conn.execute(
        "SELECT id FROM runs WHERE session_id=?",
        (f"git::{alias}::{hash_by_subject['commit-newer']}",),
    ).fetchone()
    row_older = conn.execute(
        "SELECT id FROM runs WHERE session_id=?",
        (f"git::{alias}::{hash_by_subject['commit-older']}",),
    ).fetchone()
    assert row_newer is not None and row_older is not None
    assert row_newer["id"] != row_older["id"]

    # Sin el fix, t1 habria indexado commit-older con SU propio lastrowid
    # (el de commit-newer, ajeno) en vez del id real de commit-older.
    assert row_older["id"] in captured_run_ids
    assert captured_run_ids.count(row_newer["id"]) == 1
