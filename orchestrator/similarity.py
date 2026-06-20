"""Búsqueda de runs similares: ChromaDB con fallback a SQLite FTS5."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SimilarityBackend(Protocol):
    def upsert(self, run_id: int, text: str) -> None: ...
    def query(self, text: str, n_results: int = 3) -> list[dict]: ...


class ChromaBackend:
    def __init__(self, persist_dir: Path) -> None:
        import chromadb  # type: ignore[import]
        client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        self._col = client.get_or_create_collection("runs")

    def upsert(self, run_id: int, text: str) -> None:
        if not text.strip():
            return
        self._col.upsert(ids=[str(run_id)], documents=[text])

    def query(self, text: str, n_results: int = 3) -> list[dict]:
        if not text.strip():
            return []
        try:
            res = self._col.query(query_texts=[text], n_results=n_results)
            ids = res.get("ids", [[]])[0]
            distances = res.get("distances", [[]])[0]
            return [{"run_id": int(i), "score": 1.0 - d} for i, d in zip(ids, distances)]
        except Exception:
            return []


class FTS5Backend:
    def upsert(self, run_id: int, text: str) -> None:
        pass  # Mantenido por triggers en db.py

    def query(self, text: str, n_results: int = 3) -> list[dict]:
        from orchestrator.db import fts_search
        rows = fts_search(text, limit=n_results)
        return [{"run_id": r["id"], "score": None} for r in rows]


_backend_cache: SimilarityBackend | None = None


def get_backend(home_dir: Path | None = None) -> SimilarityBackend:
    global _backend_cache
    if _backend_cache is not None:
        return _backend_cache
    if home_dir is None:
        from orchestrator.paths import HOME_DIR
        home_dir = HOME_DIR
    try:
        _backend_cache = ChromaBackend(home_dir / "chroma")
    except (ImportError, Exception):
        _backend_cache = FTS5Backend()
    return _backend_cache
