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

    claude_md = context_module.create_claude_md(project_path, alias)
    if claude_md:
        console.print(f"[green]✓[/green] CLAUDE.md generado en {claude_md}")
    else:
        console.print(f"[yellow]ℹ[/yellow] CLAUDE.md ya existe en {project_path}, sin cambios.")

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
        model_hint = f"/{decision.model}" if decision.model else ""
        console.print(f"[{style}]→ Proveedor elegido: {decision.provider}{model_hint}[/{style}]  ({decision.reason})")

    try:
        provider = build_provider(config, decision.provider)
    except (ConfigError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    if research:
        provider.model = RESEARCH_MODEL
    elif decision.model:
        provider.model = decision.model

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
    _ensure_db()

    try:
        config = load_config()
    except ConfigError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    from orchestrator.server import serve as _serve
    _serve(port=port, project=project, open_browser=open_browser, config=config)


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
