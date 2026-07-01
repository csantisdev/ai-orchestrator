"""RAG: indexación y recuperación de contexto documental por proyecto."""

from __future__ import annotations

import re
from pathlib import Path

_CHUNK_SIZE = 1500
_CHUNK_OVERLAP = 200
# Umbral de distancia L2 para filtrar resultados RAG. Con vectores normalizados
# (all-MiniLM-L6-v2), L2=1.4 equivale a cosine_sim≈0.02 (extremadamente permisivo).
# L2=0.9 equivale a cosine_sim≈0.60, filtrando contexto poco relevante.
_DISTANCE_THRESHOLD = 0.9
_SCAN_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".toml", ".rst", ".json"}
_CODE_EXTENSIONS = {
    ".py", ".php", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".cs", ".go", ".sql", ".rb", ".rs",
}
_SKIP_DIRS = {
    ".venv", "venv", "__pycache__", ".git", "node_modules",
    ".eggs", "build", "dist",
    "vendor",           # PHP / Ruby / Go vendor dirs
    ".claude", ".codex",
    ".aws", ".ssh", ".kube", ".gcloud",  # credential dirs
    # stack-specific build/cache dirs
    "storage/logs", "bootstrap/cache", "public/build",
    ".next", ".nuxt", "coverage", "target",
}
_SKIP_FILENAMES = {
    # Generic config with secrets
    "config.yaml", "config.yml",
    ".env", ".env.local", ".env.production", ".env.staging",
    "secrets.yaml", "secrets.yml",
    "credentials.yaml", "credentials.json",
    # SSH keys
    "id_rsa", "id_ed25519", "id_ecdsa",
    # Laravel / Composer
    "auth.json",
    # Node / npm / Yarn
    ".npmrc", ".yarnrc", ".yarnrc.yml",
    # Google / Firebase
    "service_account.json", "google-services.json",
    "google-credentials.json", "firebase-credentials.json",
    "GoogleService-Info.plist",
    # Infrastructure
    "terraform.tfvars", "kubeconfig", ".kubeconfig",
    # Auth helpers
    ".netrc", ".htpasswd", ".sentryclirc",
}
_SKIP_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".cer", ".crt",
    ".tfstate",   # Terraform state (contains real infra secrets)
    ".tfvars",    # Terraform vars
    ".plist",     # iOS config (GoogleService-Info.plist)
}

# Patterns that strongly suggest a file contains live credentials.
_SECRET_PATTERN = re.compile(
    r"(?i)("
    r"sk-ant-[A-Za-z0-9\-_]{20,}"              # Anthropic API key
    r"|sk-[A-Za-z0-9_\-]{30,}"                  # OpenAI API key (sk-proj-… / sk-svcacct-…)
    r"|APP_USR-[A-Za-z0-9\-]{10,}"              # MercadoPago
    r"|token\s*=\s*[a-f0-9]{32,}"              # token=<hex> in URLs (generic)
    r"|-----BEGIN\s+(?:RSA |EC |OPENSSH |PGP )PRIVATE KEY"  # private key blocks
    r")"
)

_MAX_FILE_BYTES = 150_000
_MAX_CODE_FILES = 100

_STACK_SKIP_SUGGESTIONS: dict[str, list[str]] = {
    "laravel": ["vendor", "storage", "bootstrap", "public/build"],
    "php":     ["vendor", "storage", "bootstrap"],
    "node":    ["node_modules", "dist", ".next", ".nuxt", "build", ".turbo"],
    "react":   ["node_modules", "dist", "build", ".next"],
    "python":  [".venv", "venv", "__pycache__", "dist", "build"],
    "go":      ["vendor"],
    "ruby":    ["vendor", "tmp", "log"],
}


def _is_suggested_skip(dirname: str, stack: str) -> bool:
    stack_lower = stack.lower()
    for key, dirs in _STACK_SKIP_SUGGESTIONS.items():
        if key in stack_lower and dirname in dirs:
            return True
    return False


_chroma_client = None
_chroma_lock = None


def _get_client():
    global _chroma_client, _chroma_lock
    if _chroma_lock is None:
        import threading
        _chroma_lock = threading.Lock()
    if _chroma_client is None:
        with _chroma_lock:
            if _chroma_client is None:
                import chromadb
                from orchestrator.paths import HOME_DIR
                _chroma_client = chromadb.PersistentClient(
                    path=str(HOME_DIR / "chroma"),
                    settings=chromadb.Settings(anonymized_telemetry=False),
                )
    return _chroma_client


def _docs_collection():
    return _get_client().get_or_create_collection("docs")


def _responses_collection():
    return _get_client().get_or_create_collection("responses")


def chunk_text(
    text: str,
    source: str,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> list[dict]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between zero and chunk_size - 1")

    chunks = []
    idx = 0
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            nl = text.rfind("\n", start + chunk_size // 2, end)
            if nl != -1:
                end = nl + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"text": chunk, "source": source, "chunk_idx": idx})
            idx += 1
        start = end - overlap
        if start >= len(text):
            break
    return chunks


def _is_sensitive_file(f: Path) -> bool:
    if f.name.lower() in _SKIP_FILENAMES:
        return True
    if f.suffix.lower() in _SKIP_SUFFIXES:
        return True
    return False


def _contains_secrets(text: str) -> bool:
    return bool(_SECRET_PATTERN.search(text))


def _scan_files(project_path: Path, extra_skip: frozenset[str] = frozenset()) -> list[Path]:
    effective_skip = _SKIP_DIRS | extra_skip
    files: list[Path] = []
    code_count = 0
    for f in sorted(project_path.rglob("*")):
        rel_parts = f.relative_to(project_path).parts
        if any(part in effective_skip for part in rel_parts):
            continue
        if extra_skip:
            rel_str = "/".join(rel_parts)
            if any(rel_str.startswith(d.rstrip("/") + "/") or rel_str == d for d in extra_skip):
                continue
        if not f.is_file():
            continue
        if _is_sensitive_file(f):
            continue
        if f.stat().st_size > _MAX_FILE_BYTES:
            continue
        if f.suffix in _SCAN_EXTENSIONS:
            files.append(f)
        elif f.suffix in _CODE_EXTENSIONS and code_count < _MAX_CODE_FILES:
            files.append(f)
            code_count += 1
    return files


def index_project(project: str, project_path: Path, extra_skip_dirs: list[str] | None = None) -> int:
    try:
        col = _docs_collection()
    except Exception:
        return 0

    from datetime import datetime, timezone
    from orchestrator.db import _conn, _write_lock

    extra_skip = frozenset(extra_skip_dirs) if extra_skip_dirs else frozenset()
    total = 0
    for fpath in _scan_files(project_path, extra_skip):
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if _contains_secrets(text):
            continue

        rel = str(fpath.relative_to(project_path))
        chunks = chunk_text(text, source=rel)
        if not chunks:
            continue

        ids = [f"{project}::{rel}::{c['chunk_idx']}" for c in chunks]
        docs = [c["text"] for c in chunks]
        metas = [{"project": project, "source": rel, "chunk_idx": c["chunk_idx"]} for c in chunks]

        try:
            previous = col.get(
                where={
                    "$and": [
                        {"project": {"$eq": project}},
                        {"source": {"$eq": rel}},
                    ]
                },
                include=[],
            )
            col.upsert(ids=ids, documents=docs, metadatas=metas)
            stale_ids = sorted(set(previous.get("ids") or []) - set(ids))
            if stale_ids:
                col.delete(ids=stale_ids)
            total += len(chunks)
        except Exception:
            continue

        ts = datetime.now(timezone.utc).isoformat()
        conn = _conn()
        with _write_lock:
            conn.execute(
                """INSERT INTO chunks (project, source_path, chunk_count, ts, collection)
                   VALUES (?, ?, ?, ?, 'docs')
                   ON CONFLICT(project, source_path) DO UPDATE SET
                   chunk_count=excluded.chunk_count, ts=excluded.ts""",
                (project, rel, len(chunks), ts),
            )
            conn.commit()

    if extra_skip:
        _purge_excluded_dirs(col, project, extra_skip)

    return total


def _purge_excluded_dirs(col, project: str, extra_skip: frozenset[str]) -> None:
    """Elimina de ChromaDB y SQLite los chunks de carpetas que ahora están excluidas."""
    try:
        all_indexed = col.get(
            where={"project": {"$eq": project}},
            include=["metadatas"],
        )
    except Exception:
        return

    ids_to_delete = []
    sources_to_delete: set[str] = set()
    for doc_id, meta in zip(all_indexed.get("ids") or [], all_indexed.get("metadatas") or []):
        source = ((meta or {}).get("source") or "").replace("\\", "/")
        for skip_dir in extra_skip:
            prefix = skip_dir.rstrip("/")
            if source == prefix or source.startswith(prefix + "/"):
                ids_to_delete.append(doc_id)
                sources_to_delete.add((meta or {}).get("source", source))
                break

    if not ids_to_delete:
        return

    try:
        col.delete(ids=ids_to_delete)
    except Exception:
        return

    from orchestrator.db import _conn, _write_lock
    conn = _conn()
    with _write_lock:
        for src in sources_to_delete:
            conn.execute(
                "DELETE FROM chunks WHERE project=? AND source_path=?",
                (project, src),
            )
        conn.commit()


def preview_index(
    project_path: Path,
    stack: str = "",
    saved_skip: list[str] | None = None,
) -> list[dict]:
    """Devuelve carpetas de primer nivel con conteo de archivos indexables.

    Usado por el Inspector para mostrar el pre-flight antes de indexar.
    """
    saved = set(saved_skip or [])
    results = []
    try:
        entries = sorted(project_path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS:
            continue
        try:
            count = len(_scan_files(entry, frozenset()))
        except Exception:
            count = 0
        results.append({
            "name": entry.name,
            "file_count": count,
            "suggested_skip": _is_suggested_skip(entry.name, stack),
            "already_excluded": entry.name in saved,
        })
    return results


def persist_context_hits(run_id: int, chunks: list[dict]) -> None:
    """Persiste en context_hits los chunks ya recuperados, una vez que run_id es conocido.
    Cada chunk debe tener 'collection', 'source', 'score' y opcionalmente 'chunk_idx'.
    """
    if not chunks:
        return
    try:
        from datetime import datetime, timezone
        from orchestrator.db import _conn, _write_lock
        conn = _conn()
        ts = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                run_id,
                c.get("collection", "docs"),
                c.get("source", ""),
                c.get("chunk_idx"),
                c.get("score"),
                ts,
            )
            for c in chunks
        ]
        with _write_lock:
            conn.executemany(
                """INSERT INTO context_hits (run_id, collection, source, chunk_idx, score, ts)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
    except Exception:
        pass


def retrieve_docs(task: str, project: str, n: int = 4) -> list[dict]:
    if not task.strip():
        return []
    try:
        col = _docs_collection()
        res = col.query(
            query_texts=[task],
            n_results=n,
            where={"project": project},
            include=["documents", "metadatas", "distances"],
        )
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]
        return [
            {"text": d, "source": m.get("source", ""), "score": round(float(dist), 6),
             "chunk_idx": m.get("chunk_idx"), "collection": "docs"}
            for d, m, dist in zip(docs, metas, distances)
            if dist < _DISTANCE_THRESHOLD
        ]
    except Exception:
        return []


def retrieve_responses(task: str, project: str, n: int = 2) -> list[dict]:
    if not task.strip():
        return []
    try:
        col = _responses_collection()
        res = col.query(
            query_texts=[task],
            n_results=n,
            where={"project": project},
            include=["documents", "metadatas", "distances"],
        )
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]
        return [
            {"text": d, "source": f"run #{m.get('run_id', '?')}", "score": round(float(dist), 6),
             "chunk_idx": None, "collection": "responses"}
            for d, m, dist in zip(docs, metas, distances)
            if dist < _DISTANCE_THRESHOLD
        ]
    except Exception:
        return []


def build_context_block(doc_chunks: list[dict], response_chunks: list[dict]) -> str:
    if not doc_chunks and not response_chunks:
        return ""
    parts = ["## Contexto recuperado del proyecto"]
    if doc_chunks:
        parts.append("### Documentación relevante")
        for c in doc_chunks:
            parts.append(f"**{c['source']}:**\n```\n{c['text']}\n```")
    if response_chunks:
        parts.append("### Respuestas previas similares")
        for r in response_chunks:
            parts.append(f"**{r['source']}:**\n{r['text']}")
    return "\n\n".join(parts)


def chroma_stats() -> dict:
    # Colecciones activas: 'docs' (documentación indexada) y 'responses' (respuestas previas).
    # La colección 'runs' fue eliminada — nunca se escribió en ella.
    try:
        client = _get_client()
        result: dict = {}
        for col_name in ("docs", "responses"):
            try:
                col = client.get_collection(col_name)
                count = col.count()
                if count > 0:
                    by_project: dict[str, int] = {}
                    offset = 0
                    page_size = 1000
                    while offset < count:
                        items = col.get(include=["metadatas"], limit=page_size, offset=offset)
                        metadatas = items.get("metadatas") or []
                        if not metadatas:
                            break
                        for m in metadatas:
                            p = (m or {}).get("project", "?")
                            by_project[p] = by_project.get(p, 0) + 1
                        offset += len(metadatas)
                    result[col_name] = {"count": count, "by_project": by_project}
                else:
                    result[col_name] = {"count": 0, "by_project": {}}
            except Exception:
                result[col_name] = {"count": 0, "by_project": {}}
        return result
    except Exception:
        return {}


def purge_project_responses(project: str) -> int:
    """Elimina de ChromaDB todos los vectores de respuestas de un proyecto. Retorna cantidad eliminada."""
    try:
        col = _responses_collection()
        result = col.get(where={"project": {"$eq": project}}, include=[])
        ids = result.get("ids") or []
        if ids:
            col.delete(ids=ids)
        return len(ids)
    except Exception:
        return 0


def purge_project_docs(project: str) -> int:
    """Elimina de ChromaDB los vectores de documentación de un proyecto. Retorna cantidad eliminada."""
    try:
        col = _docs_collection()
        result = col.get(where={"project": {"$eq": project}}, include=[])
        ids = result.get("ids") or []
        if ids:
            col.delete(ids=ids)
        # limpiar tabla chunks
        try:
            from orchestrator.db import _conn, _write_lock
            conn = _conn()
            with _write_lock:
                conn.execute("DELETE FROM chunks WHERE project=?", (project,))
                conn.commit()
        except Exception:
            pass
        return len(ids)
    except Exception:
        return 0


def index_response(run_id: int, project: str, task: str, response: str) -> None:
    if not response.strip():
        return
    try:
        col = _responses_collection()
        col.upsert(
            ids=[f"run_{run_id}"],
            documents=[f"Tarea: {task[:200]}\n\nRespuesta: {response[:1500]}"],
            metadatas=[{"project": project, "run_id": run_id}],
        )
    except Exception:
        pass
