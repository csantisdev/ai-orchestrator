"""Pasos iniciales de un contexto: esquema compartido entre el MCP y la CLI."""

from __future__ import annotations

import json
import re

from orchestrator.mcp_governance import ArgumentValidationError, validate_arguments

STEPS_SCHEMA = {
    "type": "array",
    "description": "Pasos iniciales del contexto (opcional).",
    "items": {
        "type": "object",
        "properties": {
            "title":    {"type": "string"},
            "provider": {"type": "string", "default": ""},
            "agent_preset": {
                "type": "string", "default": "",
                "description": "Nombre de un agente registrado (preset de provider/model/system-prompt). Ver list_agents.",
            },
        },
        "required": ["title"],
    },
}

_LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


class StepSpecError(ValueError):
    """Un paso inicial mal formado; se reporta antes de escribir nada."""


def parse_step_option(spec: str) -> dict:
    """Interpreta `--step 'Título:etiqueta'`.

    La etiqueta es lo que sigue al último ':' solo si va pegada (sin espacio)
    y tiene forma de identificador; si no, todo el texto es el título. Así
    'Fase 1: schema:claude' conserva el ':' del título y 'Fix: parser' no
    tiene etiqueta.
    """
    text = spec.strip()
    head, sep, tail = text.rpartition(":")
    if sep and _LABEL_RE.fullmatch(tail):
        title, provider = head.strip(), tail
    else:
        title, provider = text, ""
    if not title:
        raise StepSpecError(f"paso sin título: {spec!r}")
    return {"title": title, "provider": provider, "agent_preset": ""}


def load_steps_json(raw: str) -> list[dict]:
    """Valida una lista JSON de pasos con el mismo esquema que el MCP create_context."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StepSpecError(f"JSON inválido: {exc}") from exc
    try:
        validate_arguments({"type": "object", "properties": {"steps": STEPS_SCHEMA}}, {"steps": data})
    except ArgumentValidationError as exc:
        raise StepSpecError(str(exc)) from exc
    steps = []
    for index, item in enumerate(data):
        title = item["title"].strip()
        if not title:
            raise StepSpecError(f"steps[{index}].title está vacío")
        steps.append({
            "title": title,
            "provider": item.get("provider", "").strip(),
            "agent_preset": item.get("agent_preset", "").strip(),
        })
    return steps
