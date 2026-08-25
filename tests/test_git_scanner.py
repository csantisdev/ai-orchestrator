import os
import subprocess
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
        ["git", "merge", "feature", "--no-edit"],
        cwd=str(repo), check=True, capture_output=True, env=merge_env,
    )

    normal_commit_date = git_scanner._get_commits(repo)[0]["date"]
    assert git_scanner.newest_local_commit_date(repo) == normal_commit_date
