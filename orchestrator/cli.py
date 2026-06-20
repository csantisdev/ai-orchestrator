"""CLI del orquestador, construido con Typer."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import typer
from rich.console import Console
from rich.table import Table

from orchestrator import context as context_module
from orchestrator import history as history_module
from orchestrator import index as index_module
from orchestrator import router as router_module
from orchestrator.config import ConfigError, load_config
from orchestrator.context import ContextNotFoundError
from orchestrator.dashboard import build_html
from orchestrator.index import ProjectNotFoundError
from orchestrator.paths import HOME_DIR, PROVIDERS
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


RESEARCH_MODEL = "claude-opus-4-8"


@app.command()
def run(
    task: Optional[str] = typer.Option(None, "--task", "-t", help="Descripción de la tarea a resolver."),
    task_file: Optional[str] = typer.Option(None, "--task-file", "-f", help="Archivo de texto con la tarea (alternativa a --task)."),
    project: str = typer.Option(..., "--project", "-p", help="Alias del proyecto registrado."),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help=f"Forzar un proveedor específico ({', '.join(PROVIDERS)}), sin pasar por el router."
    ),
    research: bool = typer.Option(
        False, "--research", help=f"Investigación profunda: fuerza Claude {RESEARCH_MODEL}, omite el router."
    ),
    show_reason: bool = typer.Option(True, "--show-reason/--no-show-reason", help="Mostrar la justificación del ruteo."),
):
    """Ejecuta una tarea: resuelve el contexto del proyecto, rutea y llama al provider."""
    if task_file:
        task = Path(task_file).read_text(encoding="utf-8")
    if not task:
        console.print("[red]✗[/red] Debés pasar --task o --task-file.")
        raise typer.Exit(code=1)
    if research and model:
        console.print("[red]✗[/red] --research y --model no pueden usarse juntos.")
        raise typer.Exit(code=1)

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

    if research:
        try:
            decision = router_module.force_provider("claude")
        except ValueError as exc:
            console.print(f"[red]✗[/red] {exc}")
            raise typer.Exit(code=1)
        decision.reason = f"Modo research: {RESEARCH_MODEL}"
    elif model:
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

    if research:
        provider.model = RESEARCH_MODEL

    system_prompt = (
        f"Estás trabajando en el proyecto '{ctx.name}'.\n"
        f"Stack: {ctx.stack}\n"
        f"Convenciones: {', '.join(ctx.conventions) if ctx.conventions else 'ninguna registrada'}\n"
    )

    t0 = time.monotonic()
    with console.status(f"[bold cyan]Ejecutando en {decision.provider}..."):
        result = provider.complete(prompt=task, system=system_prompt)
    duration_ms = int((time.monotonic() - t0) * 1000)

    console.print()
    console.print(f"[bold green]── Respuesta ({result.provider}/{result.model}) ──[/bold green]")
    console.print(result.text)

    history_module.log_run(
        project=project,
        task=task,
        result=result,
        duration_ms=duration_ms,
        routing_reason=decision.reason,
    )


@app.command(name="history")
def history_command(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filtrar por proyecto."),
    last: int = typer.Option(20, "--last", "-n", help="Cantidad de runs a mostrar."),
):
    """Muestra el historial de runs en la terminal."""
    runs = history_module.read_runs(project=project, last=last)

    if not runs:
        msg = f"No hay runs para '{project}'." if project else "No hay runs registrados aún."
        console.print(f"[yellow]{msg}[/yellow]")
        return

    table = Table(title=f"Historial ({len(runs)} runs)", show_lines=False)
    table.add_column("Fecha", style="dim", min_width=12)
    table.add_column("Proyecto", style="cyan")
    table.add_column("Proveedor", min_width=10)
    table.add_column("Modelo", style="dim")
    table.add_column("Dur.", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Tarea", max_width=50)

    PROV_STYLE = {"claude": "orange1", "deepseek": "green", "openai": "blue"}

    for r in reversed(runs):
        from orchestrator.dashboard import _fmt_ms, _fmt_tokens, _fmt_ts
        prov = r.get("provider", "?")
        style = PROV_STYLE.get(prov, "white")
        table.add_row(
            _fmt_ts(r.get("ts", "")),
            r.get("project", "—"),
            f"[{style}]{prov}[/{style}]",
            r.get("model", "—").split("/")[-1],
            _fmt_ms(r.get("duration_ms")),
            _fmt_tokens(r.get("input_tokens"), r.get("output_tokens")),
            (r.get("task_preview", "")[:48] + "…") if len(r.get("task_preview", "")) > 48 else r.get("task_preview", ""),
        )

    console.print(table)
    console.print(f"[dim]Log en: {history_module.RUNS_PATH}[/dim]")


@app.command()
def serve(
    port: int = typer.Option(8080, "--port", help="Puerto HTTP para el dashboard."),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Proyecto por defecto al abrir."),
):
    """Inicia el dashboard web del orquestador en http://localhost:<port>"""
    import http.server
    import urllib.parse

    runs_path = history_module.RUNS_PATH

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            sel_project = params.get("project", [""])[0]

            runs = history_module.read_runs(last=200)
            html = build_html(runs, selected_project=sel_project)
            body = html.encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    url = f"http://localhost:{port}"
    console.print(f"[bold green]✓[/bold green] Dashboard en [cyan]{url}[/cyan]")
    console.print(f"[dim]  Log: {runs_path}[/dim]")
    console.print(f"[dim]  Ctrl+C para detener · auto-refresh cada 15s[/dim]")

    if not runs_path.exists():
        console.print("[yellow]ℹ[/yellow] Aún no hay runs registrados. Ejecutá un 'run' para ver datos.")

    server = http.server.HTTPServer(("localhost", port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard detenido.[/dim]")


if __name__ == "__main__":
    app()
