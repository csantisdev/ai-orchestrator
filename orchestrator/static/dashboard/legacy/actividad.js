// Pestaña Actividad: tabla de runs, filtros, CSV, filas en vivo, detalle del run y envío de tareas.
// Archivo del dashboard heredado (ola 2, separación mecánica); no cambiar el comportamiento.



// ── Runs table state ─────────────────────────────────────────────────────────
// var (no let) para que onclick attrs del HTML puedan mutar las variables desde
// el scope global. Con let, onclick crea window._runsPage=N pero renderRunsTable
// sigue leyendo la let del closure del script, que nunca cambia.
var _runsPage = 0;

var _runsPageSize = 10;

var _runsFilterProject = "";

var _runsFilterModel = "";

function renderRunsTable() {
  const PROV_CLR = {claude:"#fb923c",deepseek:"#22c55e",openai:"#818cf8"};
  const PROV_BG  = {claude:"rgba(251,146,60,0.15)",deepseek:"rgba(34,197,94,0.15)",openai:"rgba(129,140,248,0.15)"};
  const data = (window.__runsData||[]).filter(r => {
    if (_runsFilterProject && r.project !== _runsFilterProject) return false;
    if (_runsFilterModel && (r.model||"").split("/").pop() !== _runsFilterModel) return false;
    return true;
  });
  const total = data.length;
  const totalPages = Math.max(1, Math.ceil(total/_runsPageSize));
  if (_runsPage >= totalPages) _runsPage = totalPages-1;
  const start = _runsPage*_runsPageSize;
  const pageData = data.slice(start, start+_runsPageSize);

  const tbody = document.getElementById("runs-body");
  const table = document.getElementById("runs-table");
  const empty = document.getElementById("empty-msg");
  if (!total) {
    if (table) table.style.display = "none";
    if (empty) empty.style.display = "";
    const pg = document.getElementById("runs-pagination");
    if (pg) pg.innerHTML = "";
    const cnt = document.getElementById("runs-count");
    if (cnt) cnt.textContent = "(0)";
    return;
  }
  if (table) table.style.display = "";
  if (empty) empty.style.display = "none";

  tbody.innerHTML = pageData.map(r => {
    const runId = Number(r.id);
    if (!Number.isInteger(runId)) return "";
    const prov = r.provider||"?";
    const clr  = PROV_CLR[prov]||"#888";
    const bg   = PROV_BG[prov]||"rgba(113,113,122,0.12)";
    const badge = `<span style="background:${bg};color:${clr};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap">${escHtml(prov)}</span>`;
    const modelShort = (r.model||"—").split("/").pop();
    const task = r.task_preview||r.task||"";
    const taskD = task.length>80 ? task.slice(0,80)+"…" : task;
    let statusHtml = "";
    if (r.status==="running") statusHtml='<span class="badge badge-running">⟳ running</span>';
    else if (r.status==="pending") statusHtml='<span class="badge badge-pending">… pending</span>';
    else if (r.status==="failed")  statusHtml='<span class="badge badge-failed">✗ failed</span>';
    return `<tr data-run-id="${runId}" onclick="openDetail(Number(this.dataset.runId))" style="cursor:pointer">
      <td class="td-ts">${escHtml(_fmtRunTs(r.ts))}</td>
      <td class="td-project">${escHtml(r.project||"—")}</td>
      <td style="padding:9px 12px">${badge}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);font-family:'JetBrains Mono',monospace">${escHtml(modelShort)}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);text-align:right;font-variant-numeric:tabular-nums">${_fmtRunDur(r.duration_ms)}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);text-align:right;font-variant-numeric:tabular-nums">${_fmtRunTokens(r.input_tokens,r.output_tokens)}</td>
      <td style="padding:9px 12px;font-size:12px;color:#22c55e;text-align:right;font-weight:500;font-variant-numeric:tabular-nums">${r.status==="done"&&r.cost_usd==null?'<span style="color:#f59e0b;font-size:10px" title="Modelo sin pricing registrado">?</span>':_fmtRunCost(r.cost_usd)}</td>
      <td style="padding:9px 12px;font-size:12px;color:var(--text-secondary);text-align:center">${_fmtRunCache(r.cache_read_tokens,r.input_tokens)}</td>
      <td class="td-muted" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(task)}">${escHtml(taskD)}</td>
      <td style="padding:9px 12px;font-size:11px">${statusHtml}</td>
    </tr>`;
  }).join("");

  const cnt = document.getElementById("runs-count");
  if (cnt) cnt.textContent = `(${start+1}–${Math.min(start+_runsPageSize,total)} de ${total})`;

  const pg = document.getElementById("runs-pagination");
  if (pg) pg.innerHTML = _buildPagination(
    _runsPage, totalPages, _runsPageSize,
    `_runsPage=${_runsPage-1};renderRunsTable()`,
    `_runsPage=${_runsPage+1};renderRunsTable()`,
    `_runsPageSize=10;_runsPage=0;renderRunsTable()`,
    `_runsPageSize=25;_runsPage=0;renderRunsTable()`,
    `_runsPageSize=50;_runsPage=0;renderRunsTable()`,
    `_runsPageSize=100;_runsPage=0;renderRunsTable()`
  );
}

function applyRunFilters() {
  _runsFilterProject = (document.getElementById("filterProject")||{}).value||"";
  _runsFilterModel   = (document.getElementById("filterModel")||{}).value||"";
  _runsPage = 0;
  renderRunsTable();
}

// ── Export CSV ────────────────────────────────────────────────────────────────
function exportCSV() {
  const proj = (document.getElementById("filterProject")||{}).value||"";
  const mdl  = (document.getElementById("filterModel")||{}).value||"";
  let url = "/export-csv";
  const params = [];
  if (proj) params.push("project="+encodeURIComponent(proj));
  if (mdl)  params.push("model="+encodeURIComponent(mdl));
  if (params.length) url += "?"+params.join("&");
  window.location.href = url;
}

function prependPendingRow(d) {
  const tbody = document.getElementById("runs-body");
  const empty = document.getElementById("empty-msg");
  if (empty) empty.style.display = "none";
  const table = document.getElementById("runs-table");
  if (table) table.style.display = "";
  const tr = document.createElement("tr");
  tr.dataset.runId = d.run_id;
  tr.style.cursor = "pointer";
  tr.onclick = () => openDetail(d.run_id);
  tr.innerHTML = `
    <td class="td-ts">ahora</td>
    <td class="td-project">${escHtml(d.project)}</td>
    <td style="padding:9px 12px"><span class="badge badge-pending">… pending</span></td>
    <td colspan="7" class="td-muted"><span class="spinner"></span> esperando respuesta...</td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);
}

function updateRow(d) {
  const tr = document.querySelector(`tr[data-run-id="${d.run_id}"]`);
  if (!tr) return;
  tr.cells[2].innerHTML = '<span class="badge" style="background:rgba(34,197,94,0.12);color:#22c55e">done</span>';
  if (tr.cells[3]) {
    tr.cells[3].colSpan = 1;
    tr.cells[3].textContent = d.model ? d.model.split("/").pop() : "?";
    for (let i = 4; i < 10; i++) {
      if (!tr.cells[i]) {
        const td = tr.insertCell(i);
        td.style.padding = "8px 10px";
        td.style.fontSize = "12px";
        td.style.textAlign = i < 7 ? "right" : "left";
      }
    }
    tr.cells[4].textContent = d.duration_ms ? (d.duration_ms >= 1000 ? (d.duration_ms/1000).toFixed(1)+"s" : d.duration_ms+"ms") : "—";
    tr.cells[6].textContent = _fmtUsd(d.cost_usd);
  }
}

function markFailed(d) {
  const tr = document.querySelector(`tr[data-run-id="${d.run_id}"]`);
  if (!tr) return;
  tr.cells[2].innerHTML = '<span class="badge badge-failed">✗ failed</span>';
  if (tr.cells[3]) tr.cells[3].textContent = d.error || "error";
}

function updateBudgetGauge(d) {
  const sec = document.getElementById("budgetSection");
  const pct = Math.min(d.pct * 100, 100).toFixed(0);
  const color = d.pct >= 1.0 ? "#ef4444" : d.pct >= 0.8 ? "#f59e0b" : "#22c55e";
  sec.innerHTML = `<div class="panel" style="margin-bottom:20px">
    <h2>Presupuesto diario — ${escHtml(d.project)} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:10px;color:var(--text-faint)">USD</span></h2>
    <div class="budget-meta">
      <span>Gastado: <strong class="text-primary">${_fmtUsd(d.spent_usd, 4)}</strong></span>
      <span>Límite: <strong class="text-primary">${_fmtUsd(d.limit_usd, 2)}</strong></span>
      <span style="color:${color};font-weight:700">${pct}%</span>
    </div>
    <div class="budget-bar"><div class="budget-fill" style="width:${pct}%;background:${color}"></div></div>
  </div>`;
}

function openDetail(runId) {
  runId = Number(runId);
  if (!Number.isInteger(runId)) return;
  const overlay = document.getElementById("detailOverlay");
  const content = document.getElementById("detailContent");
  overlay.classList.add("open");
  content.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span> Cargando...</p>';
  fetch("/run/" + runId)
    .then(r => r.json())
    .then(data => {
      const provColor = {"claude":"#fb923c","deepseek":"#22c55e","openai":"#818cf8"}[data.provider] || "var(--text-muted)";
      const provBg = {"claude":"rgba(251,146,60,0.12)","deepseek":"rgba(34,197,94,0.12)","openai":"rgba(129,140,248,0.12)"}[data.provider] || "rgba(113,113,122,0.12)";
      content.innerHTML = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
          <span class="chip-mono">#${safeNumber(data.id)}</span>
          <span style="background:${provBg};color:${provColor};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600">${escHtml(data.provider)}</span>
          <span class="chip-mono">${escHtml(data.model ? data.model.split('/').pop() : '—')}</span>
          <span class="chip">${Number.isFinite(Number(data.duration_ms)) ? (Number(data.duration_ms)/1000).toFixed(1)+"s" : "—"}</span>
          ${data.cost_usd ? `<span style="background:rgba(34,197,94,0.10);color:#22c55e;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600">${_fmtUsd(data.cost_usd)}</span>` : (data.status==="done" ? '<span style="background:rgba(245,158,11,0.10);color:#f59e0b;padding:3px 10px;border-radius:20px;font-size:11px" title="Modelo sin pricing registrado">sin precio</span>' : '')}
          ${data.router_cost_usd ? `<span style="background:rgba(56,189,248,0.08);color:#38bdf8;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:500" title="Costo del router (DeepSeek routing)">router ${_fmtUsd(data.router_cost_usd)}</span>` : ''}
        </div>
        <div class="detail-section">
          <label>Tarea enviada</label>
          <pre>${escHtml(data.task || data.task_preview || "(sin texto)")}</pre>
        </div>
        <div class="detail-section">
          <label>Respuesta del modelo</label>
          <pre>${escHtml(data.response || "(sin respuesta aún)")}</pre>
        </div>
        <div class="detail-section">
          <label>Razón de ruteo</label>
          <p class="detail-text">${escHtml(data.routing_reason || "—")}</p>
        </div>
        ${data.cache_read_tokens ? `<div class="detail-section">
          <label>Cache Claude</label>
          <p class="detail-text">
            Leídos: <strong style="color:#38bdf8">${data.cache_read_tokens}</strong> tokens
            ${data.cache_creation_tokens ? ` · Escritos: <strong style="color:#22c55e">${data.cache_creation_tokens}</strong>` : ''}
          </p>
        </div>` : ''}
        ${data.alignments && data.alignments.length ? `<div class="detail-section">
          <label>Checkpoints de alineación</label>
          <table style="width:100%;font-size:12px;border-collapse:collapse">
            <thead><tr class="detail-thead-row">
              <th class="td-sm">Hora</th>
              <th class="td-sm">Checkpoint</th>
              <th class="td-sm">Agente</th>
              <th class="td-sm" style="text-align:center">OK</th>
              <th class="td-sm">Mensaje</th>
            </tr></thead>
            <tbody>
              ${data.alignments.map(a => `<tr class="detail-tbody-row">
                <td class="td-sm-ts">${escHtml(a.ts ? new Date(a.ts).toLocaleString("es",{hour12:false,day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : '—')}</td>
                <td class="td-sm-text">${escHtml(a.checkpoint || '—')}</td>
                <td class="td-sm-muted">${escHtml(a.agent || '—')}</td>
                <td class="td-sm" style="text-align:center">${a.confirmed ? '<span style="color:#22c55e;font-weight:700;font-size:14px">✓</span>' : '<span style="color:#f87171;font-weight:700;font-size:14px">✗</span>'}</td>
                <td class="td-sm-muted">${escHtml(a.message || '')}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>` : ''}
        ${data.tool_calls && data.tool_calls.length ? `<div class="detail-section">
          <label>Herramientas invocadas</label>
          <table style="width:100%;font-size:12px;border-collapse:collapse">
            <thead><tr class="detail-thead-row">
              <th class="td-sm">Hora</th>
              <th class="td-sm">Herramienta</th>
              <th class="td-sm" style="text-align:center">Estado</th>
              <th class="td-sm" style="text-align:right">ms</th>
              <th class="td-sm">Salida</th>
            </tr></thead>
            <tbody>
              ${data.tool_calls.map(tc => `<tr class="detail-tbody-row">
                <td class="td-sm-ts">${escHtml(tc.ts ? new Date(tc.ts).toLocaleString("es",{hour12:false,day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : '—')}</td>
                <td class="td-sm-mono">${escHtml(tc.tool_name || '—')}</td>
                <td class="td-sm" style="text-align:center"><span style="font-size:10px;padding:2px 7px;border-radius:20px;background:${tc.status==='ok'?'rgba(34,197,94,0.12)':'rgba(248,113,113,0.12)'};color:${tc.status==='ok'?'#22c55e':'#f87171'};font-weight:600">${escHtml(tc.status || '—')}</span></td>
                <td class="td-sm text-muted" style="text-align:right;font-variant-numeric:tabular-nums">${safeNumber(tc.duration_ms)}</td>
                <td class="td-sm-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(tc.output ? String(tc.output).slice(0,80) : '')}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>` : ''}
        ${data.context_hits && data.context_hits.length ? `<div class="detail-section">
          <label>Contexto RAG utilizado</label>
          <table style="width:100%;font-size:12px;border-collapse:collapse">
            <thead><tr class="detail-thead-row">
              <th class="td-sm">Coleccion</th>
              <th class="td-sm">Fuente</th>
              <th class="td-sm" style="text-align:right">Score</th>
            </tr></thead>
            <tbody>
              ${data.context_hits.map(h => '<tr class="detail-tbody-row">' +
                '<td class="td-sm-muted">' + escHtml(h.collection || 'docs') + '</td>' +
                '<td class="td-sm-mono" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(h.source || '') + '</td>' +
                '<td class="td-sm text-muted" style="text-align:right;font-variant-numeric:tabular-nums">' + (Number.isFinite(Number(h.score)) ? Number(h.score).toFixed(4) : '—') + '</td>' +
              '</tr>').join('')}
            </tbody>
          </table>
        </div>` : ''}
        <div class="detail-section" style="padding-top:8px;border-top:1px solid var(--border-faint)">
          <label>Evaluacion del run</label>
          <div style="display:flex;gap:8px;margin-top:4px">
            <button class="btn btn-secondary rate-btn" data-run="${Number(data.id)}" data-rating="useful"
              style="font-size:13px;padding:5px 14px;${data.rating==='useful'?'opacity:1;border-color:#22c55e;color:#22c55e':'opacity:0.4'}"
              onclick="rateRun(${Number(data.id)},'useful')">Util</button>
            <button class="btn btn-secondary rate-btn" data-run="${Number(data.id)}" data-rating="partial"
              style="font-size:13px;padding:5px 14px;${data.rating==='partial'?'opacity:1;border-color:#f59e0b;color:#f59e0b':'opacity:0.4'}"
              onclick="rateRun(${Number(data.id)},'partial')">Parcial</button>
            <button class="btn btn-secondary rate-btn" data-run="${Number(data.id)}" data-rating="wrong"
              style="font-size:13px;padding:5px 14px;${data.rating==='wrong'?'opacity:1;border-color:#f87171;color:#f87171':'opacity:0.4'}"
              onclick="rateRun(${Number(data.id)},'wrong')">Incorrecto</button>
            ${data.rating ? '<button class="btn btn-secondary" style="font-size:11px;opacity:0.5;padding:5px 10px" onclick="rateRun(' + Number(data.id) + ',\'\')">Quitar</button>' : ''}
          </div>
        </div>
      `;
    })
    .catch(() => { content.innerHTML = '<p style="color:#ef4444;font-size:13px">Error al cargar detalle.</p>'; });
}

function rateRun(runId, rating) {
  const btns = document.querySelectorAll(".rate-btn[data-run='" + runId + "']");
  btns.forEach(b => { b.disabled = true; });
  postJson("/rate-run", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({run_id: runId, rating: rating}),
  })
  .then(r => r.json())
  .then(d => {
    btns.forEach(b => {
      const active = b.dataset.rating === (d.rating || "");
      b.style.opacity = active ? "1" : "0.35";
      b.disabled = false;
    });
  })
  .catch(() => { btns.forEach(b => { b.disabled = false; }); });
}

function closeDetail(e) {
  if (e && e.target !== document.getElementById("detailOverlay")) return;
  document.getElementById("detailOverlay").classList.remove("open");
}

function toggleSender() {
  document.getElementById("senderPanel").classList.toggle("open");
}

function submitTask() {
  const project = document.getElementById("senderProject").value;
  const task    = document.getElementById("senderTask").value.trim();
  const model   = document.getElementById("senderModel").value;
  const status  = document.getElementById("senderStatus");
  if (!project) { status.textContent = "Seleccioná un proyecto."; return; }
  if (!task)    { status.textContent = "La tarea no puede estar vacía."; return; }
  status.innerHTML = '<span class="spinner"></span> Enviando...';
  postJson("/run", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project, task, model: model || undefined}),
  })
  .then(r => r.json())
  .then(d => {
    status.textContent = "Run #" + d.run_id + " enviado.";
    document.getElementById("senderTask").value = "";
  })
  .catch(() => { status.textContent = "Error al enviar."; });
}
