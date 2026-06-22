"""RAG: indexación y recuperación de contexto documental por proyecto."""

from __future__ import annotations

import re
from pathlib import Path

_CHUNK_SIZE = 1500
_CHUNK_OVERLAP = 200
_DISTANCE_THRESHOLD = 1.4
_SCAN_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".toml", ".rst", ".json"}
_CODE_EXTENSIONS = {".py"}
_SKIP_DIRS = {
    ".venv", "venv", "__pycache__", ".git", "node_modules",
    ".eggs", "build", "dist",
    "vendor",           # PHP / Ruby / Go vendor dirs
    ".claude", ".codex",
    ".aws", ".ssh", ".kube", ".gcloud",  # credential dirs
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

_MAX_FILE_BYTES = 100_000
_MAX_PY_FILES = 30


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


def _scan_files(project_path: Path) -> list[Path]:
    files: list[Path] = []
    py_count = 0
    for f in sorted(project_path.rglob("*")):
        if any(part in _SKIP_DIRS for part in f.relative_to(project_path).parts):
            continue
        if not f.is_file():
            continue
        if _is_sensitive_file(f):
            continue
        if f.stat().st_size > _MAX_FILE_BYTES:
            continue
        if f.suffix in _SCAN_EXTENSIONS:
            files.append(f)
        elif f.suffix in _CODE_EXTENSIONS and py_count < _MAX_PY_FILES:
            files.append(f)
            py_count += 1
    return files


def index_project(project: str, project_path: Path) -> int:
    try:
        col = _docs_collection()
    except Exception:
        return 0

    from datetime import datetime, timezone
    from orchestrator.db import _conn, _write_lock

    total = 0
    for fpath in _scan_files(project_path):
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

    return total


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
            {"text": d, "source": m.get("source", "")}
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
            {"text": d, "source": f"run #{m.get('run_id', '?')}"}
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
    try:
        client = _get_client()
        result: dict = {}
        for col_name in ("runs", "docs", "responses"):
            try:
                col = client.get_collection(col_name)
                count = col.count()
                if col_name in ("docs", "responses") and count > 0:
                    items = col.get(include=["metadatas"], limit=2000)
                    by_project: dict[str, int] = {}
                    for m in (items.get("metadatas") or []):
                        p = (m or {}).get("project", "?")
                        by_project[p] = by_project.get(p, 0) + 1
                    result[col_name] = {"count": count, "by_project": by_project}
                else:
                    result[col_name] = {"count": count}
            except Exception:
                result[col_name] = {"count": 0}
        return result
    except Exception:
        return {}


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
