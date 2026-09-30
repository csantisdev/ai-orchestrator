import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.step_specs import StepSpecError, load_steps_json, parse_step_option


@pytest.mark.parametrize("spec, title, provider", [
    ("Diseñar schema:claude", "Diseñar schema", "claude"),
    ("Fase 1: diseñar schema:claude", "Fase 1: diseñar schema", "claude"),
    ("A8 Tema /api/v1: detalle, detalle:claude", "A8 Tema /api/v1: detalle, detalle", "claude"),
    ("Fix: parser", "Fix: parser", ""),
    ("Tema:detalle con espacios", "Tema:detalle con espacios", ""),
    ("Revisar PR:codex", "Revisar PR", "codex"),
    ("Tarea:copilot_agent-2", "Tarea", "copilot_agent-2"),
    ("Reunión 10:30", "Reunión 10:30", ""),
    ("Probar http://x:8080", "Probar http://x:8080", ""),
    (r"Limpiar C:\temp", r"Limpiar C:\temp", ""),
    ("  Paso con espacios :claude  ", "Paso con espacios", "claude"),
    ("Sin etiqueta", "Sin etiqueta", ""),
    ("Termina en dos puntos:", "Termina en dos puntos:", ""),
])
def test_parse_step_option(spec, title, provider):
    assert parse_step_option(spec) == {"title": title, "provider": provider, "agent_preset": ""}


@pytest.mark.parametrize("spec", ["", "   ", ":claude", "  :claude"])
def test_parse_step_option_rejects_empty_title(spec):
    with pytest.raises(StepSpecError):
        parse_step_option(spec)


def test_load_steps_json_normalizes_steps():
    raw = json.dumps([
        {"title": " Paso: con dos puntos:claude ", "provider": " codex ", "agent_preset": "reviewer"},
        {"title": "Otro"},
    ])

    assert load_steps_json(raw) == [
        {"title": "Paso: con dos puntos:claude", "provider": "codex", "agent_preset": "reviewer"},
        {"title": "Otro", "provider": "", "agent_preset": ""},
    ]


@pytest.mark.parametrize("raw", [
    "no es json",
    json.dumps({"title": "no es lista"}),
    json.dumps([{"provider": "claude"}]),
    json.dumps([{"title": 3}]),
    json.dumps([{"title": "x", "extra": 1}]),
    json.dumps([{"title": "  "}]),
    json.dumps(["solo texto"]),
])
def test_load_steps_json_rejects_invalid_input(raw):
    with pytest.raises(StepSpecError):
        load_steps_json(raw)


def _context_rows(project):
    from orchestrator.db import _conn
    conn = _conn()
    contexts = conn.execute("SELECT id FROM contexts WHERE project=?", (project,)).fetchall()
    steps = conn.execute(
        """SELECT s.order_idx, s.title, s.provider, s.agent_preset, s.status
           FROM steps s JOIN contexts c ON c.id=s.context_id
           WHERE c.project=? ORDER BY s.order_idx""",
        (project,),
    ).fetchall()
    return contexts, [dict(row) for row in steps]


def test_create_context_keeps_colons_in_step_titles():
    result = CliRunner().invoke(app, [
        "create-context", "-p", "cli-colon", "-t", "Plan [x]",
        "-s", "A1 Tema: detalle (Q-01):claude",
        "-s", "Fix: parser",
        "-s", "Revisar [bold]:codex",
    ])

    assert result.exit_code == 0, result.output
    contexts, steps = _context_rows("cli-colon")
    assert len(contexts) == 1
    assert [(s["title"], s["provider"], s["status"]) for s in steps] == [
        ("A1 Tema: detalle (Q-01)", "claude", "in_progress"),
        ("Fix: parser", "", "pending"),
        ("Revisar [bold]", "codex", "pending"),
    ]
    assert "Plan [x]" in result.output
    assert "[claude] — A1 Tema: detalle (Q-01)" in result.output
    assert "[codex] — Revisar [bold]" in result.output


def test_create_context_rejects_invalid_step_without_writing():
    result = CliRunner().invoke(app, [
        "create-context", "-p", "cli-invalid", "-t", "Plan", "-s", "Válido:claude", "-s", ":claude",
    ])

    assert result.exit_code == 1
    assert "Pasos inválidos" in result.output
    assert _context_rows("cli-invalid") == ([], [])


def test_create_context_rolls_back_when_a_step_insert_fails():
    import orchestrator.db as db_module
    original = db_module.insert_step
    calls = []

    def failing_insert_step(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise RuntimeError("fallo simulado")
        return original(*args, **kwargs)

    with patch.object(db_module, "insert_step", failing_insert_step):
        result = CliRunner().invoke(app, [
            "create-context", "-p", "cli-rollback", "-t", "Plan", "-s", "Uno:claude", "-s", "Dos:claude",
        ])

    assert result.exit_code != 0
    assert _context_rows("cli-rollback") == ([], [])


def test_create_context_reads_steps_json_file(tmp_path):
    steps_file = tmp_path / "steps.json"
    steps_file.write_text(json.dumps([
        {"title": "Termina de verdad en :claude", "agent_preset": "reviewer"},
        {"title": "Segundo", "provider": "codex"},
    ]), encoding="utf-8")

    result = CliRunner().invoke(app, [
        "create-context", "-p", "cli-json", "-t", "Plan", "--steps-json", str(steps_file),
    ])

    assert result.exit_code == 0, result.output
    _, steps = _context_rows("cli-json")
    assert [(s["title"], s["provider"], s["agent_preset"]) for s in steps] == [
        ("Termina de verdad en :claude", "", "reviewer"),
        ("Segundo", "codex", ""),
    ]


def test_create_context_reads_steps_json_from_stdin():
    result = CliRunner().invoke(
        app,
        ["create-context", "-p", "cli-stdin", "-t", "Plan", "--steps-json", "-"],
        input=json.dumps([{"title": "Desde stdin: ok"}]),
    )

    assert result.exit_code == 0, result.output
    _, steps = _context_rows("cli-stdin")
    assert [s["title"] for s in steps] == ["Desde stdin: ok"]


def test_create_context_rejects_step_and_steps_json_together(tmp_path):
    steps_file = tmp_path / "steps.json"
    steps_file.write_text("[]", encoding="utf-8")

    result = CliRunner().invoke(app, [
        "create-context", "-p", "cli-both", "-t", "Plan", "-s", "Uno", "--steps-json", str(steps_file),
    ])

    assert result.exit_code == 1
    assert _context_rows("cli-both") == ([], [])


def test_create_context_reports_missing_steps_json_file(tmp_path):
    result = CliRunner().invoke(app, [
        "create-context", "-p", "cli-missing", "-t", "Plan", "--steps-json", str(tmp_path / "no-existe.json"),
    ])

    assert result.exit_code == 1
    assert "Pasos inválidos" in result.output
    assert _context_rows("cli-missing") == ([], [])


def test_list_contexts_escapes_markup():
    CliRunner().invoke(app, ["create-context", "-p", "cli-list", "-t", "Plan [red]", "-s", "Paso [b]:claude"])

    result = CliRunner().invoke(app, ["list-contexts", "-p", "cli-list"])

    assert result.exit_code == 0, result.output
    assert "Plan [red]" in result.output
    assert "[claude] Paso [b]" in result.output
