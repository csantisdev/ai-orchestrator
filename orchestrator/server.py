"""Servidor HTTP del dashboard — DashboardHandler + ThreadedServer."""

from __future__ import annotations

import http.server
import json as json_mod
import queue
import socket
import socketserver
import sys
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Optional

from rich.console import Console

from orchestrator.paths import HOME_DIR

_console = Console(legacy_windows=False)


def serve(port: int, project: Optional[str], open_browser: bool, config: dict) -> None:
    """Servidor HTTP del dashboard en http://127.0.0.1:<port>."""
    import threading as _threading
    from orchestrator import background as bg_module
    from orchestrator import context as context_module
    from orchestrator import history as history_module
    from orchestrator import index as index_module
    from orchestrator.config import load_config, ConfigError
    from orchestrator.db import get_run
    from orchestrator.history import projects_list
    from orchestrator.dashboard import build_html
    from orchestrator.index import ProjectNotFoundError
    from orchestrator.sse import BUS

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def handle_error(self, request, client_address):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path.startswith("/run/"):
                return self._get_run(parsed)
            if path.startswith("/context/") and not path.endswith("/delete"):
                return self._get_context(parsed)
            if path.startswith("/static/img/"):
                return self._get_static_img(parsed)
            handler = {
                "/favicon.ico":              self._get_favicon,
                "/robots.txt":               self._get_robots,
                "/static/docs-theme.css":    self._get_static_theme,
                "/static/docs-theme.js":     self._get_static_theme,
                "/docs":                     self._get_docs,
                "/mcp":                      self._get_docs,
                "/security":                 self._get_docs,
                "/events":                   self._get_events,
                "/pick-folder":              self._get_pick_folder,
                "/inspect":                  self._get_inspect,
                "/metrics":                  self._get_metrics,
                "/preview-index":            self._get_preview_index,
                "/contexts-html":            self._get_contexts_html,
                "/clean-preview":            self._get_clean_preview,
                "/integrations/status":      self._get_integrations_status,
                "/rates":                    self._get_rates,
                "/pricing":                  self._get_pricing,
                "/models":                   self._get_models,
                "/agents":                   self._get_agents,
                "/export-csv":              self._get_export_csv,
            }.get(path, self._get_dashboard)
            handler(parsed)

        def _get_favicon(self, parsed):
            self._file(self._DOCS_IMG / "favicons" / "favicon.ico")
            return

        def _get_robots(self, parsed):
            self.send_response(204)
            self.end_headers()
            return

        def _get_static_theme(self, parsed):
            path = parsed.path
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

        def _get_static_img(self, parsed):
            path = parsed.path
            rel = path[len("/static/img/"):].lstrip("/")
            target = (self._DOCS_IMG / rel).resolve()
            if not str(target).startswith(str(self._DOCS_IMG.resolve())):
                self.send_response(403)
                self.end_headers()
                return
            self._file(target)
            return

        def _get_docs(self, parsed):
            path = parsed.path
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

        def _get_events(self, parsed):
            self._handle_sse()
            return

        def _get_pick_folder(self, parsed):
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

        def _get_inspect(self, parsed):
            try:
                from orchestrator.db import read_inspector_data
                from orchestrator.rag import chroma_stats_isolated
                from orchestrator.tracer import span as _span
                with _span("Inspector · SQLite"):
                    payload = read_inspector_data()
                with _span("Inspector · ChromaDB"):
                    payload["chroma"] = chroma_stats_isolated()
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

        def _get_metrics(self, parsed):
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

        def _get_preview_index(self, parsed):
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

        def _get_contexts_html(self, parsed):
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

        def _get_context(self, parsed):
            path = parsed.path
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

        def _get_export_csv(self, parsed):
            params3 = urllib.parse.parse_qs(parsed.query)
            proj_csv = params3.get("project", [""])[0]
            model_csv = params3.get("model", [""])[0]
            import csv, io
            all_runs = history_module.read_runs(project=proj_csv or None, last=5000)
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["id","ts","project","provider","model","status","duration_ms","input_tokens","output_tokens","cost_usd","cache_read_tokens","routing_reason","task_preview","task","response"])
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
                    r.get("task_preview",""), r.get("task",""), r.get("response",""),
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

        def _get_run(self, parsed):
            path = parsed.path
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

        def _get_clean_preview(self, parsed):
            try:
                from orchestrator.db import _conn
                from orchestrator.index import list_projects
                from orchestrator.rag import chroma_stats_isolated
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
                cs = chroma_stats_isolated()
                self._json({
                    "projects": list(projects_info.values()),
                    "registered": sorted(registered),
                    "contexts_by_project": ctx_by_proj,
                    "chroma": cs,
                })
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _get_integrations_status(self, parsed):
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

        def _get_rates(self, parsed):
            try:
                from orchestrator.rates import get_current_rate
                rate_info = get_current_rate(config)
                self._json(rate_info or {"rate": None, "error": "Sin datos ni credenciales"})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _get_pricing(self, parsed):
            try:
                from orchestrator.catalog import resolve_pricing
                pricing, meta = resolve_pricing(config)
                self._json({"pricing": pricing, "source": meta["source"], "updated_at": meta.get("updated_at")})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _get_models(self, parsed):
            try:
                from orchestrator.model_discovery import compare_available_vs_priced
                self._json({"models": compare_available_vs_priced(config)})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _get_agents(self, parsed):
            try:
                from orchestrator.agents import list_agents
                self._json({"agents": [a.to_dict() for a in list_agents()]})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _get_dashboard(self, parsed):
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


        def _require_json_ct(self) -> bool:
            ct = self.headers.get("Content-Type", "")
            if "application/json" not in ct:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length > 0:
                        self.rfile.read(length)
                except (ValueError, OSError):
                    pass
                self._json({"error": "Content-Type: application/json required"}, 415)
                return False
            return True

        def do_POST(self):
            if self.path.startswith("/context/") and self.path.endswith("/delete"):
                if not self._require_json_ct():
                    return
                self._post_context_delete()
                return
            handler = {
                "/clean/unmapped":          self._post_clean_unmapped,
                "/purge-chroma-docs":       self._post_purge_chroma_docs,
                "/purge-chroma-responses":  self._post_purge_chroma_responses,
                "/delete-contexts":         self._post_delete_contexts,
                "/clear-imports":           self._post_clear_imports,
                "/rate-run":                self._post_rate_run,
                "/import-context":          self._post_import_context,
                "/sync-cc":                 self._post_sync_cc,
                "/sync-git":                self._post_sync_git,
                "/sync-codex":              self._post_sync_codex,
                "/rates/refresh":           self._post_rates_refresh,
                "/pricing/refresh":         self._post_pricing_refresh,
                "/models/refresh":          self._post_models_refresh,
                "/config/bcentral":         self._post_config_bcentral,
                "/add-project":             self._post_add_project,
                "/project/rename":          self._post_project_rename,
                "/index-docs":              self._post_index_docs,
                "/create-context":          self._post_create_context,
                "/advance-step":            self._post_advance_step,
                "/skip-step":               self._post_skip_step,
                "/run-doctor":              self._post_run_doctor,
                "/run-fix":                 self._post_run_fix,
                "/run":                     self._post_run,
            }.get(self.path)
            if handler is None:
                self._json({"error": "not found"}, 404)
                return
            if not self._require_json_ct():
                return
            handler()

        def _post_clean_unmapped(self):
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

        def _post_purge_chroma_docs(self):
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

        def _post_purge_chroma_responses(self):
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

        def _post_delete_contexts(self):
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

        def _post_clear_imports(self):
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

        def _post_rate_run(self):
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

        def _post_import_context(self):
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

        def _post_sync_cc(self):
            try:
                from orchestrator.watcher import scan_and_import
                from orchestrator.tracer import span as _tspan
                with _tspan("Sync Claude Code", detail="~/.claude/projects/"):
                    imported = scan_and_import(config, quiet=True)
                self._json({"imported": len(imported), "sessions": imported})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _post_sync_git(self):
            try:
                from orchestrator.git_scanner import scan_and_import as git_import
                from orchestrator.tracer import span as _tspan
                with _tspan("Sync Git", detail="proyectos registrados"):
                    imported = git_import({}, quiet=True)
                self._json({"imported": len(imported), "commits": imported})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _post_sync_codex(self):
            try:
                from orchestrator.codex_watcher import scan_and_import as codex_import
                from orchestrator.tracer import span as _tspan
                with _tspan("Sync Codex", detail="~/.codex/state_N.sqlite"):
                    imported = codex_import(config, quiet=True)
                self._json({"imported": len(imported), "sessions": imported})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _post_rates_refresh(self):
            try:
                from orchestrator.rates import refresh_rate
                result = refresh_rate(config)
                self._json(result)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _post_pricing_refresh(self):
            try:
                from orchestrator.catalog import resolve_pricing
                pricing, meta = resolve_pricing(config, refresh=True)
                self._json({"pricing": pricing, "source": meta["source"], "updated_at": meta.get("updated_at")})
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _post_models_refresh(self):
            try:
                from orchestrator.model_discovery import refresh_available_models
                result = refresh_available_models(config)
                self._json(result)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _post_config_bcentral(self):
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

        def _post_add_project(self):
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

        def _post_project_rename(self):
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

        def _post_index_docs(self):
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
                from orchestrator.rag import index_project_isolated
                from orchestrator.tracer import span as _span
                from pathlib import Path as _Path
                if do_save and extra_skip:
                    try:
                        context_module.save_skip_dirs(_Path(proj_path), extra_skip)
                    except Exception:
                        pass
                with _span(f"index-docs · {proj}"):
                    result = index_project_isolated(proj, _Path(proj_path), extra_skip_dirs=extra_skip or None)
                if result.get("error"):
                    self._json(result, 500)
                    return
                self._json({"chunks": result.get("chunks", 0), "project": proj})
            except ProjectNotFoundError:
                self._json({"error": f"Proyecto no registrado: {proj}"}, 404)
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return

        def _post_create_context(self):
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

        def _post_advance_step(self):
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

        def _post_skip_step(self):
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

        def _post_context_delete(self):
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

        def _post_run_doctor(self):
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

                # HOME env var + Gemini CLI MCP
                import os as _os, sys as _sys
                if _sys.platform == "win32":
                    if _os.environ.get("HOME"):
                        _ok(f"HOME definido: {_os.environ['HOME']}")
                    else:
                        _warn("HOME no definida — Gemini CLI no resuelve ~/.gemini; ejecutá fix para definirla")
                    _gemini_base = _P(_os.environ.get("HOME") or _os.environ.get("USERPROFILE", ""))
                    _gemini_cfg = _gemini_base / ".gemini" / "settings.json"
                    if _gemini_cfg.exists():
                        try:
                            import json as _jg
                            _gd = _jg.loads(_gemini_cfg.read_text(encoding="utf-8"))
                            if "ai-orchestrator" in _gd.get("mcpServers", {}):
                                _ok("Gemini CLI: ai-orchestrator en ~/.gemini/settings.json")
                            else:
                                _warn("Gemini CLI: settings.json existe pero sin ai-orchestrator — ejecutá fix")
                        except Exception:
                            _warn("Gemini CLI: no se pudo leer ~/.gemini/settings.json")
                    else:
                        _warn("Gemini CLI: ~/.gemini/settings.json no existe — ejecutá fix para crearlo")

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

        def _post_run_fix(self):
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

                # HOME env var (Gemini CLI fix)
                import os as _os2, sys as _sys2, subprocess as _sp2
                if _sys2.platform == "win32":
                    _userprofile = _os2.environ.get("USERPROFILE", str(_P.home()))
                    if not _os2.environ.get("HOME"):
                        try:
                            _sp2.run(
                                ["powershell", "-NonInteractive", "-Command",
                                 f'[System.Environment]::SetEnvironmentVariable("HOME", "{_userprofile}", "User")'],
                                capture_output=True, timeout=15,
                            )
                            _ok2(f"HOME definida permanentemente: {_userprofile} — reiniciá VS Code")
                            fixed_count += 1
                        except Exception as exc2:
                            _fail2(f"No se pudo definir HOME: {exc2}")
                    else:
                        _skip2(f"HOME ya definida: {_os2.environ['HOME']}")

                    # Gemini CLI settings.json
                    _gemini_base2 = _P(_os2.environ.get("HOME") or _userprofile)
                    _gemini_cfg2 = _gemini_base2 / ".gemini" / "settings.json"
                    _gemini_cfg2.parent.mkdir(parents=True, exist_ok=True)
                    _abs_py3 = str((_P(__file__).parent.parent / ".venv" / "Scripts" / "python.exe").resolve())
                    _cwd3 = str(_P(__file__).parent.parent.resolve())
                    _mcp_entry = {"command": _abs_py3, "args": ["-u", "-m", "orchestrator.mcp"], "cwd": _cwd3}
                    if _gemini_cfg2.exists():
                        try:
                            _gd2 = _j2.loads(_gemini_cfg2.read_text(encoding="utf-8"))
                            if "ai-orchestrator" in _gd2.get("mcpServers", {}):
                                _skip2("Gemini CLI: ~/.gemini/settings.json ya tiene ai-orchestrator")
                            else:
                                _gd2.setdefault("mcpServers", {})["ai-orchestrator"] = _mcp_entry
                                _gemini_cfg2.write_text(_j2.dumps(_gd2, indent=2, ensure_ascii=False), encoding="utf-8")
                                _ok2("Gemini CLI: ai-orchestrator agregado a ~/.gemini/settings.json")
                                fixed_count += 1
                        except Exception as exc2:
                            _fail2(f"Gemini CLI: error actualizando settings.json: {exc2}")
                    else:
                        _gemini_cfg2.write_text(
                            _j2.dumps({"mcpServers": {"ai-orchestrator": _mcp_entry}}, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        _ok2("Gemini CLI: ~/.gemini/settings.json creado")
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

        def _post_run(self):
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
            self.send_header("Access-Control-Allow-Origin", f"http://127.0.0.1:{self.server.server_address[1]}")
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
                self.send_header("Access-Control-Allow-Origin", f"http://127.0.0.1:{self.server.server_address[1]}")
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
        _console.print(f"[red]✗[/red] No se pudo iniciar en el puerto {port}: {exc}")
        _console.print(f"[dim]  Intentá con otro puerto: ai-orchestrator serve --port 9000[/dim]")
        sys.exit(1)

    _console.print(f"[bold green]✓[/bold green] Dashboard en [cyan]{url}[/cyan]")
    _console.print(f"[dim]  DB: {HOME_DIR / 'runs.db'}[/dim]")
    _console.print(f"[dim]  Ctrl+C para detener · SSE activo[/dim]")

    import threading as _threading
    def _prewarm_chroma():
        try:
            from orchestrator.rag import _get_client
            _get_client()
        except Exception:
            pass
    _threading.Thread(target=_prewarm_chroma, daemon=True).start()

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        _console.print("\n[dim]Dashboard detenido.[/dim]")

