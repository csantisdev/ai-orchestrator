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
from orchestrator.config import ConfigError, get_pricing_table, load_config
from orchestrator.context import ContextNotFoundError
from orchestrator.costs import calculate_cost, check_budget
from orchestrator.dashboard import build_html
from orchestrator.db import get_run, init_db, projects_list
from orchestrator.index import ProjectNotFoundError
from orchestrator.paths import HOME_DIR, PROVIDERS
from orchestrator.providers.factory import build_provider

app = typer.Typer(
    name="ai-orchestrator",
    help="Orquestador local de agentes IA. Rutea tareas entre Claude, OpenAI y DeepSeek.",
    no_args_is_help=True,
)
console = Console(legacy_windows=False)


def _ensure_db() -> None:
    init_db()


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
    _ensure_db()
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
    _ensure_db()
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
    _ensure_db()
    try:
        index_module.remove_project(alias)
        console.print(f"[green]✓[/green] '{alias}' fue quitado del índice.")
    except ProjectNotFoundError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)


@app.command()
def rename(
    old_alias: str = typer.Argument(..., help="Alias actual del proyecto."),
    new_alias: str = typer.Argument(..., help="Nuevo alias."),
):
    """Renombra el alias de un proyecto en el índice y en todo el historial."""
    _ensure_db()
    from orchestrator.db import rename_project_in_db
    try:
        index_module.rename_project(old_alias, new_alias)
    except (ProjectNotFoundError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)
    counts = rename_project_in_db(old_alias, new_alias)
    console.print(f"[green]✓[/green] '{old_alias}' → '{new_alias}'")
    console.print(f"  {counts['runs']} run(s) y {counts['contexts']} contexto(s) actualizados.")


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
    _ensure_db()

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
    _rag_chunks: list[dict] = []
    try:
        from orchestrator.rag import retrieve_docs, retrieve_responses, build_context_block
        _doc_chunks = retrieve_docs(task, project)
        _resp_chunks = retrieve_responses(task, project)
        _rag_chunks = _doc_chunks + _resp_chunks
        rag_block = build_context_block(_doc_chunks, _resp_chunks)
        if rag_block:
            system_prompt += "\n\n" + rag_block
    except Exception:
        pass

    t0 = time.monotonic()
    with console.status(f"[bold cyan]Ejecutando en {decision.provider}..."):
        result = provider.complete(prompt=task, system=system_prompt)
    duration_ms = int((time.monotonic() - t0) * 1000)

    console.print()
    console.print(f"[bold green]── Respuesta ({result.provider}/{result.model}) ──[/bold green]")
    console.print(result.text)

    pricing = get_pricing_table(config)
    cost_usd = calculate_cost(result, pricing)

    run_id = history_module.log_run(
        project=project,
        task=task,
        result=result,
        duration_ms=duration_ms,
        routing_reason=decision.reason,
        cost_usd=cost_usd,
    )

    if run_id and _rag_chunks:
        try:
            from orchestrator.rag import persist_context_hits
            persist_context_hits(run_id, _rag_chunks)
        except Exception:
            pass

    from orchestrator.similarity import get_backend
    try:
        get_backend().upsert(run_id, task)
    except Exception:
        pass

    try:
        from orchestrator.rag import index_response
        index_response(run_id, project, task, result.text)
    except Exception:
        pass

    if cost_usd is not None:
        cache_note = ""
        if result.cache_read_tokens:
            cache_note = f"  [dim](cache hit: {result.cache_read_tokens} tokens)[/dim]"
        console.print(f"\n[dim]Costo estimado: ${cost_usd:.4f}{cache_note}[/dim]")

    budget = check_budget(project, config, daily_budget_usd=ctx.daily_budget_usd)
    if budget["warning"]:
        spent = budget["spent_usd"]
        limit = budget["limit_usd"]
        pct = round(budget["pct"] * 100)
        style = "red" if budget["over"] else "yellow"
        console.print(f"[{style}]⚠  Presupuesto diario: ${spent:.4f} / ${limit:.2f} ({pct}%)[/{style}]")


@app.command(name="sync-cc")
def sync_cc(
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Silenciar salida detallada."),
):
    """Importa sesiones de Claude Code al historial del orquestador."""
    _ensure_db()
    try:
        config = load_config()
    except ConfigError:
        config = {}

    from orchestrator.watcher import scan_and_import
    imported = scan_and_import(config, quiet=quiet)

    if not imported:
        if not quiet:
            console.print("[dim]No hay sesiones nuevas de Claude Code para importar.[/dim]")
        return

    table = Table(title=f"Claude Code — {len(imported)} sesión(es) importada(s)", show_lines=False)
    table.add_column("Proyecto", style="cyan")
    table.add_column("Session", style="dim")
    table.add_column("Modelo", style="dim")
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Out", justify="right")
    table.add_column("Costo", justify="right")
    table.add_column("Tarea", max_width=50)

    from orchestrator.dashboard import _fmt_cost
    for s in imported:
        table.add_row(
            s["project"],
            s["session_id"],
            s["model"].split("/")[-1],
            str(s["input_tokens"]),
            str(s["output_tokens"]),
            _fmt_cost(s["cost_usd"]),
            s["task_preview"],
        )

    console.print(table)


@app.command(name="sync-codex")
def sync_codex(
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Silenciar salida detallada."),
):
    """Importa sesiones de Codex (~/.codex/state_N.sqlite) al historial del orquestador."""
    _ensure_db()
    try:
        config = load_config()
    except ConfigError:
        config = {}

    from orchestrator.codex_watcher import scan_and_import as codex_import
    imported = codex_import(config, quiet=quiet)

    if not imported:
        if not quiet:
            console.print("[dim]No hay sesiones nuevas de Codex para importar.[/dim]")
        return

    table = Table(title=f"Codex — {len(imported)} sesión(es) importada(s)", show_lines=False)
    table.add_column("Proyecto", style="cyan")
    table.add_column("Thread", style="dim")
    table.add_column("Modelo", style="dim")
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Out", justify="right")
    table.add_column("Costo", justify="right")
    table.add_column("Tarea", max_width=50)

    from orchestrator.dashboard import _fmt_cost
    for s in imported:
        table.add_row(
            s["project"],
            s["session_id"],
            s["model"].split("/")[-1] if s["model"] else "—",
            str(s["input_tokens"]),
            str(s["output_tokens"]),
            _fmt_cost(s["cost_usd"]),
            s["task_preview"],
        )

    console.print(table)


@app.command(name="sync-git")
def sync_git(
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Silenciar salida detallada."),
):
    """Importa historial git de proyectos registrados como runs observables."""
    _ensure_db()
    from orchestrator.git_scanner import scan_and_import as git_import
    imported = git_import({}, quiet=quiet)

    if not imported:
        if not quiet:
            console.print("[dim]No hay commits nuevos para importar.[/dim]")
        return

    table = Table(title=f"Git — {len(imported)} commit(s) importado(s)", show_lines=False)
    table.add_column("Proyecto", style="cyan")
    table.add_column("Hash", style="dim")
    table.add_column("Autor", style="dim")
    table.add_column("Mensaje", max_width=60)
    for s in imported:
        table.add_row(s["project"], s["hash"], s["author"], s["subject"])
    console.print(table)


@app.command(name="create-context")
def create_context_cmd(
    project: str = typer.Option(..., "--project", "-p", help="Alias del proyecto."),
    title: str = typer.Option(..., "--title", "-t", help="Objetivo del contexto."),
    description: str = typer.Option("", "--description", "-d", help="Descripción extendida."),
    step: Optional[list[str]] = typer.Option(None, "--step", "-s", help="'Título:provider' — repetible. Ej: 'Diseñar schema:claude'"),
):
    """Crea un contexto de trabajo con pasos en la base de datos."""
    _ensure_db()
    from orchestrator.db import insert_context, insert_step, activate_first_step
    ctx_id = insert_context(project, title, description)
    console.print(f"[green]✓[/green] Contexto [bold]#{ctx_id}[/bold] creado → {title}")
    steps_created = []
    for i, s in enumerate(step or [], 1):
        parts = s.split(":", 1)
        step_title = parts[0].strip()
        provider = parts[1].strip() if len(parts) > 1 else ""
        sid = insert_step(ctx_id, i, step_title, provider=provider)
        badge = f" [{provider}]" if provider else ""
        console.print(f"  [cyan]paso {i}[/cyan]{badge} — {step_title} [dim](#{sid})[/dim]")
        steps_created.append(sid)
    if steps_created:
        activate_first_step(ctx_id)
        console.print(f"  [yellow]▶[/yellow] paso 1 marcado como [bold]in_progress[/bold]")
    else:
        console.print("  [yellow]sin pasos[/yellow] — añadí con --step 'Título:provider'")


@app.command(name="list-contexts")
def list_contexts_cmd(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filtrar por proyecto."),
):
    """Lista contextos de trabajo y sus pasos."""
    _ensure_db()
    from orchestrator.db import read_contexts_with_steps
    contexts = read_contexts_with_steps(project=project)
    if not contexts:
        msg = f"No hay contextos para '{project}'." if project else "No hay contextos registrados."
        console.print(f"[yellow]{msg}[/yellow]")
        return
    for ctx in contexts:
        sc = "green" if ctx["status"] == "active" else "dim"
        console.print(f"\n[bold]#{ctx['id']}[/bold] [{sc}]{ctx['status']}[/{sc}]  [cyan]{ctx['project']}[/cyan] — {ctx['title']}")
        if ctx.get("description"):
            console.print(f"  [dim]{ctx['description']}[/dim]")
        for s in ctx.get("steps", []):
            sc2 = {"pending": "dim", "in_progress": "yellow", "completed": "green"}.get(s["status"], "dim")
            badge = f" [{s['provider']}]" if s.get("provider") else ""
            console.print(f"  [{sc2}]{s['order_idx']}.[/{sc2}]{badge} {s['title']} — [{sc2}]{s['status']}[/{sc2}]")


@app.command(name="index-docs")
def index_docs(
    project: str = typer.Option(..., "--project", "-p", help="Alias del proyecto a indexar."),
    exclude: str = typer.Option("", "--exclude", "-e", help="Carpetas a excluir, separadas por coma. Ej: vendor,storage"),
    save: bool = typer.Option(False, "--save", help="Guardar exclusiones en context.yaml para próximas indexaciones."),
):
    """Indexa la documentación del proyecto en ChromaDB para búsqueda RAG."""
    _ensure_db()
    try:
        project_path = index_module.get_project_path(project)
    except ProjectNotFoundError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    extra = [d.strip() for d in exclude.split(",") if d.strip()] if exclude else []

    from orchestrator.rag import index_project
    from pathlib import Path as _Path
    with console.status(f"[bold cyan]Indexando {project}..."):
        n = index_project(project, _Path(project_path), extra_skip_dirs=extra or None)

    if n:
        console.print(f"[green]✓[/green] {n} chunks indexados para '{project}'")
    else:
        console.print(f"[yellow]⚠[/yellow] No se encontraron archivos para indexar en '{project_path}'")

    if save and extra:
        try:
            from orchestrator import context as _ctx_mod
            _ctx_mod.save_skip_dirs(_Path(project_path), extra)
            console.print(f"[green]✓[/green] Exclusiones guardadas en context.yaml: {extra}")
        except Exception as exc:
            console.print(f"[yellow]⚠[/yellow] No se pudo guardar en context.yaml: {exc}")


@app.command(name="import-context")
def import_context(
    project: str = typer.Option(..., "--project", "-p", help="Alias del proyecto."),
    agent: str = typer.Option("external", "--agent", "-a", help="Nombre del agente (claude-code, deepseek, openai, etc.)."),
    model: str = typer.Option("", "--model", "-m", help="Modelo usado por el agente."),
    task: str = typer.Option("", "--task", "-t", help="Tarea o prompt enviado al agente."),
    response: str = typer.Option("", "--response", "-r", help="Respuesta del agente."),
    no_index: bool = typer.Option(False, "--no-index", help="Omitir indexación RAG."),
):
    """Importa el contexto producido por un agente externo (DeepSeek, OpenAI, Claude, etc.)."""
    _ensure_db()

    if not task:
        task = typer.prompt("Tarea / Prompt enviado al agente")
    if not response:
        console.print("[dim]Pegá la respuesta del agente (Enter + Ctrl+D para finalizar):[/dim]")
        import sys
        lines = []
        try:
            for line in sys.stdin:
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        response = "".join(lines).strip()

    if not response:
        console.print("[red]✗[/red] La respuesta no puede estar vacía.")
        raise typer.Exit(code=1)

    from orchestrator.db import import_external_run
    from orchestrator.rag import index_response
    run_id = import_external_run(
        project=project,
        task=task,
        response=response,
        provider=agent,
        model=model,
        agent_label=agent,
    )
    console.print(f"[green]✓[/green] Contexto importado como run #{run_id} (proyecto: {project}, agente: {agent})")

    if not no_index:
        try:
            index_response(run_id, project, task, response)
            console.print(f"[green]✓[/green] Indexado en RAG para futuros runs")
        except Exception as exc:
            console.print(f"[yellow]⚠[/yellow] No se pudo indexar en RAG: {exc}")


@app.command(name="clear-imports")
def clear_imports_command(
    project: str = typer.Option(..., "--project", "-p", help="Alias del proyecto a limpiar."),
    provider: Optional[str] = typer.Option(None, "--provider", help="Filtrar por proveedor (claude-code, deepseek, openai, external). Sin valor elimina todos."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirmar eliminación sin prompt interactivo."),
):
    """Elimina runs importados de un proyecto de runs.db y ChromaDB responses."""
    _ensure_db()
    from orchestrator.db import delete_imported_runs
    from orchestrator.rag import purge_project_responses

    label = f"'{project}'" + (f" (provider: {provider})" if provider else " (todos los providers)")
    if not confirm:
        typer.confirm(f"¿Eliminar todos los runs importados de {label}?", abort=True)

    run_ids = delete_imported_runs(project, provider=provider)
    if not run_ids:
        console.print(f"[yellow]⚠[/yellow] No se encontraron runs para {label}")
        return

    console.print(f"[green]✓[/green] {len(run_ids)} runs eliminados de runs.db")

    if not provider:
        purged = purge_project_responses(project)
        console.print(f"[green]✓[/green] {purged} vectores eliminados de ChromaDB responses")
    else:
        # Purge solo los vectores de los run_ids eliminados
        try:
            from orchestrator.rag import _responses_collection
            col = _responses_collection()
            ids_to_del = [f"run_{rid}" for rid in run_ids]
            col.delete(ids=ids_to_del)
            console.print(f"[green]✓[/green] {len(ids_to_del)} vectores eliminados de ChromaDB responses")
        except Exception as exc:
            console.print(f"[yellow]⚠[/yellow] No se pudo limpiar ChromaDB: {exc}")


@app.command(name="history")
def history_command(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filtrar por proyecto."),
    last: int = typer.Option(20, "--last", "-n", help="Cantidad de runs a mostrar."),
):
    """Muestra el historial de runs en la terminal."""
    _ensure_db()
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
    table.add_column("Costo", justify="right")
    table.add_column("Tarea", max_width=50)

    PROV_STYLE = {"claude": "orange1", "deepseek": "green", "openai": "blue"}

    for r in reversed(runs):
        from orchestrator.dashboard import _fmt_cost, _fmt_ms, _fmt_tokens, _fmt_ts
        prov = r.get("provider", "?")
        style = PROV_STYLE.get(prov, "white")
        preview = r.get("task_preview") or r.get("task", "")
        table.add_row(
            _fmt_ts(r.get("ts", "")),
            r.get("project", "—"),
            f"[{style}]{prov}[/{style}]",
            r.get("model", "—").split("/")[-1],
            _fmt_ms(r.get("duration_ms")),
            _fmt_tokens(r.get("input_tokens"), r.get("output_tokens")),
            _fmt_cost(r.get("cost_usd")),
            (preview[:48] + "…") if len(preview) > 48 else preview,
        )

    console.print(table)
    console.print(f"[dim]DB en: {history_module.RUNS_PATH}[/dim]")


@app.command()
def serve(
    port: int = typer.Option(8080, "--port", help="Puerto HTTP para el dashboard."),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Proyecto por defecto al abrir."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Abrir en el browser al iniciar."),
):
    """Inicia el dashboard web interactivo en http://127.0.0.1:<port>"""
    import http.server
    import json as json_mod
    import queue
    import socket
    import socketserver
    import urllib.parse
    import webbrowser

    _ensure_db()

    try:
        config = load_config()
    except ConfigError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    from orchestrator import background as bg_module
    from orchestrator.sse import BUS

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def handle_error(self, request, client_address):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/favicon.ico":
                self._file(self._DOCS_IMG / "favicons" / "favicon.ico")
                return

            if path == "/robots.txt":
                self.send_response(204)
                self.end_headers()
                return

            if path in ("/static/docs-theme.css", "/static/docs-theme.js"):
                _fname = path.split("/")[-1]
                _ct = "text/css; charset=utf-8" if _fname.endswith(".css") else "text/javascript; charset=utf-8"
                _src = (self._DOCS_IMG.parent / _fname).resolve()
                if _src.exists():
                    body = _src.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", _ct)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()
                return

            if path.startswith("/static/img/"):
                rel = path[len("/static/img/"):].lstrip("/")
                target = (self._DOCS_IMG / rel).resolve()
                if not str(target).startswith(str(self._DOCS_IMG.resolve())):
                    self.send_response(403)
                    self.end_headers()
                    return
                self._file(target)
                return

            if path in ("/docs", "/mcp", "/security"):
                _doc_map = {"/docs": "index.html", "/mcp": "mcp.html", "/security": "security.html"}
                docs_html = self._DOCS_IMG.parent / _doc_map[path]
                try:
                    body = docs_html.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (FileNotFoundError, OSError):
                    self.send_response(404)
                    self.end_headers()
                return

            if path == "/events":
                self._handle_sse()
                return

            if path == "/pick-folder":
                try:
                    import sys as _sys
                    import subprocess as _sp
                    folder = None
                    if _sys.platform == "win32":
                        _ps = (
                            "Add-Type -AssemblyName System.Windows.Forms;"
                            "[System.Windows.Forms.Application]::EnableVisualStyles();"
                            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                            "$d.Description = 'Seleccionar carpeta del proyecto';"
                            "$d.RootFolder = [System.Environment+SpecialFolder]::MyComputer;"
                            "$d.ShowNewFolderButton = $false;"
                            "$h = New-Object System.Windows.Forms.Form;"
                            "$h.TopMost = $true; $h.Opacity = 0; $h.Show();"
                            "if ($d.ShowDialog($h) -eq 'OK') { Write-Output $d.SelectedPath };"
                            "$h.Close()"
                        )
                        _r = _sp.run(
                            ["powershell", "-NonInteractive", "-Command", _ps],
                            capture_output=True, text=True, timeout=120,
                            creationflags=0x08000000,
                        )
                        folder = _r.stdout.strip() or None
                    else:
                        import tkinter as _tk
                        from tkinter import filedialog as _fd
                        _root = _tk.Tk()
                        _root.withdraw()
                        _root.wm_attributes("-topmost", True)
                        folder = _fd.askdirectory(
                            parent=_root,
                            title="Seleccionar carpeta del proyecto",
                        ) or None
                        _root.destroy()
                    self._json({"path": folder})
                except Exception as exc:
                    self._json({"path": None, "error": str(exc)}, 500)
                return

            if path == "/inspect":
                try:
                    from orchestrator.db import read_inspector_data
                    from orchestrator.rag import chroma_stats
                    from orchestrator.tracer import span as _span
                    with _span("Inspector · SQLite"):
                        payload = read_inspector_data()
                    with _span("Inspector · ChromaDB"):
                        payload["chroma"] = chroma_stats()
                    try:
                        registered = set(index_module.list_projects().keys())
                    except Exception:
                        registered = set()
                    try:
                        from_runs = set(projects_list())
                    except Exception:
                        from_runs = set()
                    payload["registered_projects"] = sorted(registered)
                    payload["registered_project_index"] = index_module.list_projects()
                    payload["all_projects"] = sorted(registered | from_runs)
                    try:
                        from orchestrator.rates import get_current_rate
                        payload["rate_info"] = get_current_rate(config)
                    except Exception:
                        payload["rate_info"] = None
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                    return
                self._json(payload)
                return

            if path == "/metrics":
                try:
                    from orchestrator.db import _conn
                    conn = _conn()
                    # Costo y runs por proyecto
                    by_proj = conn.execute(
                        """SELECT project,
                                  COUNT(*) as runs,
                                  SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                                  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                                  COALESCE(SUM(cost_usd),0) as cost,
                                  COALESCE(SUM(input_tokens),0) as in_tok,
                                  COALESCE(SUM(output_tokens),0) as out_tok,
                                  COALESCE(AVG(duration_ms),0) as avg_ms
                           FROM runs GROUP BY project ORDER BY cost DESC LIMIT 30"""
                    ).fetchall()
                    # Costo por modelo
                    by_model = conn.execute(
                        """SELECT model,
                                  COUNT(*) as runs,
                                  COALESCE(SUM(cost_usd),0) as cost,
                                  COALESCE(AVG(duration_ms),0) as avg_ms
                           FROM runs WHERE model != '' GROUP BY model ORDER BY cost DESC LIMIT 20"""
                    ).fetchall()
                    # Costo por proveedor
                    by_prov = conn.execute(
                        """SELECT provider,
                                  COUNT(*) as runs,
                                  COALESCE(SUM(cost_usd),0) as cost
                           FROM runs GROUP BY provider ORDER BY cost DESC"""
                    ).fetchall()
                    # Distribución de ratings
                    ratings = conn.execute(
                        """SELECT COALESCE(rating,'sin-rating') as rating, COUNT(*) as cnt
                           FROM runs GROUP BY rating ORDER BY cnt DESC"""
                    ).fetchall()
                    # Costo diario últimos 14 días
                    daily = conn.execute(
                        """SELECT date(ts) as day, COALESCE(SUM(cost_usd),0) as cost, COUNT(*) as runs
                           FROM runs WHERE date(ts) >= date('now','-14 days')
                           GROUP BY day ORDER BY day"""
                    ).fetchall()
                    from orchestrator.rates import get_current_rate
                    rate_info = get_current_rate(config)
                    self._json({
                        "by_project": [dict(r) for r in by_proj],
                        "by_model":   [dict(r) for r in by_model],
                        "by_provider":[dict(r) for r in by_prov],
                        "ratings":    [dict(r) for r in ratings],
                        "daily":      [dict(r) for r in daily],
                        "rate":       rate_info,
                    })
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if path == "/preview-index":
                try:
                    _qp = urllib.parse.parse_qs(parsed.query)
                    proj = _qp.get("project", [""])[0].strip()
                    if not proj:
                        self._json({"error": "project required"}, 400)
                        return
                    proj_path = index_module.get_project_path(proj)
                    from orchestrator.rag import preview_index, _SKIP_DIRS
                    from pathlib import Path as _Path
                    stack = ""
                    saved_skip: list[str] = []
                    try:
                        ctx = context_module.load_context(_Path(proj_path))
                        stack = ctx.stack
                        saved_skip = ctx.skip_dirs
                    except Exception:
                        pass
                    folders = preview_index(_Path(proj_path), stack=stack, saved_skip=saved_skip)
                    self._json({
                        "project": proj,
                        "stack": stack,
                        "global_skip_dirs": sorted(_SKIP_DIRS),
                        "folders": folders,
                    })
                except ProjectNotFoundError:
                    self._json({"error": f"Proyecto no registrado: {proj}"}, 404)
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if path == "/contexts-html":
                params2 = urllib.parse.parse_qs(parsed.query)
                sel2 = params2.get("project", [""])[0]
                status2 = params2.get("status", [None])[0]
                from orchestrator.db import read_contexts_with_steps as _rcs
                ctxs = _rcs(project=sel2 or None, status=status2)
                from orchestrator.dashboard import _build_contexts_section
                frag = _build_contexts_section(ctxs).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(frag)))
                    self.end_headers()
                    self.wfile.write(frag)
                except (BrokenPipeError, ConnectionAbortedError, OSError):
                    pass
                return

            if path.startswith("/context/"):
                try:
                    ctx_id = int(path.split("/context/", 1)[-1].rstrip("/"))
                except ValueError:
                    self._json({"error": "invalid id"}, 400)
                    return
                from orchestrator.db import _conn as _db_conn, read_tool_calls_for_step, read_alignments_for_step
                conn2 = _db_conn()
                row2 = conn2.execute("SELECT * FROM contexts WHERE id=?", (ctx_id,)).fetchone()
                if row2 is None:
                    self._json({"error": "not found"}, 404)
                    return
                ctx_payload = dict(row2)
                steps2 = conn2.execute("SELECT * FROM steps WHERE context_id=? ORDER BY order_idx", (ctx_id,)).fetchall()
                ctx_payload["steps"] = []
                for s in steps2:
                    sd = dict(s)
                    sd["alignments"] = [dict(a) for a in read_alignments_for_step(s["id"])]
                    sd["tool_calls"] = [dict(tc) for tc in read_tool_calls_for_step(s["id"])]
                    ctx_payload["steps"].append(sd)
                self._json(ctx_payload)
                return

            if path == "/export-csv":
                params3 = urllib.parse.parse_qs(parsed.query)
                proj_csv = params3.get("project", [""])[0]
                model_csv = params3.get("model", [""])[0]
                import csv, io
                all_runs = history_module.read_runs(project=proj_csv or None, last=5000)
                out = io.StringIO()
                w = csv.writer(out)
                w.writerow(["id","ts","project","provider","model","status","duration_ms","input_tokens","output_tokens","cost_usd","cache_read_tokens","routing_reason","task_preview"])
                for r in all_runs:
                    m = str(r.get("model",""))
                    if model_csv and m.split("/")[-1] != model_csv:
                        continue
                    w.writerow([
                        r.get("id",""), r.get("ts",""), r.get("project",""),
                        r.get("provider",""), m, r.get("status",""),
                        r.get("duration_ms",""), r.get("input_tokens",""),
                        r.get("output_tokens",""), r.get("cost_usd",""),
                        r.get("cache_read_tokens",""), r.get("routing_reason",""),
                        r.get("task_preview",""),
                    ])
                csv_bytes = out.getvalue().encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="runs.csv"')
                    self.send_header("Content-Length", str(len(csv_bytes)))
                    self.end_headers()
                    self.wfile.write(csv_bytes)
                except (BrokenPipeError, ConnectionAbortedError, OSError):
                    pass
                return

            if path.startswith("/run/"):
                run_id_str = path.split("/run/", 1)[-1].rstrip("/")
                try:
                    rid = int(run_id_str)
                except ValueError:
                    self._json({"error": "invalid id"}, 400)
                    return
                row = get_run(rid)
                if row is None:
                    self._json({"error": "not found"}, 404)
                    return
                payload = dict(row)
                if row["step_id"]:
                    from orchestrator.db import read_tool_calls_for_step, read_alignments_for_step
                    payload["tool_calls"] = [dict(r) for r in read_tool_calls_for_step(row["step_id"])]
                    payload["alignments"] = [dict(r) for r in read_alignments_for_step(row["step_id"])]
                # context_hits — chunks RAG usados en este run
                try:
                    from orchestrator.db import _conn
                    _ch = _conn().execute(
                        "SELECT collection, source, chunk_idx, score FROM context_hits WHERE run_id=? ORDER BY score",
                        (rid,),
                    ).fetchall()
                    payload["context_hits"] = [dict(r) for r in _ch]
                except Exception:
                    payload["context_hits"] = []
                self._json(payload)
                return

            if path == "/clean-preview":
                try:
                    from orchestrator.db import _conn
                    from orchestrator.index import list_projects
                    from orchestrator.rag import chroma_stats
                    conn = _conn()
                    registered = set(list_projects().keys())
                    rows = conn.execute(
                        """SELECT project, provider, COUNT(*) as runs,
                                  COALESCE(SUM(cost_usd),0) as cost
                           FROM runs GROUP BY project, provider ORDER BY project, provider"""
                    ).fetchall()
                    projects_info = {}
                    for r in rows:
                        p = r["project"]
                        if p not in projects_info:
                            projects_info[p] = {"project": p, "registered": p in registered,
                                                "runs": 0, "cost": 0.0, "providers": []}
                        projects_info[p]["runs"] += r["runs"]
                        projects_info[p]["cost"] += r["cost"]
                        projects_info[p]["providers"].append(
                            {"provider": r["provider"], "runs": r["runs"]}
                        )
                    # Contextos por proyecto
                    ctx_rows = conn.execute(
                        """SELECT project, status, COUNT(*) as n FROM contexts
                           GROUP BY project, status"""
                    ).fetchall()
                    ctx_by_proj: dict = {}
                    for r in ctx_rows:
                        p = r["project"]
                        if p not in ctx_by_proj:
                            ctx_by_proj[p] = {"total": 0, "by_status": {}}
                        ctx_by_proj[p]["total"] += r["n"]
                        ctx_by_proj[p]["by_status"][r["status"]] = r["n"]
                    # ChromaDB stats
                    cs = chroma_stats()
                    self._json({
                        "projects": list(projects_info.values()),
                        "registered": sorted(registered),
                        "contexts_by_project": ctx_by_proj,
                        "chroma": cs,
                    })
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if path == "/integrations/status":
                try:
                    providers_cfg = config.get("providers", {})
                    providers_status = []
                    for name, cfg in providers_cfg.items():
                        providers_status.append({
                            "name": name,
                            "configured": bool(cfg.get("api_key", "").strip()),
                            "model": cfg.get("model", ""),
                        })
                    from orchestrator.rates import get_current_rate, get_bcentral_config
                    bc = get_bcentral_config(config)
                    rate_info = get_current_rate(config)
                    self._json({
                        "providers": providers_status,
                        "bcentral": {
                            "configured": bool(bc.get("user") and bc.get("pass")),
                            "user": bc.get("user", ""),
                            "rate": rate_info,
                        },
                    })
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if path == "/rates":
                try:
                    from orchestrator.rates import get_current_rate
                    rate_info = get_current_rate(config)
                    self._json(rate_info or {"rate": None, "error": "Sin datos ni credenciales"})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            params = urllib.parse.parse_qs(parsed.query)
            sel_project = params.get("project", [project or ""])[0]
            # Pre-filtrar en DB: si hay proyecto seleccionado, traer solo sus runs
            # Siempre traer todos los proyectos por separado para el selector
            runs_list = history_module.read_runs(project=sel_project or None, last=500)
            try:
                _registered = list(index_module.list_projects().keys())
            except Exception:
                _registered = []
            extra_projects = sorted(set(projects_list()) | set(_registered))
            html = build_html(runs_list, selected_project=sel_project, projects_extra=extra_projects)
            body = html.encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, OSError):
                pass

        def do_POST(self):
            if self.path == "/clean/unmapped":
                try:
                    from orchestrator.db import _conn, _write_lock
                    from orchestrator.index import list_projects
                    from orchestrator.rag import purge_project_responses
                    conn = _conn()
                    registered = set(list_projects().keys())
                    unmapped = [r["project"] for r in conn.execute(
                        "SELECT DISTINCT project FROM runs"
                    ).fetchall() if r["project"] not in registered]
                    total_deleted = 0
                    chroma_purged = 0
                    for proj in unmapped:
                        count = conn.execute(
                            "SELECT COUNT(*) FROM runs WHERE project=?", (proj,)
                        ).fetchone()[0]
                        with _write_lock:
                            conn.execute("DELETE FROM runs WHERE project=?", (proj,))
                            conn.commit()
                        total_deleted += count
                        try:
                            chroma_purged += purge_project_responses(proj)
                        except Exception:
                            pass
                    self._json({
                        "projects_cleaned": unmapped,
                        "runs_deleted": total_deleted,
                        "chroma_purged": chroma_purged,
                    })
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/purge-chroma-docs":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj = (body.get("project") or "").strip()
                    from orchestrator.rag import purge_project_docs
                    if proj:
                        purged = purge_project_docs(proj)
                        self._json({"project": proj, "purged": purged})
                    else:
                        # purgar todos los proyectos
                        from orchestrator.db import _conn
                        all_projs = [r["project"] for r in _conn().execute(
                            "SELECT DISTINCT project FROM chunks"
                        ).fetchall()]
                        total = 0
                        for p in all_projs:
                            total += purge_project_docs(p)
                        self._json({"purged": total, "projects": all_projs})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/purge-chroma-responses":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj = (body.get("project") or "").strip()
                    from orchestrator.rag import purge_project_responses
                    if proj:
                        purged = purge_project_responses(proj)
                        self._json({"project": proj, "purged": purged})
                    else:
                        from orchestrator.db import _conn
                        all_projs = [r["project"] for r in _conn().execute(
                            "SELECT DISTINCT project FROM runs"
                        ).fetchall()]
                        total = 0
                        for p in all_projs:
                            total += purge_project_responses(p)
                        self._json({"purged": total, "projects": all_projs})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/delete-contexts":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj   = (body.get("project") or "").strip()
                    status = (body.get("status") or "").strip()
                    from orchestrator.db import _conn, _write_lock
                    conn = _conn()
                    # Obtener context_ids a eliminar
                    q = "SELECT id FROM contexts WHERE 1=1"
                    params: list = []
                    if proj:
                        q += " AND project=?"; params.append(proj)
                    if status:
                        q += " AND status=?"; params.append(status)
                    ctx_ids = [r["id"] for r in conn.execute(q, params).fetchall()]
                    if not ctx_ids:
                        self._json({"deleted_contexts": 0, "deleted_steps": 0}); return
                    ph = ",".join("?" * len(ctx_ids))
                    with _write_lock:
                        step_count = conn.execute(
                            f"SELECT COUNT(*) FROM steps WHERE context_id IN ({ph})", ctx_ids
                        ).fetchone()[0]
                        conn.execute(f"DELETE FROM steps WHERE context_id IN ({ph})", ctx_ids)
                        conn.execute(f"DELETE FROM contexts WHERE id IN ({ph})", ctx_ids)
                        conn.commit()
                    self._json({
                        "deleted_contexts": len(ctx_ids),
                        "deleted_steps": step_count,
                        "project": proj or None,
                        "status": status or None,
                    })
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/clear-imports":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj = (body.get("project") or "").strip()
                    provider = (body.get("provider") or "").strip() or None
                    if not proj:
                        self._json({"error": "project es requerido"}, 400)
                        return
                    from orchestrator.db import delete_imported_runs
                    from orchestrator.rag import purge_project_responses, _responses_collection
                    from orchestrator.tracer import span as _tspan
                    with _tspan(f"clear-imports · {proj}", detail=provider or "todos"):
                        run_ids = delete_imported_runs(proj, provider=provider)
                        chroma_purged = 0
                        if run_ids:
                            if not provider:
                                chroma_purged = purge_project_responses(proj)
                            else:
                                try:
                                    col = _responses_collection()
                                    col.delete(ids=[f"run_{rid}" for rid in run_ids])
                                    chroma_purged = len(run_ids)
                                except Exception:
                                    pass
                    self._json({
                        "project": proj,
                        "provider": provider,
                        "runs_deleted": len(run_ids),
                        "chroma_purged": chroma_purged,
                    })
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/rate-run":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    rid = int(body.get("run_id", 0))
                    rating = (body.get("rating") or "").strip()
                    if not rid or rating not in ("useful", "wrong", "partial", ""):
                        self._json({"error": "run_id y rating (useful/wrong/partial) requeridos"}, 400)
                        return
                    from orchestrator.db import _conn, _write_lock
                    _c = _conn()
                    with _write_lock:
                        _c.execute(
                            "UPDATE runs SET rating=? WHERE id=?",
                            (rating or None, rid),
                        )
                        _c.commit()
                    self._json({"run_id": rid, "rating": rating or None})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/import-context":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj = (body.get("project") or "").strip()
                    task_text = (body.get("task") or "").strip()
                    response_text = (body.get("response") or "").strip()
                    if not proj or not task_text or not response_text:
                        self._json({"error": "project, task y response son requeridos"}, 400)
                        return
                    agent = (body.get("agent") or "external").strip() or "external"
                    model_name = (body.get("model") or "").strip()
                    from orchestrator.db import import_external_run
                    from orchestrator.rag import index_response as _idx_resp
                    from orchestrator.tracer import span as _tspan
                    run_id = None
                    indexed = False
                    with _tspan(f"import-context · {agent}", detail=proj):
                        run_id = import_external_run(
                            project=proj,
                            task=task_text,
                            response=response_text,
                            provider=agent,
                            model=model_name,
                            agent_label=agent,
                        )
                        try:
                            with _tspan(f"index-response · {proj}"):
                                _idx_resp(run_id, proj, task_text, response_text)
                            indexed = True
                        except Exception:
                            pass
                    self._json({"run_id": run_id, "project": proj, "indexed": indexed})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/sync-cc":
                try:
                    from orchestrator.watcher import scan_and_import
                    from orchestrator.tracer import span as _tspan
                    with _tspan("Sync Claude Code", detail="~/.claude/projects/"):
                        imported = scan_and_import(config, quiet=True)
                    self._json({"imported": len(imported), "sessions": imported})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/sync-git":
                try:
                    from orchestrator.git_scanner import scan_and_import as git_import
                    from orchestrator.tracer import span as _tspan
                    with _tspan("Sync Git", detail="proyectos registrados"):
                        imported = git_import({}, quiet=True)
                    self._json({"imported": len(imported), "commits": imported})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/sync-codex":
                try:
                    from orchestrator.codex_watcher import scan_and_import as codex_import
                    from orchestrator.tracer import span as _tspan
                    with _tspan("Sync Codex", detail="~/.codex/state_N.sqlite"):
                        imported = codex_import(config, quiet=True)
                    self._json({"imported": len(imported), "sessions": imported})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/rates/refresh":
                try:
                    from orchestrator.rates import refresh_rate
                    result = refresh_rate(config)
                    self._json(result)
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/config/bcentral":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    user = body.get("user", "").strip()
                    password = body.get("pass", "").strip()
                    if not user or not password:
                        self._json({"error": "user y pass son requeridos"}, 400)
                        return
                    from orchestrator.rates import save_bcentral_credentials, refresh_rate
                    save_bcentral_credentials(user, password)
                    # Recargar config y probar conexión inmediatamente
                    new_config = load_config()
                    result = refresh_rate(new_config)
                    self._json({"saved": True, **result})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/add-project":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    alias = body.get("alias", "").strip()
                    path = body.get("path", "").strip()
                    if not alias or not path:
                        self._json({"error": "alias y path son requeridos"}, 400)
                        return
                    from pathlib import Path as _Path
                    project_path = _Path(path).expanduser().resolve()
                    if not project_path.exists():
                        self._json({"error": f"Ruta no existe: {path}"}, 400)
                        return
                    index_module.add_project(alias, str(project_path))
                    self._json({"ok": True, "alias": alias, "path": str(project_path)})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/project/rename":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    old = body.get("old", "").strip()
                    new = body.get("new", "").strip()
                    if not old or not new:
                        self._json({"error": "old y new son requeridos"}, 400)
                        return
                    if old == new:
                        self._json({"error": "El nuevo alias es igual al actual"}, 400)
                        return
                    from orchestrator.db import rename_project_in_db
                    from orchestrator.index import ProjectNotFoundError as _PNF
                    try:
                        index_module.rename_project(old, new)
                    except (_PNF, ValueError) as exc:
                        self._json({"error": str(exc)}, 400)
                        return
                    counts = rename_project_in_db(old, new)
                    self._json({"ok": True, "old": old, "new": new, **counts})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/index-docs":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj = body.get("project", "").strip()
                    if not proj:
                        self._json({"error": "project required"}, 400)
                        return
                    extra_skip = body.get("extra_skip_dirs", []) or []
                    do_save = bool(body.get("save_skip_dirs", False))
                    proj_path = index_module.get_project_path(proj)
                    from orchestrator.rag import index_project
                    from orchestrator.tracer import span as _span
                    from pathlib import Path as _Path
                    if do_save and extra_skip:
                        try:
                            context_module.save_skip_dirs(_Path(proj_path), extra_skip)
                        except Exception:
                            pass
                    with _span(f"index-docs · {proj}"):
                        n = index_project(proj, _Path(proj_path), extra_skip_dirs=extra_skip or None)
                    self._json({"chunks": n, "project": proj})
                except ProjectNotFoundError:
                    self._json({"error": f"Proyecto no registrado: {proj}"}, 404)
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/create-context":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj = body.get("project", "").strip()
                    title = body.get("title", "").strip()
                    if not proj or not title:
                        self._json({"error": "project y title son requeridos"}, 400)
                        return
                    from orchestrator.db import insert_context, insert_step, activate_first_step
                    ctx_id = insert_context(proj, title, body.get("description", ""))
                    steps_out = []
                    for i, s in enumerate(body.get("steps", []) or [], 1):
                        step_title = (s.get("title", "") if isinstance(s, dict) else str(s)).strip()
                        provider = s.get("provider", "") if isinstance(s, dict) else ""
                        if step_title:
                            sid = insert_step(ctx_id, i, step_title, provider=provider)
                            steps_out.append({"id": sid, "order_idx": i, "title": step_title, "provider": provider, "status": "pending"})
                    if steps_out:
                        activate_first_step(ctx_id)
                        steps_out[0]["status"] = "in_progress"
                    self._json({"context_id": ctx_id, "project": proj, "title": title, "steps": steps_out}, 201)
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/advance-step":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    step_id = int(body.get("step_id", 0))
                    if not step_id:
                        self._json({"error": "step_id requerido"}, 400)
                        return
                    from orchestrator.mcp import _tool_advance_step
                    result = _tool_advance_step({"step_id": step_id, "notes": body.get("notes", "")})
                    from orchestrator.db import _conn as _db2
                    step_row = _db2().execute("SELECT context_id FROM steps WHERE id=?", (step_id,)).fetchone()
                    if step_row:
                        ctx_row = _db2().execute("SELECT project FROM contexts WHERE id=?", (step_row["context_id"],)).fetchone()
                        proj2 = ctx_row["project"] if ctx_row else ""
                        from orchestrator.db import read_contexts_with_steps as _rcs2
                        import json as _j
                        BUS.publish("ctx_updated", _j.dumps({"project": proj2, "contexts": _rcs2(project=proj2 or None)}, ensure_ascii=False, default=str))
                    self._json(result, 200)
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/skip-step":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    step_id = int(body.get("step_id", 0))
                    if not step_id:
                        self._json({"error": "step_id requerido"}, 400)
                        return
                    from orchestrator.mcp import _tool_skip_step
                    result = _tool_skip_step({"step_id": step_id, "reason": body.get("reason", "")})
                    from orchestrator.db import _conn as _db3
                    step_row = _db3().execute("SELECT context_id FROM steps WHERE id=?", (step_id,)).fetchone()
                    if step_row:
                        ctx_row = _db3().execute("SELECT project FROM contexts WHERE id=?", (step_row["context_id"],)).fetchone()
                        proj3 = ctx_row["project"] if ctx_row else ""
                        from orchestrator.db import read_contexts_with_steps as _rcs3
                        import json as _j2
                        BUS.publish("ctx_updated", _j2.dumps({"project": proj3, "contexts": _rcs3(project=proj3 or None)}, ensure_ascii=False, default=str))
                    self._json(result, 200)
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path.startswith("/context/") and self.path.endswith("/delete"):
                try:
                    ctx_id_str = self.path.split("/context/", 1)[-1].split("/delete")[0]
                    ctx_id = int(ctx_id_str)
                    from orchestrator.db import delete_context
                    result = delete_context(ctx_id)
                    from orchestrator.db import read_contexts_with_steps as _rcs_del
                    import json as _jd
                    BUS.publish("ctx_updated", _jd.dumps({"project": "", "contexts": []}, ensure_ascii=False))
                    self._json(result, 200)
                except (ValueError, IndexError) as exc:
                    self._json({"error": str(exc)}, 400)
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/run-doctor":
                try:
                    from pathlib import Path as _P
                    lines: list[dict] = []
                    n_issues = 0
                    n_warnings = 0

                    def _ok(msg):   lines.append({"text": msg, "ok": True})
                    def _warn(msg): lines.append({"text": msg, "warn": True}); nonlocal n_warnings; n_warnings += 1
                    def _fail(msg): lines.append({"text": msg, "fail": True}); nonlocal n_issues;   n_issues   += 1

                    # Config
                    try:
                        cfg = load_config()
                        _ok("config.yaml cargado")
                        for pname, pcfg in cfg.get("providers", {}).items():
                            key = pcfg.get("api_key", "").strip()
                            if not key or key.startswith("<"):
                                _fail(f"Provider '{pname}': api_key vacía o placeholder")
                            else:
                                _ok(f"Provider '{pname}': API key OK")
                    except ConfigError as exc:
                        _fail(f"config.yaml: {exc}")

                    # .mcp.json
                    mcp_f = _P(__file__).parent.parent / ".mcp.json"
                    if mcp_f.exists():
                        _ok(".mcp.json presente — MCP activo")
                    else:
                        _warn(".mcp.json no existe — ejecutá fix para crearlo")

                    # Codex MCP config
                    codex_f = _P(__file__).parent.parent / ".codex" / "config.toml"
                    if codex_f.exists():
                        try:
                            import tomllib as _tomllib2
                            codex_cfg = _tomllib2.loads(codex_f.read_text(encoding="utf-8"))
                            server = codex_cfg.get("mcp_servers", {}).get("ai_orchestrator", {})
                            command = str(server.get("command", "")).strip()
                            args = [str(a) for a in server.get("args", [])]
                            cwd_raw = str(server.get("cwd", _P(__file__).parent.parent)).strip()
                            cwd_path = _P(cwd_raw) if cwd_raw else _P(__file__).parent.parent
                            if not cwd_path.is_absolute():
                                cwd_path = (_P(__file__).parent.parent / cwd_path).resolve()
                            command_path = _P(command)
                            if command and not command_path.is_absolute():
                                command_path = (cwd_path / command_path).resolve()
                            if not server:
                                _warn(".codex/config.toml sin mcp_servers.ai_orchestrator")
                            elif command and not command_path.exists():
                                _warn(f".codex/config.toml apunta a Python inexistente: {command_path}")
                            elif "-m" in args and "orchestrator.mcp" in args:
                                _ok(".codex/config.toml presente — MCP activo en Codex")
                            else:
                                _warn(".codex/config.toml no apunta a orchestrator.mcp")
                        except Exception:
                            _warn("No se pudo leer .codex/config.toml")
                    else:
                        _warn(".codex/config.toml no existe — ejecutá fix para habilitar Codex")

                    # MCP global
                    gs_path = _P.home() / ".claude" / "settings.json"
                    if gs_path.exists():
                        import json as _j
                        try:
                            gs = _j.loads(gs_path.read_text(encoding="utf-8"))
                            if "ai-orchestrator" in gs.get("mcpServers", {}):
                                _ok("MCP registrado en settings.json global")
                            else:
                                _warn("MCP no registrado globalmente — usá fix --global-mcp")
                        except Exception:
                            _warn("No se pudo leer settings.json global")
                    else:
                        _warn("settings.json global no encontrado")

                    # Proyectos
                    try:
                        projs = index_module.list_projects()
                        _ok(f"{len(projs)} proyecto(s) registrado(s)")
                        for alias, path in projs.items():
                            pp = _P(path)
                            if not pp.exists():
                                _fail(f"{alias}: ruta no existe")
                            elif not context_module.context_exists(pp):
                                _warn(f"{alias}: sin context.yaml")
                            else:
                                _ok(f"{alias}: OK")
                    except Exception as exc:
                        _warn(f"Error leyendo índice: {exc}")

                    # DB + ChromaDB
                    from orchestrator.paths import HOME_DIR as _hd
                    if (_hd / "runs.db").exists():
                        size_kb = round((_hd / "runs.db").stat().st_size / 1024)
                        _ok(f"runs.db OK ({size_kb} KB)")
                    else:
                        _warn("runs.db no existe aún")
                    if (_hd / "chroma").exists():
                        _ok("ChromaDB OK")
                    else:
                        _warn("ChromaDB vacío — usá index-docs")

                    self._json({"lines": lines, "issues": n_issues, "warnings": n_warnings})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path == "/run-fix":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length)) if length else {}
                    from pathlib import Path as _P
                    import shutil as _shutil
                    import json as _j2

                    lines: list[dict] = []
                    fixed_count = 0

                    def _ok2(msg):   lines.append({"text": msg, "ok": True});
                    def _skip2(msg): lines.append({"text": msg, "info": True})
                    def _fail2(msg): lines.append({"text": msg, "fail": True})

                    # .mcp.json
                    mcp_f = _P(__file__).parent.parent / ".mcp.json"
                    mcp_ex = _P(__file__).parent.parent / ".mcp.json.example"
                    if mcp_f.exists():
                        _skip2(".mcp.json ya existe")
                    elif mcp_ex.exists():
                        _shutil.copy(mcp_ex, mcp_f)
                        _ok2(".mcp.json creado — reiniciá Claude Code para activarlo")
                        fixed_count += 1
                    else:
                        mcp_f.write_text(
                            '{\n  "mcpServers": {\n    "ai-orchestrator": {\n'
                            '      "command": ".venv/Scripts/python.exe",\n'
                            '      "args": ["-u", "-m", "orchestrator.mcp"],\n'
                            '      "cwd": "."\n'
                            '    }\n  }\n}\n', encoding="utf-8"
                        )
                        _ok2(".mcp.json creado desde cero")
                        fixed_count += 1

                    # .codex/config.toml
                    codex_f = _P(__file__).parent.parent / ".codex" / "config.toml"
                    if codex_f.exists():
                        _skip2(".codex/config.toml ya existe")
                    else:
                        project_root2 = _P(__file__).parent.parent
                        codex_f.parent.mkdir(parents=True, exist_ok=True)
                        abs_py2 = str((project_root2 / ".venv" / "Scripts" / "python.exe").resolve()).replace("\\", "\\\\")
                        cwd2 = str(project_root2.resolve()).replace("\\", "\\\\")
                        codex_f.write_text(
                            '[mcp_servers.ai_orchestrator]\n'
                            f'command = "{abs_py2}"\n'
                            'args = ["-u", "-m", "orchestrator.mcp"]\n'
                            f'cwd = "{cwd2}"\n'
                            'startup_timeout_sec = 15\n'
                            'tool_timeout_sec = 60\n'
                            'enabled = true\n'
                            'required = true\n'
                            'default_tools_approval_mode = "auto"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.get_context]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.list_steps]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.confirm_alignment]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.record_tool_call]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.advance_step]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.skip_step]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.create_context]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.add_step]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.update_context]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.import_agent_context]\napproval_mode = "approve"\n\n'
                            '[mcp_servers.ai_orchestrator.tools.update_step]\napproval_mode = "approve"\n',
                            encoding="utf-8",
                        )
                        _ok2(".codex/config.toml creado — abrí una sesión nueva de Codex")
                        fixed_count += 1

                    # MCP global
                    if body.get("global_mcp") or body.get("all"):
                        gs_path = _P.home() / ".claude" / "settings.json"
                        gs = {}
                        if gs_path.exists():
                            try: gs = _j2.loads(gs_path.read_text(encoding="utf-8"))
                            except Exception: pass
                        servers = gs.setdefault("mcpServers", {})
                        if "ai-orchestrator" in servers:
                            _skip2("MCP global ya registrado")
                        else:
                            abs_py = str((_P(__file__).parent.parent / ".venv" / "Scripts" / "python.exe").resolve())
                            servers["ai-orchestrator"] = {
                                "command": abs_py,
                                "args": ["-u", "-m", "orchestrator.mcp"],
                                "cwd": str(_P(__file__).parent.parent.resolve()),
                            }
                            gs_path.write_text(_j2.dumps(gs, indent=2, ensure_ascii=False), encoding="utf-8")
                            _ok2("MCP registrado en settings.json global")
                            fixed_count += 1

                    # context.yaml por proyecto
                    try:
                        projs = index_module.list_projects()
                        for alias, path in projs.items():
                            pp = _P(path)
                            if not pp.exists():
                                _skip2(f"{alias}: ruta no existe, omitido")
                                continue
                            if context_module.context_exists(pp):
                                _skip2(f"{alias}: context.yaml ya existe")
                            else:
                                try:
                                    context_module.create_default_context(
                                        project_path=pp, name=alias, stack="",
                                        description="", default_provider="claude"
                                    )
                                    _ok2(f"{alias}: context.yaml creado")
                                    fixed_count += 1
                                except Exception as exc2:
                                    _fail2(f"{alias}: error creando context.yaml — {exc2}")
                    except Exception as exc2:
                        _fail2(f"Error leyendo proyectos: {exc2}")

                    # Sync
                    if body.get("sync") or body.get("all"):
                        try:
                            cfg2 = {}
                            try: cfg2 = load_config()
                            except Exception: pass
                            from orchestrator.watcher import scan_and_import
                            imported_cc = scan_and_import(cfg2, quiet=True)
                            _ok2(f"sync-cc: {len(imported_cc)} sesión(es) importada(s)")
                            fixed_count += len(imported_cc)
                        except Exception as exc2:
                            _fail2(f"sync-cc: {exc2}")
                        try:
                            from orchestrator.git_scanner import scan_and_import as _gi
                            imported_g = _gi({}, quiet=True)
                            _ok2(f"sync-git: {len(imported_g)} commit(s) importado(s)")
                        except Exception as exc2:
                            _fail2(f"sync-git: {exc2}")
                        try:
                            from orchestrator.codex_watcher import scan_and_import as _ci
                            imported_cx = _ci(cfg2, quiet=True)
                            _ok2(f"sync-codex: {len(imported_cx)} sesión(es) importada(s)")
                        except Exception as exc2:
                            _fail2(f"sync-codex: {exc2}")

                    # Index RAG — siempre re-indexa (upsert es idempotente por ID
                    # determinístico project::path::chunk_idx; el guard count>0 fue
                    # eliminado porque dejaba índices desactualizados tras cambios de código).
                    if body.get("index") or body.get("all"):
                        try:
                            from orchestrator.rag import index_project as _idx
                            for alias, path in (index_module.list_projects() or {}).items():
                                pp = _P(path)
                                if not pp.exists(): continue
                                n = _idx(alias, pp)
                                _ok2(f"{alias}: {n} chunks indexados")
                                fixed_count += 1
                        except Exception as exc2:
                            _fail2(f"index: {exc2}")

                    self._json({"lines": lines, "fixed": fixed_count})
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
                return

            if self.path != "/run":
                self._json({"error": "not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json_mod.loads(self.rfile.read(length))
                proj = body.get("project", "").strip()
                task_text = body.get("task", "").strip()
                forced_model = body.get("model") or None
                if not proj or not task_text:
                    self._json({"error": "project and task are required"}, 400)
                    return
                run_id = bg_module.submit_run(
                    project=proj,
                    task=task_text,
                    config=config,
                    model=forced_model,
                )
                self._json({"run_id": run_id}, 202)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)

        def _handle_sse(self):
            try:
                self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except (OSError, AttributeError):
                pass
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            q = BUS.subscribe()
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                BUS.unsubscribe(q)

        def _json(self, data: dict, status: int = 200) -> None:
            body = json_mod.dumps(data, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, OSError):
                pass

        _MIME_TYPES = {".ico": "image/x-icon", ".png": "image/png", ".json": "application/json"}
        _DOCS_IMG = Path(__file__).parent.parent / "docs" / "img"

        def _file(self, file_path: Path) -> None:
            suffix = file_path.suffix.lower()
            content_type = self._MIME_TYPES.get(suffix, "application/octet-stream")
            try:
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
            except (BrokenPipeError, ConnectionAbortedError, OSError):
                pass

    class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    url = f"http://127.0.0.1:{port}"

    try:
        server = ThreadedServer(("127.0.0.1", port), DashboardHandler)
    except OSError as exc:
        console.print(f"[red]✗[/red] No se pudo iniciar en el puerto {port}: {exc}")
        console.print(f"[dim]  Intentá con otro puerto: ai-orchestrator serve --port 9000[/dim]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]✓[/bold green] Dashboard en [cyan]{url}[/cyan]")
    console.print(f"[dim]  DB: {HOME_DIR / 'runs.db'}[/dim]")
    console.print(f"[dim]  Ctrl+C para detener · SSE activo[/dim]")

    import threading as _threading
    def _prewarm_chroma():
        try:
            from orchestrator.rag import _get_client
            _get_client()
        except Exception:
            pass
    _threading.Thread(target=_prewarm_chroma, daemon=True).start()

    if open_browser:
        import webbrowser
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        console.print("\n[dim]Dashboard detenido.[/dim]")


@app.command()
def doctor(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Limitar diagnóstico a un proyecto específico."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Mostrar detalles extra en cada check."),
):
    """Diagnostica el estado de la configuración y detecta problemas pendientes."""
    _ensure_db()
    from pathlib import Path as _Path

    issues: list[str] = []
    warnings: list[str] = []

    def ok(msg: str) -> None:
        console.print(f"  [green]✓[/green] {msg}")

    def warn(msg: str, hint: str = "") -> None:
        warnings.append(msg)
        line = f"  [yellow]⚠[/yellow]  {msg}"
        if hint:
            line += f"  [dim]→ {hint}[/dim]"
        console.print(line)

    def fail(msg: str, hint: str = "") -> None:
        issues.append(msg)
        line = f"  [red]✗[/red] {msg}"
        if hint:
            line += f"  [dim]→ {hint}[/dim]"
        console.print(line)

    def info(msg: str) -> None:
        if verbose:
            console.print(f"  [dim]  {msg}[/dim]")

    # ── 1. Entorno Python ──────────────────────────────────────────────────
    console.print("\n[bold cyan]Entorno[/bold cyan]")
    import sys as _sys
    ok(f"Python {_sys.version.split()[0]}")

    venv_python = _Path(__file__).parent.parent / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = _Path(__file__).parent.parent / ".venv" / "bin" / "python"
    if venv_python.exists():
        ok(f".venv encontrado en {venv_python.parent.parent}")
    else:
        warn(".venv no detectado en el proyecto", "Ejecutá: python -m venv .venv && pip install -e .")

    # ── 2. Archivos globales ───────────────────────────────────────────────
    console.print("\n[bold cyan]Configuración global[/bold cyan]")
    info(f"HOME_DIR: {HOME_DIR}")

    if HOME_DIR.exists():
        ok(f"Directorio global existe: {HOME_DIR}")
    else:
        fail(f"Directorio global no existe: {HOME_DIR}", "Ejecutá cualquier comando para crearlo")

    config_path = HOME_DIR / "config.yaml"
    try:
        config = load_config()
        ok(f"config.yaml cargado")
        providers_cfg = config.get("providers", {})
        for pname, pcfg in providers_cfg.items():
            key = pcfg.get("api_key", "").strip()
            if not key or key.startswith("<"):
                fail(f"Provider '{pname}': api_key vacía o placeholder", f"Completá config.yaml → providers.{pname}.api_key")
            else:
                masked = key[:8] + "…" + key[-4:]
                ok(f"Provider '{pname}': API key configurada [{masked}]")
                info(f"  modelo: {pcfg.get('model', '—')}")
    except ConfigError as exc:
        fail(f"config.yaml: {exc}", "Copiá config.example.yaml → ~/.ai-orchestrator/config.yaml")
        config = {}

    index_path = HOME_DIR / "index.yaml"
    if index_path.exists():
        projects = index_module.list_projects()
        ok(f"index.yaml: {len(projects)} proyecto(s) registrado(s)")
    else:
        warn("index.yaml no existe aún", "Se creará al registrar el primer proyecto con 'add'")
        projects = {}

    db_path = HOME_DIR / "runs.db"
    if db_path.exists():
        size_kb = round(db_path.stat().st_size / 1024)
        ok(f"runs.db existe ({size_kb} KB)")
    else:
        warn("runs.db no existe", "Se creará automáticamente al usar el orquestador")

    chroma_path = HOME_DIR / "chroma"
    if chroma_path.exists():
        ok(f"ChromaDB existe: {chroma_path}")
    else:
        warn("ChromaDB vacío", "Se creará al indexar el primer proyecto con 'index-docs'")

    # ── 3. Integración Claude Code / MCP ──────────────────────────────────
    console.print("\n[bold cyan]Integración Claude Code / MCP[/bold cyan]")
    project_root = _Path(__file__).parent.parent
    mcp_json = project_root / ".mcp.json"
    mcp_example = project_root / ".mcp.json.example"

    if mcp_json.exists():
        ok(f".mcp.json presente → MCP activo al abrir desde {project_root.name}/")
    else:
        fail(".mcp.json no existe",
             "Ejecutá: ai-orchestrator fix  (lo crea automáticamente desde .mcp.json.example)")

    codex_config = project_root / ".codex" / "config.toml"
    if codex_config.exists():
        try:
            import tomllib as _tomllib
            codex_cfg = _tomllib.loads(codex_config.read_text(encoding="utf-8"))
            server = codex_cfg.get("mcp_servers", {}).get("ai_orchestrator", {})
            command = str(server.get("command", "")).strip()
            args = [str(a) for a in server.get("args", [])]
            cwd_raw = str(server.get("cwd", project_root)).strip() or str(project_root)
            cwd_path = _Path(cwd_raw)
            if not cwd_path.is_absolute():
                cwd_path = (project_root / cwd_path).resolve()
            command_path = _Path(command)
            if command and not command_path.is_absolute():
                command_path = (cwd_path / command_path).resolve()

            if not server:
                warn(".codex/config.toml no define mcp_servers.ai_orchestrator",
                     "Ejecutá: ai-orchestrator fix para regenerar la configuración local de Codex")
            elif command and not command_path.exists():
                warn(f".codex/config.toml apunta a Python inexistente: {command_path}",
                     "Ejecutá: ai-orchestrator fix para recrearlo con la ruta del .venv")
            elif "-m" in args and "orchestrator.mcp" in args:
                ok(".codex/config.toml presente → MCP disponible para Codex")
            else:
                warn(".codex/config.toml no apunta a orchestrator.mcp",
                     "Ejecutá: ai-orchestrator fix para corregir args del MCP")
        except Exception:
            warn("No se pudo leer .codex/config.toml",
                 "Ejecutá: ai-orchestrator fix para recrearlo")
    else:
        warn(".codex/config.toml no existe",
             "Ejecutá: ai-orchestrator fix para habilitar el MCP en Codex")

    global_settings = _Path.home() / ".claude" / "settings.json"
    if global_settings.exists():
        import json as _json
        try:
            gs = _json.loads(global_settings.read_text(encoding="utf-8"))
            if "mcpServers" in gs and "ai-orchestrator" in gs["mcpServers"]:
                ok("MCP registrado en ~/.claude/settings.json global")
            else:
                warn("MCP no está en ~/.claude/settings.json global",
                     "Con .mcp.json sólo carga cuando el working dir es el proyecto; 'fix --global-mcp' lo agrega globalmente")
        except Exception:
            warn("No se pudo leer ~/.claude/settings.json")
    else:
        warn("~/.claude/settings.json no encontrado")

    # ── 4. Proyectos ──────────────────────────────────────────────────────
    console.print("\n[bold cyan]Proyectos registrados[/bold cyan]")
    if not projects:
        warn("No hay proyectos registrados", "Usá 'add <alias> --path <ruta>'")
    else:
        from rich.markup import escape as _esc
        filter_alias = project
        for alias, path in sorted(projects.items()):
            if filter_alias and alias != filter_alias:
                continue
            proj_path = _Path(path)
            a = _esc(alias)
            if not proj_path.exists():
                fail(f"[{a}] ruta no existe: {path}", "Actualizá o eliminá con 'remove'")
                continue

            ok(f"[bold]{a}[/bold]  {path}")

            # context.yaml
            has_ctx = context_module.context_exists(proj_path)
            if has_ctx:
                info(f"  context.yaml ✓")
            else:
                warn(f"  {a}: sin context.yaml", "Ejecutá: ai-orchestrator fix  (o 'add' de nuevo)")

            # Indexado en ChromaDB
            if chroma_path.exists():
                try:
                    from orchestrator.rag import chroma_stats
                    stats = chroma_stats()
                    docs_count = stats.get("docs", {}).get("by_project", {}).get(alias, 0)
                    resp_count = stats.get("responses", {}).get("by_project", {}).get(alias, 0)
                    if docs_count > 0:
                        info(f"  RAG docs: {docs_count} chunks")
                    else:
                        warn(f"  {a}: no indexado en ChromaDB docs", f"Ejecutá: ai-orchestrator fix  (o 'index-docs -p {alias}')")
                    if resp_count > 0:
                        info(f"  RAG responses: {resp_count} vectores")
                except Exception:
                    pass

    # ── 5. Resumen ─────────────────────────────────────────────────────────
    console.print()
    if not issues and not warnings:
        console.print("[bold green]✓ Todo en orden — el orquestador está listo para usar.[/bold green]")
    else:
        if issues:
            console.print(f"[bold red]{len(issues)} problema(s) crítico(s)[/bold red]  |  "
                          f"[yellow]{len(warnings)} advertencia(s)[/yellow]")
            console.print("[dim]Ejecutá [bold]ai-orchestrator fix[/bold] para aplicar correcciones automáticas.[/dim]")
        else:
            console.print(f"[green]Sin errores críticos[/green]  |  [yellow]{len(warnings)} advertencia(s)[/yellow]")
            console.print("[dim]Ejecutá [bold]ai-orchestrator fix[/bold] para resolver advertencias automáticamente.[/dim]")


@app.command(name="fix")
def fix_command(
    global_mcp: bool = typer.Option(False, "--global-mcp", help="Registrar el MCP en ~/.claude/settings.json global."),
    sync: bool = typer.Option(False, "--sync", help="Ejecutar sync-cc y sync-git después de corregir."),
    index: bool = typer.Option(False, "--index", help="Indexar en ChromaDB los proyectos sin chunks."),
    all_fixes: bool = typer.Option(False, "--all", help="Aplicar todas las mejoras automáticas disponibles."),
):
    """Aplica mejoras automáticas detectadas por 'doctor'."""
    _ensure_db()
    from pathlib import Path as _Path
    import json as _json

    fixed: list[str] = []
    skipped: list[str] = []

    def did(msg: str) -> None:
        fixed.append(msg)
        console.print(f"  [green]✓[/green] {msg}")

    def skip(msg: str) -> None:
        skipped.append(msg)
        console.print(f"  [dim]–[/dim] {msg}")

    def fail(msg: str) -> None:
        console.print(f"  [red]✗[/red] {msg}")

    # ── 1. .mcp.json ──────────────────────────────────────────────────────
    console.print("\n[bold cyan]MCP[/bold cyan]")
    project_root = _Path(__file__).parent.parent
    mcp_json = project_root / ".mcp.json"
    mcp_example = project_root / ".mcp.json.example"

    if mcp_json.exists():
        skip(".mcp.json ya existe")
    elif mcp_example.exists():
        import shutil
        shutil.copy(mcp_example, mcp_json)
        did(f".mcp.json creado desde .mcp.json.example (reiniciá Claude Code para activarlo)")
    else:
        mcp_json.write_text(
            '{\n  "mcpServers": {\n    "ai-orchestrator": {\n'
            '      "command": ".venv/Scripts/python.exe",\n'
            '      "args": ["-u", "-m", "orchestrator.mcp"],\n'
            '      "cwd": "."\n'
            '    }\n  }\n}\n',
            encoding="utf-8",
        )
        did(".mcp.json creado (reiniciá Claude Code para activarlo)")

    codex_config = project_root / ".codex" / "config.toml"
    if codex_config.exists():
        skip(".codex/config.toml ya existe")
    else:
        codex_config.parent.mkdir(parents=True, exist_ok=True)
        abs_python = str((project_root / ".venv" / "Scripts" / "python.exe").resolve())
        codex_config.write_text(
            '[mcp_servers.ai_orchestrator]\n'
            f'command = "{abs_python.replace("\\", "\\\\")}"\n'
            'args = ["-u", "-m", "orchestrator.mcp"]\n'
            f'cwd = "{str(project_root.resolve()).replace("\\", "\\\\")}"\n'
            'startup_timeout_sec = 15\n'
            'tool_timeout_sec = 60\n'
            'enabled = true\n'
            'required = true\n'
            'default_tools_approval_mode = "auto"\n\n'
            '[mcp_servers.ai_orchestrator.tools.get_context]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.list_steps]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.confirm_alignment]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.record_tool_call]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.advance_step]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.skip_step]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.create_context]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.add_step]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.update_context]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.import_agent_context]\napproval_mode = "approve"\n\n'
            '[mcp_servers.ai_orchestrator.tools.update_step]\napproval_mode = "approve"\n',
            encoding="utf-8",
        )
        did(".codex/config.toml creado (abrí una sesión nueva de Codex para activarlo)")

    # ── 2. MCP global en ~/.claude/settings.json ──────────────────────────
    if global_mcp or all_fixes:
        console.print("\n[bold cyan]MCP global[/bold cyan]")
        global_settings = _Path.home() / ".claude" / "settings.json"
        abs_python = str((project_root / ".venv" / "Scripts" / "python.exe").resolve())
        mcp_entry = {
            "command": abs_python,
            "args": ["-u", "-m", "orchestrator.mcp"],
            "cwd": str(project_root.resolve()),
        }
        if global_settings.exists():
            try:
                gs = _json.loads(global_settings.read_text(encoding="utf-8"))
            except Exception:
                gs = {}
        else:
            gs = {}
        servers = gs.setdefault("mcpServers", {})
        if "ai-orchestrator" in servers:
            skip("MCP ya registrado en ~/.claude/settings.json global")
        else:
            servers["ai-orchestrator"] = mcp_entry
            global_settings.write_text(_json.dumps(gs, indent=2, ensure_ascii=False), encoding="utf-8")
            did("MCP registrado en ~/.claude/settings.json global (disponible en todos los proyectos)")

    # ── 3. context.yaml para proyectos sin él ─────────────────────────────
    console.print("\n[bold cyan]Proyectos[/bold cyan]")
    try:
        projects = index_module.list_projects()
    except Exception:
        projects = {}

    if not projects:
        skip("No hay proyectos registrados — nada que corregir")
    else:
        from rich.markup import escape as _esc2
        for alias, path in sorted(projects.items()):
            proj_path = _Path(path)
            a = _esc2(alias)
            if not proj_path.exists():
                skip(f"{a}: ruta no existe, omitido")
                continue
            if context_module.context_exists(proj_path):
                skip(f"{a}: context.yaml ya existe")
            else:
                try:
                    ctx_path = context_module.create_default_context(
                        project_path=proj_path,
                        name=alias,
                        stack="",
                        description="",
                        default_provider="claude",
                    )
                    did(f"{a}: context.yaml creado en {ctx_path}")
                except Exception as exc:
                    fail(f"{a}: no se pudo crear context.yaml: {exc}")

    # ── 4. Re-indexar proyectos en ChromaDB ───────────────────────────────
    # Siempre re-indexa: upsert con IDs determinísticos es idempotente y
    # garantiza que el índice refleje el estado actual del código.
    # El guard count>0 fue eliminado porque dejaba índices desactualizados.
    if index or all_fixes:
        console.print("\n[bold cyan]Indexación RAG[/bold cyan]")
        from rich.markup import escape as _esc3
        for alias, path in sorted(projects.items()):
            proj_path = _Path(path)
            a3 = _esc3(alias)
            if not proj_path.exists():
                continue
            try:
                from orchestrator.rag import index_project
                with console.status(f"[dim]Indexando {alias}...[/dim]"):
                    n = index_project(alias, proj_path)
                did(f"{a3}: {n} chunks indexados en ChromaDB")
            except Exception as exc:
                fail(f"{a3}: error al indexar: {exc}")

    # ── 5. Sync Claude Code + Git ──────────────────────────────────────────
    if sync or all_fixes:
        console.print("\n[bold cyan]Sincronización[/bold cyan]")
        try:
            try:
                config = load_config()
            except ConfigError:
                config = {}
            from orchestrator.watcher import scan_and_import
            imported_cc = scan_and_import(config, quiet=True)
            if imported_cc:
                did(f"sync-cc: {len(imported_cc)} sesión(es) de Claude Code importada(s)")
            else:
                skip("sync-cc: sin sesiones nuevas")
        except Exception as exc:
            fail(f"sync-cc falló: {exc}")

        try:
            from orchestrator.git_scanner import scan_and_import as git_import
            imported_git = git_import({}, quiet=True)
            if imported_git:
                did(f"sync-git: {len(imported_git)} commit(s) importado(s)")
            else:
                skip("sync-git: sin commits nuevos")
        except Exception as exc:
            fail(f"sync-git falló: {exc}")

        try:
            from orchestrator.codex_watcher import scan_and_import as codex_import
            imported_codex = codex_import(config, quiet=True)
            if imported_codex:
                did(f"sync-codex: {len(imported_codex)} sesión(es) de Codex importada(s)")
            else:
                skip("sync-codex: sin sesiones nuevas")
        except Exception as exc:
            fail(f"sync-codex falló: {exc}")

    # ── Resumen ────────────────────────────────────────────────────────────
    console.print()
    if fixed:
        console.print(f"[bold green]{len(fixed)} mejora(s) aplicada(s).[/bold green]")
        for f in fixed:
            console.print(f"  [green]·[/green] {f}")
    else:
        console.print("[green]No había nada que corregir — el sistema ya estaba en orden.[/green]")

    if not (global_mcp or all_fixes):
        console.print("\n[dim]Opciones adicionales:[/dim]")
        console.print("[dim]  --global-mcp   Registrar MCP en ~/.claude/settings.json (todos los proyectos)[/dim]")
        console.print("[dim]  --sync         Sincronizar Claude Code + Git[/dim]")
        console.print("[dim]  --index        Indexar proyectos en ChromaDB RAG[/dim]")
        console.print("[dim]  --all          Aplicar todas las mejoras anteriores[/dim]")


if __name__ == "__main__":
    app()
