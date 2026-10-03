// Pestaña Proyectos: proyectos registrados, indexación, importación de contextos y explorador de la base.
// Archivo del dashboard heredado (ola 2, separación mecánica); no cambiar el comportamiento.

function loadProyectos() {
  const el = document.getElementById("proyectos-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Cargando...</p>';
  fetch("/inspect")
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        el.innerHTML = `<p style="color:#f87171;font-size:13px">Error del servidor: ${escHtml(data.error)}</p>`;
        return;
      }
      renderProyectos(data);
    })
    .catch(err => {
      el.innerHTML = `<p style="color:#f87171;font-size:13px">Error de conexión: ${escHtml(String(err))}</p>`;
    });
}

function reloadProyectos() {
  const el = document.getElementById("proyectos-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Actualizando...</p>';
  fetch("/inspect")
    .then(r => r.json())
    .then(renderProyectos)
    .catch(() => { el.innerHTML = '<p style="color:#f87171;font-size:13px">Error al recargar.</p>'; });
}

function pickFolder(alias) {
  const btn    = document.getElementById("reg-pick-" + alias);
  const input  = document.getElementById("reg-path-" + alias);
  const status = document.getElementById("reg-status-" + alias);
  const orig   = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  postJson("/pick-folder", "{}")
    .then(r => r.json())
    .then(d => {
      if (d.path) {
        input.value = d.path;
        status.textContent = "";
        input.focus();
      } else {
        status.textContent = d.error ? "✗ " + d.error : "Cancelado.";
        status.style.color = "var(--text-muted)";
      }
    })
    .catch(() => { status.textContent = "✗ Sin respuesta."; status.style.color = "#f87171"; })
    .finally(() => { btn.disabled = false; btn.innerHTML = orig; });
}

function addNewProject() {
  const alias = (document.getElementById("new-proj-alias") || {}).value.trim();
  const path  = (document.getElementById("new-proj-path")  || {}).value.trim();
  const status = document.getElementById("new-proj-status");
  if (!alias) { status.textContent = "El alias no puede estar vacío."; status.style.color = "#f87171"; return; }
  if (!path)  { status.textContent = "La ruta no puede estar vacía.";  status.style.color = "#f87171"; return; }
  status.innerHTML = '<span class="spinner"></span>&nbsp;Registrando...';
  postJson("/add-project", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({alias, path}),
  })
  .then(r => r.json())
  .then(d => {
    if (d.error) { status.textContent = "✗ " + d.error; status.style.color = "#f87171"; return; }
    status.textContent = '✓ Proyecto "' + alias + '" registrado.';
    status.style.color = "#22c55e";
    document.getElementById("new-proj-alias").value = "";
    document.getElementById("new-proj-path").value = "";
    showToast('✓ Proyecto "' + alias + '" agregado.');
    setTimeout(reloadProyectos, 600);
  })
  .catch(() => { status.textContent = "✗ Error de conexión."; status.style.color = "#f87171"; });
}

function pickNewProjectFolder() {
  const btn = document.getElementById("new-proj-pick");
  const orig = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
  postJson("/pick-folder", "{}")
    .then(r => r.json())
    .then(d => {
      if (d.path) {
        const pathInput = document.getElementById("new-proj-path");
        if (pathInput) pathInput.value = d.path;
        if (!document.getElementById("new-proj-alias").value) {
          const bs = String.fromCharCode(92);
          const lastSep = Math.max(d.path.lastIndexOf("/"), d.path.lastIndexOf(bs));
          const seg = lastSep >= 0 ? d.path.slice(lastSep + 1) : d.path;
          if (seg) document.getElementById("new-proj-alias").value = seg;
        }
      }
    })
    .catch(() => {})
    .finally(() => { if (btn) { btn.disabled = false; btn.innerHTML = orig; } });
}

function startRenameProject(alias) {
  const form = document.getElementById("rename-form-" + alias);
  if (form) { form.style.display = "flex"; }
  const inp = document.getElementById("rename-input-" + alias);
  if (inp) { inp.focus(); inp.select(); }
}

function cancelRenameProject(alias) {
  const form = document.getElementById("rename-form-" + alias);
  if (form) form.style.display = "none";
  const inp = document.getElementById("rename-input-" + alias);
  if (inp) inp.value = alias;
  const st = document.getElementById("rename-status-" + alias);
  if (st) st.textContent = "";
}

function confirmRenameProject(oldAlias) {
  const inp = document.getElementById("rename-input-" + oldAlias);
  const st  = document.getElementById("rename-status-" + oldAlias);
  if (!inp) return;
  const newAlias = inp.value.trim();
  if (!newAlias || newAlias === oldAlias) { cancelRenameProject(oldAlias); return; }
  if (st) { st.textContent = "…"; st.style.color = "var(--text-muted)"; }
  postJson("/project/rename", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({old: oldAlias, new: newAlias}),
  })
  .then(r => r.json())
  .then(d => {
    if (d.error) {
      if (st) { st.textContent = "✗ " + d.error; st.style.color = "#f87171"; }
    } else {
      if (st) { st.textContent = "✓"; st.style.color = "#22c55e"; }
      setTimeout(reloadProyectos, 700);
    }
  })
  .catch(() => { if (st) { st.textContent = "✗ Error"; st.style.color = "#f87171"; } });
}

function registerProject(alias) {
  const input  = document.getElementById("reg-path-" + alias);
  const status = document.getElementById("reg-status-" + alias);
  const path = input ? input.value.trim() : "";
  if (!path) { status.textContent = "Ingresá la ruta."; status.style.color = "#f87171"; return; }
  status.innerHTML = '<span class="spinner"></span>';
  postJson("/add-project", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({alias, path}),
  })
  .then(r => r.json())
  .then(d => {
    if (d.error) { status.textContent = "✗ " + d.error; status.style.color = "#f87171"; }
    else {
      status.textContent = "✓ registrado";
      status.style.color = "#22c55e";
      const row = document.getElementById("reg-row-" + alias);
      if (row) row.style.opacity = "0.4";
      setTimeout(reloadProyectos, 900);
    }
  })
  .catch(() => { status.textContent = "✗ Error de conexión."; status.style.color = "#f87171"; });
}

function startIndexFlow() {
  const proj = (document.getElementById("insp-project-sel") || {}).value || "";
  const status = document.getElementById("insp-action-status");
  if (!proj) { status.textContent = "Seleccioná un proyecto."; return; }
  status.innerHTML = '<span class="spinner"></span>&nbsp;Cargando carpetas...';
  document.getElementById("insp-index-btn").disabled = true;
  fetch("/preview-index?project=" + encodeURIComponent(proj))
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        status.textContent = "Error: " + data.error;
        document.getElementById("insp-index-btn").disabled = false;
        return;
      }
      status.textContent = "";
      _renderPreflightPanel(data);
      document.getElementById("index-preflight").style.display = "block";
      document.getElementById("insp-index-btn").style.display = "none";
    })
    .catch(() => {
      status.textContent = "Error al obtener carpetas.";
      document.getElementById("insp-index-btn").disabled = false;
    });
}

function _renderPreflightPanel(data) {
  const container = document.getElementById("index-folder-list");
  const folders = data.folders || [];
  if (!folders.length) {
    container.innerHTML = '<p class="text-faint" style="font-size:12px">No se encontraron subcarpetas.</p>';
    return;
  }
  container.innerHTML = folders.map(f => {
    const checked = f.suggested_skip || f.already_excluded;
    const badge = f.already_excluded
      ? `<span style="font-size:10px;color:var(--text-muted);margin-left:4px">guardado</span>`
      : f.suggested_skip
        ? `<span style="font-size:10px;color:var(--text-muted);margin-left:4px">sugerido</span>`
        : "";
    return `<label style="display:flex;align-items:center;gap:6px;padding:6px 10px;
            background:var(--bg-elevated);border-radius:6px;font-size:12px;cursor:pointer;
            border:1px solid var(--border);user-select:none">
      <input type="checkbox" class="folder-exclude-cb" value="${escHtml(f.name)}" ${checked ? "checked" : ""}>
      <span style="font-family:'JetBrains Mono',monospace">${escHtml(f.name)}/</span>
      <span style="color:var(--text-faint)">${escHtml(String(Number(f.file_count) || 0))} arch.</span>
      ${badge}
    </label>`;
  }).join("");
}

function confirmIndex() {
  const proj = (document.getElementById("insp-project-sel") || {}).value || "";
  const save = (document.getElementById("index-save-exclusions") || {}).checked !== false;
  const excluded = [...document.querySelectorAll(".folder-exclude-cb:checked")].map(cb => cb.value);
  const status = document.getElementById("insp-action-status");
  status.innerHTML = '<span class="spinner"></span>&nbsp;Indexando...';
  postJson("/index-docs", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project: proj, extra_skip_dirs: excluded, save_skip_dirs: save}),
  })
  .then(r => r.json())
  .then(d => {
    document.getElementById("index-preflight").style.display = "none";
    document.getElementById("insp-index-btn").style.display = "";
    document.getElementById("insp-index-btn").disabled = false;
    if (d.error) { status.textContent = "Error: " + d.error; showToast("Error indexando: " + d.error, true); }
    else { status.textContent = "✓ " + d.chunks + " chunks indexados para '" + d.project + "'."; showToast("✓ " + d.chunks + " chunks indexados — " + d.project); }
    reloadProyectos();
  })
  .catch(() => {
    status.textContent = "Error de conexión.";
    document.getElementById("insp-index-btn").disabled = false;
  });
}

function cancelIndexFlow() {
  document.getElementById("index-preflight").style.display = "none";
  document.getElementById("insp-index-btn").style.display = "";
  document.getElementById("insp-index-btn").disabled = false;
  document.getElementById("insp-action-status").textContent = "";
}

function _onImpAgentChange() {
  const agent = (document.getElementById("imp-agent-sel") || {}).value || "";
  const isCC = agent === "claude-code";
  document.getElementById("imp-panel-cc").style.display = isCC ? "" : "none";
  document.getElementById("imp-panel-manual").style.display = isCC ? "none" : "";
}

function triggerSyncCC() {
  const status = document.getElementById("imp-cc-status");
  status.innerHTML = '<span class="spinner"></span>&nbsp;Sincronizando...';
  postJson("/sync-cc", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"})
    .then(r => r.json())
    .then(d => {
      if (d.error) { status.textContent = "Error: " + d.error; showToast("Error sync-cc: " + d.error, true); return; }
      const msg = d.imported === 0
        ? "No hay sesiones nuevas."
        : "✓ " + d.imported + " sesión(es) sincronizada(s) e indexadas.";
      status.textContent = msg;
      showToast(msg);
      reloadProyectos();
    })
    .catch(() => { status.textContent = "Error de conexión."; });
}

function clearImports() {
  const proj = (document.getElementById("imp-clear-project") || {}).value || "";
  const provider = (document.getElementById("imp-clear-provider") || {}).value || "";
  const status = document.getElementById("imp-clear-status");
  if (!proj) { status.textContent = "Seleccioná un proyecto."; return; }
  const providerLabel = provider ? `<strong>${escHtml(provider)}</strong>` : "todos los providers";
  showConfirmModal(
    "Limpiar datos importados",
    `Se eliminarán los registros de <strong>${escHtml(proj)}</strong> (${providerLabel}) de <code>runs.db</code> y los vectores RAG en ChromaDB.<br><br>` +
    `<span style="font-size:12px;color:var(--text-muted)">Los archivos fuente no se modifican — podés volver a indexar en cualquier momento.</span>`,
    () => _doCleanImports(proj, provider, status),
    { okLabel: "Eliminar", okDanger: true }
  );
}

function _doCleanImports(proj, provider, status) {
  status.innerHTML = '<span class="spinner"></span>&nbsp;Limpiando...';
  postJson("/clear-imports", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project: proj, provider: provider || null}),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) { status.textContent = "Error: " + d.error; showToast("Error: " + d.error, true); return; }
      const msg = `✓ ${d.runs_deleted} runs y ${d.chroma_purged} vectores eliminados de "${proj}".`;
      status.textContent = msg;
      showToast(msg);
      reloadProyectos();
    })
    .catch(() => { status.textContent = "Error de conexión."; });
}

function submitImportContext() {
  const proj = (document.getElementById("imp-project-sel") || {}).value || "";
  const agent = (document.getElementById("imp-agent-sel") || {}).value || "external";
  const model = (document.getElementById("imp-model") || {}).value || "";
  const task = (document.getElementById("imp-task") || {}).value.trim();
  const response = (document.getElementById("imp-response") || {}).value.trim();
  const status = document.getElementById("imp-manual-status");
  if (!proj) { status.textContent = "Seleccioná un proyecto."; return; }
  if (!task) { status.textContent = "La tarea no puede estar vacía."; return; }
  if (!response) { status.textContent = "La respuesta no puede estar vacía."; return; }
  status.innerHTML = '<span class="spinner"></span>&nbsp;Importando...';
  postJson("/import-context", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project: proj, agent, model, task, response}),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) { status.textContent = "Error: " + d.error; showToast("Error: " + d.error, true); return; }
      const msg = "✓ Run #" + d.run_id + " importado" + (d.indexed ? " e indexado en RAG." : ".");
      status.textContent = msg;
      showToast(msg);
      document.getElementById("imp-task").value = "";
      document.getElementById("imp-response").value = "";
      reloadProyectos();
    })
    .catch(() => { status.textContent = "Error de conexión."; });
}

function renderProyectos(data) {
  const el = document.getElementById("proyectos-content");
  const chroma = data.chroma || {};
  const COLS = ["runs","docs","responses"];
  const colLabels = {runs:"Routing memory",docs:"Docs (RAG)",responses:"Respuestas"};
  const registered = new Set(data.registered_projects || []);
  const allProjects = data.all_projects || [];
  const projOpts = allProjects.map(p => {
    const indexable = registered.has(p);
    const label = indexable ? p : p + " (sin ruta)";
    return `<option value="${escHtml(p)}" ${indexable ? "" : 'style="color:var(--text-muted)"'}>${escHtml(label)}</option>`;
  }).join("");
  // ── Panel: Proyectos ─────────────────────────────────────────────────────
  const unregistered = allProjects.filter(p => !registered.has(p));
  const unregRows = unregistered.map(function(p) {
    const pe = escHtml(p);
    return (
      '<div style="display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border-faint)" id="reg-row-' + pe + '">' +
      '<span style="font-size:12px;color:var(--text-primary);min-width:130px;font-family:monospace;flex-shrink:0">' + pe + '</span>' +
      '<input type="text" id="reg-path-' + pe + '" placeholder="Ruta al directorio del proyecto" style="flex:1;min-width:0;font-size:12px">' +
      '<button class="btn btn-secondary" data-proj="' + pe + '" id="reg-pick-' + pe + '" title="Seleccionar carpeta" style="padding:0 10px;font-size:15px;flex-shrink:0" onclick="pickFolder(this.dataset.proj)">&#128193;</button>' +
      '<button class="btn btn-secondary" data-proj="' + pe + '" style="white-space:nowrap;flex-shrink:0;font-size:12px" onclick="registerProject(this.dataset.proj)">Registrar</button>' +
      '<span id="reg-status-' + pe + '" style="font-size:12px;min-width:80px;flex-shrink:0"></span>' +
      '</div>'
    );
  }).join("");
  const unregSection = unregistered.length
    ? '<p class="text-muted" style="font-size:12px;margin:0 0 6px">Proyectos detectados sin ruta — completá la ruta para habilitarlos:</p>' + unregRows
    : "";
  const mbAdd = unregistered.length ? "14px" : "6px";

  // ── Tabla de proyectos registrados (alias → path + ✎ renombrar) ──────────
  // Los alias no van en handlers en línea: el escape HTML no protege una
  // cadena JavaScript dentro de un atributo onclick. Se leen de data-alias.
  if (!window.__regDelegated) {
    window.__regDelegated = true;
    document.addEventListener("click", function(ev) {
      const btn = ev.target.closest && ev.target.closest("[data-reg-action]");
      if (!btn) return;
      const alias = btn.dataset.alias || "";
      if (btn.dataset.regAction === "start") startRenameProject(alias);
      else if (btn.dataset.regAction === "confirm") confirmRenameProject(alias);
      else if (btn.dataset.regAction === "cancel") cancelRenameProject(alias);
    });
    document.addEventListener("keydown", function(ev) {
      const input = ev.target.closest && ev.target.closest("input[data-reg-input]");
      if (!input) return;
      if (ev.key === "Enter") confirmRenameProject(input.dataset.alias || "");
      else if (ev.key === "Escape") cancelRenameProject(input.dataset.alias || "");
    });
  }
  const regIndex = data.registered_project_index || {};
  const regEntries = Object.entries(regIndex);
  const regRows2 = regEntries.map(function([alias, projPath]) {
    const ae = escHtml(alias);
    const pe = escHtml(projPath);
    return (
      '<div class="reg-proj-row" id="regrow-' + ae + '" style="display:flex;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid var(--border-faint)">' +
        '<span style="font-size:12px;font-weight:600;color:var(--text-primary);min-width:140px;font-family:monospace;flex-shrink:0">' + ae + '</span>' +
        '<span style="font-size:11px;color:var(--text-faint);flex:1;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + pe + '">' + pe + '</span>' +
        '<button class="btn btn-secondary" style="padding:2px 10px;font-size:11px;flex-shrink:0" data-reg-action="start" data-alias="' + ae + '">✎ Renombrar</button>' +
        '<div id="rename-form-' + ae + '" style="display:none;gap:6px;align-items:center">' +
          '<input id="rename-input-' + ae + '" type="text" value="' + ae + '" style="width:140px;font-size:12px" data-reg-input="1" data-alias="' + ae + '">' +
          '<button class="btn btn-primary" style="padding:2px 10px;font-size:11px;flex-shrink:0" data-reg-action="confirm" data-alias="' + ae + '">OK</button>' +
          '<button class="btn btn-secondary" style="padding:2px 10px;font-size:11px;flex-shrink:0" data-reg-action="cancel" data-alias="' + ae + '">✕</button>' +
          '<span id="rename-status-' + ae + '" style="font-size:11px;min-width:60px"></span>' +
        '</div>' +
      '</div>'
    );
  }).join("");
  const regSection2 = regEntries.length
    ? '<div style="margin-top:4px;margin-bottom:6px">' + regRows2 + '</div>'
    : '<p class="text-muted" style="font-size:12px;margin:4px 0 6px">Sin proyectos registrados.</p>';

  let html = '<div class="panel" style="margin-bottom:16px">' +
    '<h2>Proyectos</h2>' +
    '<p class="text-muted" style="font-size:11px;margin-bottom:8px">Proyectos registrados en el índice:</p>' +
    regSection2 +
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:' + mbAdd + ';border-top:1px solid var(--border-faint);padding-top:10px;margin-top:4px">' +
      '<input id="new-proj-alias" type="text" placeholder="alias (ej: mi-proyecto)" style="width:160px;font-size:12px">' +
      '<input id="new-proj-path" type="text" placeholder="Ruta al directorio" style="flex:1;min-width:160px;font-size:12px">' +
      '<button id="new-proj-pick" class="btn btn-secondary" title="Seleccionar carpeta…" style="padding:0 10px;font-size:15px;flex-shrink:0" onclick="pickNewProjectFolder()">&#128193;</button>' +
      '<button class="btn btn-primary" style="white-space:nowrap;flex-shrink:0" onclick="addNewProject()">+ Agregar proyecto</button>' +
      '<span id="new-proj-status" class="text-muted" style="font-size:12px;width:100%"></span>' +
    '</div>' +
    unregSection +
  '</div>';

  html += `<div class="panel" style="margin-bottom:16px">
    <h2>Acciones</h2>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <select id="insp-project-sel" style="min-width:160px">
        <option value="">— proyecto —</option>${projOpts}
      </select>
      <button id="insp-index-btn" class="btn btn-primary" onclick="startIndexFlow()">Actualizar conocimiento</button>
      <span id="insp-action-status" class="text-muted" style="font-size:12px"></span>
      <button class="btn btn-secondary" onclick="reloadProyectos()" style="margin-left:auto">↻ Recargar</button>
    </div>
    <div id="index-preflight" style="display:none;margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <p style="font-size:12px;color:var(--text-muted);margin-bottom:10px">
        Elegí qué carpetas <strong>excluir</strong> de la indexación. Las marcadas no se indexarán.
      </p>
      <div id="index-folder-list" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px"></div>
      <label style="font-size:12px;color:var(--text-muted);display:flex;align-items:center;gap:6px;margin-bottom:12px;cursor:pointer">
        <input type="checkbox" id="index-save-exclusions" checked>
        Guardar exclusiones en context.yaml (se pre-cargan la próxima vez)
      </label>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="confirmIndex()">Confirmar e indexar</button>
        <button class="btn btn-secondary" onclick="cancelIndexFlow()">Cancelar</button>
      </div>
    </div>
  </div>
  <div class="panel" style="margin-bottom:20px">
    <h2>ChromaDB — Colecciones vectoriales</h2>
    <div class="insp-grid">`;
  COLS.forEach(col => {
    const c = chroma[col] || {};
    const bp = c.by_project || {};
    const bpRows = Object.entries(bp).map(([p,n]) =>
      `<div class="col-proj-row"><span class="text-faint">${escHtml(p)}</span><span style="color:#22c55e;font-weight:600">${n}</span></div>`
    ).join("");
    html += `<div class="insp-stat">
      <div class="col-name">${colLabels[col] || col}</div>
      <div class="col-count">${c.count ?? "—"}</div>
      <div class="col-sub">documentos indexados</div>
      ${bpRows ? '<div class="col-projects">' + bpRows + '</div>' : ""}
    </div>`;
  });
  html += `</div></div></div>`;

  // ── Panel: Efectividad RAG ────────────────────────────────────────────────
  const ragEff    = data.rag_effectiveness || [];
  const ragChunks = data.rag_top_chunks    || [];
  if (ragEff.length) {
    const ragRows = ragEff.map(r => {
      const pct   = r.hit_pct ?? 0;
      const color = pct >= 60 ? '#22c55e' : pct >= 30 ? '#f59e0b' : '#f87171';
      return '<tr style="border-bottom:1px solid var(--border-faint)">' +
        '<td style="padding:7px 10px;font-size:12px;font-family:monospace;color:var(--text-primary)">'  + escHtml(r.project)       + '</td>' +
        '<td style="padding:7px 10px;font-size:12px;color:var(--text-muted);text-align:right">'         + r.total_runs              + '</td>' +
        '<td style="padding:7px 10px;font-size:12px;color:var(--text-muted);text-align:right">'         + r.runs_with_hits          + '</td>' +
        '<td style="padding:7px 10px;font-size:12px;font-weight:700;color:' + color + ';text-align:right">' + pct + '%'             + '</td>' +
      '</tr>';
    }).join('');

    const topRows = ragChunks.map(c => {
      const src   = c.source || '';
      const bsep  = String.fromCharCode(92);
      const i1    = Math.max(src.lastIndexOf('/'), src.lastIndexOf(bsep));
      const i2    = i1 > 0 ? Math.max(src.lastIndexOf('/', i1 - 1), src.lastIndexOf(bsep, i1 - 1)) : -1;
      const short = i2 >= 0 ? src.slice(i2 + 1) : src;
      return '<tr style="border-bottom:1px solid var(--border-faint)">' +
        '<td style="padding:5px 10px;font-size:11px;font-family:monospace;color:var(--text-primary)">' + escHtml(c.project) + '</td>' +
        '<td style="padding:5px 10px;font-size:11px;color:var(--text-muted)" title="' + escHtml(src) + '">' + escHtml(short) + '</td>' +
        '<td style="padding:5px 10px;font-size:11px;color:#22c55e;text-align:right;font-weight:600">'  + c.frequency + '</td>' +
      '</tr>';
    }).join('');

    html += `<div class="panel" style="margin-bottom:16px">
      <h2>Efectividad RAG</h2>
      <p class="text-muted" style="font-size:12px;margin-bottom:14px">Porcentaje de runs (excluye importaciones sync-cc / codex / git) que usaron al menos un chunk de contexto RAG en su respuesta.</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div>
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:8px">Por proyecto — % con RAG hits</div>
          <table style="width:100%;border-collapse:collapse">
            <thead><tr style="background:var(--bg-elevated)">
              <th style="padding:6px 10px;font-size:10px;text-align:left;text-transform:uppercase;letter-spacing:.5px">Proyecto</th>
              <th style="padding:6px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">Runs</th>
              <th style="padding:6px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">Con RAG</th>
              <th style="padding:6px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">%</th>
            </tr></thead>
            <tbody>${ragRows}</tbody>
          </table>
        </div>
        <div>
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:8px">Chunks más recuperados</div>
          ${topRows
            ? '<table style="width:100%;border-collapse:collapse"><thead><tr style="background:var(--bg-elevated)"><th style="padding:5px 10px;font-size:10px;text-align:left;text-transform:uppercase;letter-spacing:.5px">Proyecto</th><th style="padding:5px 10px;font-size:10px;text-align:left;text-transform:uppercase;letter-spacing:.5px">Chunk</th><th style="padding:5px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">Hits</th></tr></thead><tbody>' + topRows + '</tbody></table>'
            : '<p class="text-muted" style="font-size:12px">Sin datos — indexá docs y ejecutá tareas primero.</p>'
          }
        </div>
      </div>
    </div>`;
  }

  // ── Panel: Importar contexto de agentes ──────────────────────────────────
  const impProjOpts = allProjects.map(p =>
    `<option value="${escHtml(p)}">${escHtml(p)}</option>`
  ).join("");
  html += `<div class="panel" style="margin-bottom:16px">
    <h2>Importar contexto de agentes</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
      <select id="imp-project-sel" style="min-width:140px">
        <option value="">— proyecto —</option>${impProjOpts}
      </select>
      <select id="imp-agent-sel" onchange="_onImpAgentChange()" style="min-width:140px">
        <option value="claude-code">Claude Code (auto-sync)</option>
        <option value="claude">Claude (manual)</option>
        <option value="deepseek">DeepSeek</option>
        <option value="openai">OpenAI</option>
        <option value="other">Otro agente</option>
      </select>
      <input id="imp-model" type="text" placeholder="Modelo (opcional)" style="width:160px;font-size:12px">
    </div>
    <div id="imp-panel-cc">
      <p class="text-muted" style="font-size:12px;margin-bottom:8px">
        Importa sesiones desde <code>~/.claude/projects/</code> extrayendo el contenido completo de las respuestas para indexarlas en RAG.
      </p>
      <button class="btn btn-primary" onclick="triggerSyncCC()">↻ Sincronizar Claude Code</button>
      <span id="imp-cc-status" class="text-muted" style="font-size:12px;margin-left:8px"></span>
    </div>
    <div id="imp-panel-manual" style="display:none">
      <textarea id="imp-task" rows="2" placeholder="Tarea / Prompt enviado al agente"
        style="width:100%;margin-bottom:6px;font-size:12px;box-sizing:border-box"></textarea>
      <textarea id="imp-response" rows="6" placeholder="Respuesta del agente"
        style="width:100%;margin-bottom:8px;font-size:12px;box-sizing:border-box"></textarea>
      <button class="btn btn-primary" onclick="submitImportContext()">Importar y indexar</button>
      <span id="imp-manual-status" class="text-muted" style="font-size:12px;margin-left:8px"></span>
    </div>
    <p class="text-muted" style="font-size:11px;margin-top:10px">Para limpiar runs por proyecto o eliminar proyectos no mapeados usá la pestaña <strong>Datos</strong>. Para configurar credenciales de BCCh usá <strong>Configuración</strong>.</p>
  </div>`;

  function mkTable(title, rows, cols) {
    const n = (rows||[]).length;
    if (!n) return `<div class="panel" style="margin-bottom:16px"><h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">(0)</span></h2><p class="text-faint" style="font-size:13px">Sin registros.</p></div>`;
    const ths = cols.map(c => `<th style="text-align:left;padding:7px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px">${c.label}</th>`).join("");
    const trs = rows.map(r => `<tr style="border-bottom:1px solid var(--border-faint)">${
      cols.map(c => {
        const val = r[c.key] ?? "—";
        const sval = c.fmt ? c.fmt(val) : String(val);
        const display = c.max && sval.length > c.max ? sval.slice(0, c.max) + "…" : sval;
        return `<td style="padding:7px 10px;font-size:12px;color:${c.color||"var(--text-secondary)"};${c.mono?"font-family:'JetBrains Mono',monospace":""}">
          ${escHtml(display)}
        </td>`;
      }).join("")
    }</tr>`).join("");
    return `<div class="panel" style="margin-bottom:16px;overflow-x:auto">
      <h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">${n} filas</span></h2>
      <table><thead><tr style="background:var(--bg-elevated);border-bottom:1px solid var(--border)">${ths}</tr></thead><tbody>${trs}</tbody></table>
    </div>`;
  }

  html += mkTablePaged("chunks","Chunks indexados (RAG)", data.chunks, [
    {label:"Proyecto",    key:"project",    color:"var(--text-primary)"},
    {label:"Archivo",     key:"source_path",color:"var(--text-secondary)",mono:true,max:60},
    {label:"Chunks",      key:"chunk_count",color:"#22c55e"},
    {label:"Colección",   key:"collection", color:"var(--text-muted)"},
    {label:"Indexado",    key:"ts",         color:"var(--text-faint)",mono:true,fmt:fmtTs},
  ]);

  html += mkTablePaged("contexts","Flujos", data.contexts, [
    {label:"ID",      key:"id",          color:"var(--text-faint)",mono:true},
    {label:"Proyecto",key:"project",     color:"var(--text-primary)"},
    {label:"Título",  key:"title",       color:"var(--text-detail)",max:50},
    {label:"Estado",  key:"status",      color:"#22c55e"},
    {label:"Creado",  key:"ts",          color:"var(--text-faint)",mono:true,fmt:fmtTs},
  ]);

  html += mkTablePaged("steps","Pasos", data.steps, [
    {label:"ID",       key:"id",            color:"var(--text-faint)",mono:true},
    {label:"Proyecto", key:"project",       color:"var(--text-primary)"},
    {label:"Contexto", key:"context_title", color:"var(--text-secondary)",max:30},
    {label:"#",        key:"order_idx",     color:"var(--text-muted)",mono:true},
    {label:"Título",   key:"title",         color:"var(--text-detail)",max:40},
    {label:"Estado",   key:"status",        color:"#38bdf8"},
    {label:"Provider", key:"provider",      color:"var(--text-muted)"},
  ]);

  html += mkTablePaged("alignments","Alineamientos", data.alignments, [
    {label:"ID",         key:"id",         color:"var(--text-faint)",mono:true},
    {label:"Hora",       key:"ts",         color:"var(--text-faint)",mono:true,fmt:fmtTs},
    {label:"Paso",       key:"step_title", color:"var(--text-secondary)",max:35},
    {label:"Agente",     key:"agent",      color:"var(--text-detail)"},
    {label:"OK",         key:"confirmed",  color:"#22c55e"},
    {label:"Checkpoint", key:"checkpoint", color:"var(--text-muted)",max:50},
  ]);

  html += mkTablePaged("tool_calls","Tool Calls", data.tool_calls, [
    {label:"ID",          key:"id",          color:"var(--text-faint)",mono:true},
    {label:"Hora",        key:"ts",          color:"var(--text-faint)",mono:true,fmt:fmtTs},
    {label:"Paso",        key:"step_title",  color:"var(--text-secondary)",max:35},
    {label:"Herramienta", key:"tool_name",   color:"var(--text-primary)",mono:true},
    {label:"Estado",      key:"status",      color:"#22c55e"},
    {label:"ms",          key:"duration_ms", color:"var(--text-muted)"},
  ]);

  el.innerHTML = html;
}
