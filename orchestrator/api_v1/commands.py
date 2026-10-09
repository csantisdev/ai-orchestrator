"""Comandos gobernados de la UI (RFC-010 §3.1): única vía de escritura de las vistas migradas."""

from __future__ import annotations

from orchestrator import commands
from orchestrator.api_v1 import Request, route


@route("GET", "/api/v1/commands")
def list_commands(request: Request) -> dict:
    return commands.catalog_view()


@route("POST", "/api/v1/commands/{name}")
def run_command(request: Request) -> tuple[int, dict]:
    return commands.execute(request.params["name"], request.body or {})
