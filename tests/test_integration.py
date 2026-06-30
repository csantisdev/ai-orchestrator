"""Test de integración: db, costs, similarity, contextos y MCP tools."""
import json
import threading
import tempfile
from pathlib import Path


def _close_db(db_mod):
    if hasattr(db_mod._local, "conn") and db_mod._local.conn:
        db_mod._local.conn.close()
        db_mod._local.conn = None


def test_db_lifecycle():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()

        from orchestrator.providers.base import CompletionResult
        run_id = db_mod.insert_run("proj", "crear tests", "claude", "claude-sonnet-4-6")
        assert isinstance(run_id, int)

        result = CompletionResult(
            text="respuesta",
            provider="claude",
            model="claude-sonnet-4-6",
            raw_response={"usage": {"input_tokens": 500, "output_tokens": 200}},
            cache_creation_tokens=0,
            cache_read_tokens=50,
        )
        db_mod.update_run(run_id, result, duration_ms=1000, routing_reason="router", cost_usd=0.005)

        rows = db_mod.read_runs()
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "done"
        assert row["provider"] == "claude"
        assert row["cost_usd"] == 0.005
        assert row["cache_read_tokens"] == 50

        cost = db_mod.daily_cost("proj")
        assert abs(cost - 0.005) < 1e-9

    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_cost_calculation():
    from orchestrator.providers.base import CompletionResult
    from orchestrator.costs import calculate_cost, DEFAULT_PRICING

    result = CompletionResult(
        text="r",
        provider="claude",
        model="claude-sonnet-4-6",
        raw_response={"usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}},
    )
    cost = calculate_cost(result, DEFAULT_PRICING)
    assert cost is not None
    assert abs(cost - (3.00 + 15.00)) < 0.001


def test_cost_calculation_direct_tokens():
    from orchestrator.providers.base import CompletionResult
    from orchestrator.costs import calculate_cost, DEFAULT_PRICING

    result = CompletionResult(
        text="r",
        provider="claude",
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        raw_response={},
    )
    cost = calculate_cost(result, DEFAULT_PRICING)
    assert cost is not None
    assert abs(cost - (3.00 + 15.00)) < 0.001


def test_context_and_steps():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()

        ctx_id = db_mod.insert_context("mi-proyecto", "Implementar MCP", "Descripción del objetivo")
        assert isinstance(ctx_id, int)

        s1 = db_mod.insert_step(ctx_id, 1, "Diseñar schema", provider="claude")
        s2 = db_mod.insert_step(ctx_id, 2, "Implementar handlers", provider="deepseek")
        assert s1 < s2

        rows = db_mod.read_contexts_with_steps("mi-proyecto")
        assert len(rows) == 1
        assert rows[0]["title"] == "Implementar MCP"
        assert len(rows[0]["steps"]) == 2
        assert rows[0]["steps"][0]["order_idx"] == 1
        assert rows[0]["steps"][1]["provider"] == "deepseek"

    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_mcp_tool_handlers():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()

        from orchestrator.mcp import (
            _tool_get_context,
            _tool_list_steps,
            _tool_confirm_alignment,
            _tool_record_tool_call,
            _tool_advance_step,
        )

        ctx_id = db_mod.insert_context("test-proj", "Test MCP", "Objetivo de prueba")
        db_mod.insert_step(ctx_id, 1, "Paso uno", provider="claude")
        db_mod.insert_step(ctx_id, 2, "Paso dos", provider="deepseek")
        db_mod.activate_first_step(ctx_id)

        ctx = _tool_get_context({"project": "test-proj"})
        assert ctx["title"] == "Test MCP"
        assert ctx["status"] == "active"

        result = _tool_list_steps({"context_id": ctx_id})
        assert len(result["steps"]) == 2
        assert result["steps"][0]["title"] == "Paso uno"

        step_id = result["steps"][0]["id"]

        align = _tool_confirm_alignment({
            "step_id": step_id,
            "context_id": ctx_id,
            "agent": "claude-code",
            "checkpoint": "antes de ejecutar paso 1",
            "confirmed": True,
            "message": "todo ok",
        })
        assert align["confirmed"] is True
        assert isinstance(align["id"], int)

        tc = _tool_record_tool_call({
            "step_id": step_id,
            "context_id": ctx_id,
            "tool_name": "Edit",
            "input": {"file": "db.py"},
            "output": "ok",
            "status": "ok",
            "duration_ms": 120,
        })
        assert isinstance(tc["id"], int)

        advance = _tool_advance_step({"step_id": step_id, "notes": "completado"})
        assert advance["completed_step_id"] == step_id
        assert advance["next_step"] is not None
        assert advance["next_step"]["title"] == "Paso dos"
        assert advance["context_done"] is False

        advance2 = _tool_advance_step({"step_id": advance["next_step"]["id"], "notes": "listo"})
        assert advance2["context_done"] is True
        assert advance2["next_step"] is None

        final_ctx = _tool_get_context({"context_id": ctx_id})
        assert final_ctx["status"] == "completed"

    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_update_context_and_step():
    import shutil
    import threading
    import tempfile
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod
    from orchestrator.mcp import (
        _tool_create_context,
        _tool_update_context,
        _tool_update_step,
        _tool_get_context,
        _tool_list_steps,
        _tool_add_step,
    )

    tmp = tempfile.mkdtemp()
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = paths_mod.Path(tmp)
    paths_mod.DB_PATH  = paths_mod.Path(tmp) / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()

        ctx = _tool_create_context({
            "project": "test-proj",
            "title": "Titulo inicial ASCII",
            "description": "Descripcion inicial",
        })
        ctx_id = ctx["context_id"]

        step = _tool_add_step({"context_id": ctx_id, "title": "Paso inicial ASCII"})
        step_id = step["step_id"]

        # update_context con UTF-8 real
        res = _tool_update_context({
            "context_id": ctx_id,
            "title": "Configuración técnica",
            "description": "implementación correcta con acentos: á é í ó ú ñ",
        })
        assert res["updated"] == ["title", "description"]

        fetched = _tool_get_context({"context_id": ctx_id})
        assert fetched["title"] == "Configuración técnica"
        assert "á" in fetched["description"]

        # update_step con UTF-8 real
        res2 = _tool_update_step({
            "step_id": step_id,
            "title": "Implementación del módulo",
            "notes": "Revisión técnica completada",
        })
        assert res2["updated"] == ["title", "notes"]

        steps = _tool_list_steps({"context_id": ctx_id})
        s = steps["steps"][0]
        assert s["title"] == "Implementación del módulo"
        assert s["notes"] == "Revisión técnica completada"
        assert s["description"] == ""  # no enviado, no tocado

        # omitir todos los campos no hace nada (no error)
        res3 = _tool_update_context({"context_id": ctx_id})
        assert res3["updated"] == []

        res4 = _tool_update_step({"step_id": step_id})
        assert res4["updated"] == []

        # campo vacío explícito sí se guarda (distinto de omitido)
        res5 = _tool_update_step({"step_id": step_id, "notes": ""})
        assert res5["updated"] == ["notes"]
        steps2 = _tool_list_steps({"context_id": ctx_id})
        assert steps2["steps"][0]["notes"] == ""

        # context_id / step_id inexistente lanza ValueError
        import pytest
        with pytest.raises(ValueError, match="not found"):
            _tool_update_context({"context_id": 99999, "title": "x"})
        with pytest.raises(ValueError, match="not found"):
            _tool_update_step({"step_id": 99999, "title": "x"})

    finally:
        def _close_db(mod):
            try:
                if hasattr(mod._local, "conn") and mod._local.conn:
                    mod._local.conn.close()
            except Exception:
                pass
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        shutil.rmtree(tmp, ignore_errors=True)


def test_mcp_result_supports_modern_and_legacy_clients():
    from orchestrator.mcp import (
        DEFAULT_PROTOCOL_VERSION,
        SERVER_INSTRUCTIONS,
        SUPPORTED_PROTOCOL_VERSIONS,
        _tool_call_result,
    )

    payload = {"context_id": 7, "status": "active"}
    result = _tool_call_result(payload)

    assert result["structuredContent"] == payload
    assert json.loads(result["content"][0]["text"]) == payload
    assert "get_context" in SERVER_INSTRUCTIONS
    assert "advance_step" in SERVER_INSTRUCTIONS
    assert "2024-11-05" in SUPPORTED_PROTOCOL_VERSIONS
    assert DEFAULT_PROTOCOL_VERSION == "2025-06-18"


def test_step_id_propagation():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()

        ctx_id = db_mod.insert_context("proj-x", "Plan de prueba", "Verifica step_id")
        step_id = db_mod.insert_step(ctx_id, 1, "Paso activo", provider="deepseek")

        conn = db_mod._conn()
        conn.execute("UPDATE steps SET status='in_progress' WHERE id=?", (step_id,))
        conn.commit()

        run_id = db_mod.insert_run("proj-x", "tarea de prueba", step_id=step_id)

        rows = db_mod.read_runs(project="proj-x")
        assert len(rows) == 1
        assert rows[0]["step_id"] == step_id

    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_tool_calls_and_alignments_readable():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()

    try:
        db_mod.init_db()

        from orchestrator.mcp import _tool_record_tool_call, _tool_confirm_alignment

        ctx_id = db_mod.insert_context("proj-y", "Contexto lectura", "")
        step_id = db_mod.insert_step(ctx_id, 1, "Paso lectura", provider="claude")

        _tool_record_tool_call({
            "step_id": step_id, "context_id": ctx_id,
            "tool_name": "Read", "input": {"path": "db.py"},
            "output": "ok", "status": "ok", "duration_ms": 50,
        })
        _tool_confirm_alignment({
            "step_id": step_id, "context_id": ctx_id,
            "agent": "claude-code", "checkpoint": "antes de paso 1",
            "confirmed": True, "message": "listo",
        })

        tcs = db_mod.read_tool_calls_for_step(step_id)
        aligns = db_mod.read_alignments_for_step(step_id)

        assert len(tcs) == 1
        assert tcs[0]["tool_name"] == "Read"
        assert tcs[0]["status"] == "ok"

        assert len(aligns) == 1
        assert aligns[0]["checkpoint"] == "antes de paso 1"
        assert aligns[0]["confirmed"] == 1

    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_rag_chunk_text():
    from orchestrator.rag import chunk_text

    text = "A" * 2000
    chunks = chunk_text(text, source="test.md", chunk_size=1500, overlap=200)

    assert [len(c["text"]) for c in chunks] == [1500, 700]
    for c in chunks:
        assert len(c["text"]) <= 1500
        assert c["source"] == "test.md"
    assert chunks[0]["chunk_idx"] == 0
    assert chunks[1]["chunk_idx"] == 1
    assert chunks[0]["text"][-200:] == chunks[1]["text"][:200]


def test_rag_chunk_text_rejects_invalid_configuration():
    import pytest
    from orchestrator.rag import chunk_text

    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("texto", source="test.md", chunk_size=0)
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("texto", source="test.md", chunk_size=100, overlap=100)


def test_rag_index_and_retrieve():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod
    import orchestrator.similarity as sim_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()
    sim_mod._backend_cache = None

    try:
        db_mod.init_db()

        import orchestrator.rag as rag_mod

        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        readme = project_dir / "README.md"
        readme.write_text(
            "Este proyecto gestiona tickets de soporte interno. "
            "Permite buscar, filtrar y exportar bases de ticket.",
            encoding="utf-8",
        )

        n = rag_mod.index_project("myproject", project_dir)
        assert n > 0

        rows = db_mod._conn().execute(
            "SELECT * FROM chunks WHERE project='myproject'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["source_path"] == "README.md"

        results = rag_mod.retrieve_docs("tickets de soporte interno", "myproject", n=2)
        assert len(results) >= 1
        assert "ticket" in results[0]["text"].lower() or "tickets" in results[0]["text"].lower()

        block = rag_mod.build_context_block(results, [])
        assert "Documentación relevante" in block
        assert "README.md" in block

        readme.write_text("Documento breve actualizado.", encoding="utf-8")
        assert rag_mod.index_project("myproject", project_dir) == 1
        indexed = rag_mod._docs_collection().get(
            where={
                "$and": [
                    {"project": {"$eq": "myproject"}},
                    {"source": {"$eq": "README.md"}},
                ]
            },
            include=["documents"],
        )
        assert indexed["ids"] == ["myproject::README.md::0"]
        assert indexed["documents"] == ["Documento breve actualizado."]

    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        sim_mod._backend_cache = None
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_similarity_backend():
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod
    import orchestrator.similarity as sim_mod

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    original_home = paths_mod.HOME_DIR
    original_db   = paths_mod.DB_PATH
    paths_mod.HOME_DIR = tmp_path
    paths_mod.DB_PATH  = tmp_path / "runs.db"
    db_mod._local = threading.local()
    sim_mod._backend_cache = None

    try:
        db_mod.init_db()
        backend = sim_mod.get_backend(tmp_path)
        assert isinstance(backend, (sim_mod.FTS5Backend, sim_mod.ChromaBackend))
        backend.upsert(1, "crear tests para modelo User")
        result = backend.query("tests modelo")
        assert isinstance(result, list)
    finally:
        _close_db(db_mod)
        paths_mod.HOME_DIR = original_home
        paths_mod.DB_PATH  = original_db
        db_mod._local = threading.local()
        sim_mod._backend_cache = None
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_secret_filter():
    import shutil
    import tempfile
    from pathlib import Path

    from orchestrator.rag import (
        _SKIP_FILENAMES,
        _SKIP_SUFFIXES,
        _contains_secrets,
        _is_sensitive_file,
        _scan_files,
    )

    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)

    try:
        for fname in [".env", "credentials.json", "id_rsa", ".npmrc", "secrets.yaml"]:
            f = tmp_path / fname
            f.write_text("VAR=value", encoding="utf-8")
            assert _is_sensitive_file(f), f"{fname} debería ser sensible por nombre"

        for suffix in [".pem", ".key", ".p12", ".pfx"]:
            f = tmp_path / f"cert{suffix}"
            f.write_text("dummy", encoding="utf-8")
            assert _is_sensitive_file(f), f"cert{suffix} debería ser sensible por extensión"

        assert _contains_secrets("sk-ant-api01-" + "A" * 30)
        assert _contains_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIEo...")
        assert not _contains_secrets("este archivo no tiene credenciales")
        assert not _contains_secrets("sk-short")

        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("Documentación pública.", encoding="utf-8")
        (project_dir / ".env").write_text("API_KEY=valor", encoding="utf-8")
        (project_dir / "server.key").write_text("dummy key content", encoding="utf-8")

        scanned = _scan_files(project_dir)
        scanned_names = {f.name for f in scanned}

        assert "README.md" in scanned_names
        assert ".env" not in scanned_names
        assert "server.key" not in scanned_names

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
