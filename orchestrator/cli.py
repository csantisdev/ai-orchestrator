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
    try:
        from orchestrator.rag import retrieve_docs, retrieve_responses, build_context_block
        rag_block = build_context_block(
            retrieve_docs(task, project),
            retrieve_responses(task, project),
        )
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


@app.command(name="create-context")
def create_context_cmd(
    project: str = typer.Option(..., "--project", "-p", help="Alias del proyecto."),
    title: str = typer.Option(..., "--title", "-t", help="Objetivo del contexto."),
    description: str = typer.Option("", "--description", "-d", help="Descripción extendida."),
    step: Optional[list[str]] = typer.Option(None, "--step", "-s", help="'Título:provider' — repetible. Ej: 'Diseñar schema:claude'"),
):
    """Crea un contexto de trabajo con pasos en la base de datos."""
    _ensure_db()
    from orchestrator.db import insert_context, insert_step
    ctx_id = insert_context(project, title, description)
    console.print(f"[green]✓[/green] Contexto [bold]#{ctx_id}[/bold] creado → {title}")
    for i, s in enumerate(step or [], 1):
        parts = s.split(":", 1)
        step_title = parts[0].strip()
        provider = parts[1].strip() if len(parts) > 1 else ""
        sid = insert_step(ctx_id, i, step_title, provider=provider)
        badge = f" [{provider}]" if provider else ""
        console.print(f"  [cyan]paso {i}[/cyan]{badge} — {step_title} [dim](#{sid})[/dim]")
    if not step:
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
):
    """Indexa la documentación del proyecto en ChromaDB para búsqueda RAG."""
    _ensure_db()
    try:
        project_path = index_module.get_project_path(project)
    except ProjectNotFoundError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    from orchestrator.rag import index_project
    from pathlib import Path as _Path
    with console.status(f"[bold cyan]Indexando {project}..."):
        n = index_project(project, _Path(project_path))

    if n:
        console.print(f"[green]✓[/green] {n} chunks indexados para '{project}'")
    else:
        console.print(f"[yellow]⚠[/yellow] No se encontraron archivos para indexar en '{project_path}'")


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

            if path in ("/favicon.ico", "/robots.txt"):
                self.send_response(204)
                self.end_headers()
                return

            if path == "/events":
                self._handle_sse()
                return

            if path == "/inspect":
                import concurrent.futures
                from orchestrator.db import read_inspector_data
                from orchestrator.rag import chroma_stats
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                    db_fut = ex.submit(read_inspector_data)
                    ch_fut = ex.submit(chroma_stats)
                    payload = db_fut.result()
                    payload["chroma"] = ch_fut.result()
                try:
                    payload["registered_projects"] = sorted(index_module.list_projects().keys())
                except Exception:
                    payload["registered_projects"] = []
                self._json(payload)
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
                self._json(payload)
                return

            params = urllib.parse.parse_qs(parsed.query)
            sel_project = params.get("project", [project or ""])[0]
            runs_list = history_module.read_runs(last=200)
            extra_projects = projects_list()
            from orchestrator.db import read_contexts_with_steps
            contexts = read_contexts_with_steps(project=sel_project or None)
            html = build_html(runs_list, selected_project=sel_project, projects_extra=extra_projects, contexts=contexts)
            body = html.encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, OSError):
                pass

        def do_POST(self):
            if self.path == "/index-docs":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json_mod.loads(self.rfile.read(length))
                    proj = body.get("project", "").strip()
                    if not proj:
                        self._json({"error": "project required"}, 400)
                        return
                    proj_path = index_module.get_project_path(proj)
                    from orchestrator.rag import index_project
                    from pathlib import Path as _Path
                    n = index_project(proj, _Path(proj_path))
                    self._json({"chunks": n, "project": proj})
                except ProjectNotFoundError:
                    self._json({"error": f"Proyecto no registrado: {proj}"}, 404)
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


if __name__ == "__main__":
    app()
