"""CLI del orquestador, construido con Typer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import typer
from rich.console import Console
from rich.table import Table

from orchestrator import context as context_module
from orchestrator import index as index_module
from orchestrator import router as router_module
from orchestrator.config import ConfigError, load_config
from orchestrator.context import ContextNotFoundError
from orchestrator.index import ProjectNotFoundError
from orchestrator.paths import PROVIDERS
from orchestrator.providers.factory import build_provider

app = typer.Typer(
    name="ai-orchestrator",
    help="Orquestador local de agentes IA. Rutea tareas entre Claude, OpenAI y DeepSeek.",
    no_args_is_help=True,
)
console = Console(legacy_windows=False)


@app.command()
def add(
    alias: str = typer.Argument(..., help="Alias corto para referirte al proyecto."),
    path: str = typer.Option(..., "--path", "-p", help="Ruta absoluta al proyecto."),
    stack: str = typer.Option("", "--stack", help="Stack tecnológico (ej. 'PHP/Laravel')."),
    description: str = typer.Option("", "--description", "-d", help="Descripción breve del proyecto."),
    default_provider: str = typer.Option(
        "claude", "--default-provider", help=f"Proveedor por defecto. Opciones: {', '.join(PROVIDERS)}"
    ),
):
    """Registra un proyecto en el índice y genera su context.yaml si no existe."""
    project_path = Path(path).expanduser().resolve()

    if not project_path.exists():
        console.print(f"[red]✗[/red] La ruta no existe: {project_path}")
        raise typer.Exit(code=1)

    if default_provider not in PROVIDERS:
        console.print(f"[red]✗[/red] Proveedor inválido: '{default_provider}'. Opciones: {', '.join(PROVIDERS)}")
        raise typer.Exit(code=1)

    index_module.add_project(alias, str(project_path))

    if context_module.context_exists(project_path):
        console.print(f"[yellow]ℹ[/yellow] {alias} ya tenía un context.yaml, se mantuvo sin cambios.")
    else:
        ctx_path = context_module.create_default_context(
            project_path=project_path,
            name=alias,
            stack=stack,
            description=description,
            default_provider=default_provider,
        )
        console.print(f"[green]✓[/green] Context generado en {ctx_path}")

    console.print(f"[green]✓[/green] Proyecto '{alias}' registrado -> {project_path}")
    console.print("  Revisá y completá el context.yaml antes de usarlo en serio.")


@app.command(name="list")
def list_command():
    """Lista los proyectos registrados en el índice."""
    projects = index_module.list_projects()

    if not projects:
        console.print("[yellow]No hay proyectos registrados.[/yellow] Usá 'ai-orchestrator add <alias> --path <ruta>'.")
        return

    table = Table(title="Proyectos registrados")
    table.add_column("Alias", style="cyan")
    table.add_column("Path", style="white")
    table.add_column("Context", style="green")

    for alias, path in sorted(projects.items()):
        has_context = context_module.context_exists(Path(path))
        table.add_row(alias, path, "✓" if has_context else "✗ falta")

    console.print(table)


@app.command()
def remove(alias: str = typer.Argument(..., help="Alias del proyecto a quitar del índice.")):
    """Quita un proyecto del índice (no borra archivos del proyecto)."""
    try:
        index_module.remove_project(alias)
        console.print(f"[green]✓[/green] '{alias}' fue quitado del índice.")
    except ProjectNotFoundError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)


@app.command()
def run(
    task: str = typer.Option(..., "--task", "-t", help="Descripción de la tarea a resolver."),
    project: str = typer.Option(..., "--project", "-p", help="Alias del proyecto registrado."),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help=f"Forzar un proveedor específico ({', '.join(PROVIDERS)}), sin pasar por el router."
    ),
    show_reason: bool = typer.Option(True, "--show-reason/--no-show-reason", help="Mostrar la justificación del ruteo."),
):
    """Ejecuta una tarea: resuelve el contexto del proyecto, rutea y llama al provider."""
    try:
        config = load_config()
    except ConfigError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    try:
        project_path = index_module.get_project_path(project)
    except ProjectNotFoundError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    try:
        ctx = context_module.load_context(project_path)
    except ContextNotFoundError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    if model:
        try:
            decision = router_module.force_provider(model)
        except ValueError as exc:
            console.print(f"[red]✗[/red] {exc}")
            raise typer.Exit(code=1)
    else:
        with console.status("[bold cyan]Consultando al router..."):
            decision = router_module.decide_provider(task=task, ctx=ctx, config=config)

    if show_reason:
        style = "yellow" if decision.used_fallback else "cyan"
        console.print(f"[{style}]→ Proveedor elegido: {decision.provider}[/{style}]  ({decision.reason})")

    try:
        provider = build_provider(config, decision.provider)
    except (ConfigError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    system_prompt = (
        f"Estás trabajando en el proyecto '{ctx.name}'.\n"
        f"Stack: {ctx.stack}\n"
        f"Convenciones: {', '.join(ctx.conventions) if ctx.conventions else 'ninguna registrada'}\n"
    )

    with console.status(f"[bold cyan]Ejecutando en {decision.provider}..."):
        result = provider.complete(prompt=task, system=system_prompt)

    console.print()
    console.print(f"[bold green]── Respuesta ({result.provider}/{result.model}) ──[/bold green]")
    console.print(result.text)


if __name__ == "__main__":
    app()
