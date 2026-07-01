"""JavaScript del dashboard."""

from __future__ import annotations


def _build_js() -> str:
    return """\n
// ── Runs table state ─────────────────────────────────────────────────────────
// var (no let) para que onclick attrs del HTML puedan mutar las variables desde
// el scope global. Con let, onclick crea window._runsPage=N pero renderRunsTable
// sigue leyendo la let del closure del script, que nunca cambia.
var _runsPage = 0;
var _runsPageSize = 10;
var _runsFilterProject = "";
var _runsFilterModel = "";

function _fmtRunTs(iso) {
  try {
    return new Date(iso).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
  } catch { return (iso||"").slice(0,16); }
}
function _fmtRunDur(ms) {
  if (ms == null) return "—";
  if (ms >= 3600000) return (ms/3600000).toFixed(1)+"h";
  if (ms >= 60000)   return (ms/60000).toFixed(1)+"m";
  if (ms >= 1000)    return (ms/1000).toFixed(1)+"s";
  return ms+"ms";
}
function _fmtRunTokens(inp,out) {
  if (inp==null && out==null) return "—";
  const t=(inp||0)+(out||0);
  return t>=1000 ? Math.floor(t/1000)+"K" : String(t);
}
function _fmtUsd(v, dec) {
  if (dec == null) dec = 4;
  if (v == null || v === "") return "—";
  const n = parseFloat(v);
  if (isNaN(n)) return "—";
  if (n > 0 && n < 0.0001 && dec >= 4) return "<0,0001 USD";
  return n.toLocaleString("es-CL", {minimumFractionDigits: dec, maximumFractionDigits: dec}) + " USD";
}
function _fmtRunCost(v) {
  return _fmtUsd(v, 4);
}
function _fmtRunCache(cr,inp) {
  if (!cr) return "—";
  const total = (inp||0) + cr;
  return Math.round(cr/total*100)+"%";
}

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
    return `<tr data-run-id="${r.id}" onclick="openDetail(${r.id})" style="cursor:pointer">
      <td class="td-ts">${_fmtRunTs(r.ts)}</td>
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

function _buildPagination(page, totalPages, pageSize, cbPrev, cbNext, cbSize10, cbSize25, cbSize50, cbSize100) {
  const sizes = [[10,cbSize10],[25,cbSize25],[50,cbSize50],[100,cbSize100]];
  const btns = sizes.map(([n,cb]) =>
    `<button class="pg-btn${n===pageSize?' pg-btn-active':''}" onclick="${cb}">${n}</button>`
  ).join("");
  return `<div class="pagination-bar">
    <button class="pg-btn" onclick="${cbPrev}" ${page<=0?'disabled':''}>← Ant.</button>
    <span style="font-size:12px;color:var(--text-muted);padding:0 4px">Pág. ${page+1} / ${totalPages}</span>
    <button class="pg-btn" onclick="${cbNext}" ${page>=totalPages-1?'disabled':''}>Sig. →</button>
    <span style="font-size:11px;color:var(--text-faint);margin-left:6px">Filas:</span>
    ${btns}
  </div>`;
}

// ── Proyectos pagination ──────────────────────────────────────────────────────
// var (no const) — mismo motivo que los runs: onclick attrs necesitan mutar estas
// variables desde el scope global; const las hace inaccesibles desde onclick.
var _inspPages = {};
var _inspSizes = {};

function mkTablePaged(id, title, rows, cols) {
  if (!_inspPages[id]) _inspPages[id] = 0;
  if (!_inspSizes[id]) _inspSizes[id] = 10;
  const n = (rows||[]).length;
  if (!n) return `<div class="panel" style="margin-bottom:16px"><h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">(0)</span></h2><p class="text-faint" style="font-size:13px">Sin registros.</p></div>`;
  const ps = _inspSizes[id];
  const tp = Math.max(1,Math.ceil(n/ps));
  if (_inspPages[id]>=tp) _inspPages[id]=tp-1;
  const pg = _inspPages[id];
  const slice = rows.slice(pg*ps, pg*ps+ps);
  const ths = cols.map(c=>`<th style="text-align:left;padding:7px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px">${c.label}</th>`).join("");
  const trs = slice.map(r=>`<tr style="border-bottom:1px solid var(--border-faint)">${
    cols.map(c=>{
      const val=r[c.key]??"—";
      const sval=c.fmt?c.fmt(val):String(val);
      const display=c.max&&sval.length>c.max?sval.slice(0,c.max)+"…":sval;
      return `<td style="padding:7px 10px;font-size:12px;color:${c.color||"var(--text-secondary)"};${c.mono?"font-family:'JetBrains Mono',monospace":""}">${escHtml(display)}</td>`;
    }).join("")
  }</tr>`).join("");
  const pgHtml = _buildPagination(pg, tp, ps,
    `_inspPages['${id}']=${pg-1};reloadProyectos()`,
    `_inspPages['${id}']=${pg+1};reloadProyectos()`,
    `_inspSizes['${id}']=10;_inspPages['${id}']=0;reloadProyectos()`,
    `_inspSizes['${id}']=25;_inspPages['${id}']=0;reloadProyectos()`,
    `_inspSizes['${id}']=50;_inspPages['${id}']=0;reloadProyectos()`,
    `_inspSizes['${id}']=100;_inspPages['${id}']=0;reloadProyectos()`
  );
  return `<div class="panel" style="margin-bottom:16px;overflow-x:auto">
    <h2>${title} <span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)">${n} filas</span></h2>
    <table><thead><tr style="background:var(--bg-elevated);border-bottom:1px solid var(--border)">${ths}</tr></thead><tbody>${trs}</tbody></table>
    ${pgHtml}
  </div>`;
}

// ── Context actions ───────────────────────────────────────────────────────────
let _ctxStatusFilter = "all";

function setCtxFilter(status) {
  _ctxStatusFilter = status || "all";
  document.querySelectorAll(".ctx-filter-btn").forEach(b => b.classList.remove("pg-btn-active"));
  const btn = document.getElementById("ctx-filter-" + _ctxStatusFilter);
  if (btn) btn.classList.add("pg-btn-active");
  _refreshContexts();
}

function advanceStep(stepId, ctxId) {
  fetch("/advance-step",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_id:stepId})})
    .then(r=>r.json())
    .then(d=>{
      if (d.error){showToast("Error: "+d.error,true);return;}
      showToast(d.context_done?"Flujo completado":"Paso avanzado");
      _refreshContexts();
    }).catch(()=>showToast("Error de conexión",true));
}

function skipStep(stepId, ctxId) {
  fetch("/skip-step",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_id:stepId,reason:"omitido desde dashboard"})})
    .then(r=>r.json())
    .then(d=>{
      if (d.error){showToast("Error: "+d.error,true);return;}
      showToast("Paso omitido");
      _refreshContexts();
    }).catch(()=>showToast("Error de conexión",true));
}

function runContext(btn) {
  const project = btn.dataset.project;
  const task    = btn.dataset.task;
  if (!project || !task) { showToast("Sin proyecto o tarea definida", true); return; }
  btn.disabled = true;
  btn.textContent = "…";
  fetch("/run", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({project, task})})
    .then(r => r.json())
    .then(d => {
      if (d.error) { showToast("Error: " + d.error, true); btn.disabled = false; btn.textContent = "▶ Ejecutar"; return; }
      showToast("Run #" + d.run_id + " enviado — " + escHtml(project));
      btn.disabled = false;
      btn.textContent = "▶ Ejecutar";
    })
    .catch(() => { showToast("Error de conexión", true); btn.disabled = false; btn.textContent = "▶ Ejecutar"; });
}

function deleteContext(ctxId, title) {
  showConfirmModal(
    "Eliminar contexto",
    "Se eliminarán permanentemente el contexto <strong>" + escHtml(title) + "</strong>, todos sus pasos, alineamientos y tool calls registrados.<br><br>Los runs históricos se conservan pero perderán la referencia al paso.",
    function() {
      fetch("/context/" + ctxId + "/delete", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
        .then(r => r.json())
        .then(d => {
          if (d.error) { showToast("Error: " + d.error, true); return; }
          showToast("Contexto eliminado — " + (d.steps||0) + " paso(s) borrado(s)");
          _refreshContexts();
        })
        .catch(() => showToast("Error de conexión", true));
    },
    {okLabel: "Eliminar", okDanger: true}
  );
}

function _refreshContexts() {
  const params = [];
  if (_runsFilterProject) params.push("project="+encodeURIComponent(_runsFilterProject));
  params.push("status="+encodeURIComponent(_ctxStatusFilter||"all"));
  fetch("/contexts-html?"+params.join("&"))
    .then(r=>r.text())
    .then(html=>{
      const el=document.getElementById("contextsSection");
      if(el){const tmp=document.createElement("div");tmp.innerHTML=html;el.replaceWith(tmp.firstChild||el);}
    }).catch(()=>{});
}

// ── Context detail overlay ───────────────────────────────────────────────────
function openContextDetail(ctxId) {
  const overlay = document.getElementById("ctxDetailOverlay");
  const content = document.getElementById("ctxDetailContent");
  overlay.classList.add("open");
  content.innerHTML='<p class="text-muted" style="font-size:13px"><span class="spinner"></span> Cargando...</p>';
  fetch("/context/"+ctxId)
    .then(r=>r.json())
    .then(data=>{
      const STEP_CLR={pending:"#71717a",in_progress:"#38bdf8",completed:"#22c55e",blocked:"#f87171",skipped:"#52525b"};
      const stepsHtml=(data.steps||[]).map(s=>{
        const sc=STEP_CLR[s.status]||"#71717a";
        const aligns=(s.alignments||[]).map(a=>`<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border-faint);display:flex;gap:8px">
          <span style="color:var(--text-faint);white-space:nowrap">${a.ts?new Date(a.ts).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"—"}</span>
          <span style="color:${a.confirmed?"#22c55e":"#f87171"};font-weight:700">${a.confirmed?"✓":"✗"}</span>
          <span style="color:var(--text-secondary)">${escHtml(a.checkpoint||"")}</span>
          <span style="color:var(--text-faint)">${escHtml(a.agent||"")}</span>
        </div>`).join("") || '<span style="font-size:11px;color:var(--text-faint)">Sin alineamientos.</span>';
        const tools=(s.tool_calls||[]).map(tc=>`<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border-faint);display:flex;gap:8px">
          <span style="color:var(--text-faint);white-space:nowrap">${tc.ts?new Date(tc.ts).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"—"}</span>
          <span style="font-family:'JetBrains Mono',monospace;color:var(--text-primary)">${escHtml(tc.tool_name||"")}</span>
          <span style="color:${tc.status==="ok"?"#22c55e":"#f87171"}">${escHtml(tc.status||"")}</span>
          <span style="color:var(--text-faint)">${tc.duration_ms!=null?tc.duration_ms+"ms":""}</span>
        </div>`).join("") || '<span style="font-size:11px;color:var(--text-faint)">Sin tool calls.</span>';
        return `<div style="margin-bottom:14px;padding:10px;background:var(--bg-elevated);border-radius:10px;border-left:3px solid ${sc}">
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
            <span style="font-size:11px;font-weight:700;color:var(--text-faint);font-family:'JetBrains Mono',monospace">${s.order_idx||"?"}</span>
            <span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1">${escHtml(s.title||"")}</span>
            <span style="font-size:10px;background:rgba(0,0,0,.2);color:${sc};padding:2px 8px;border-radius:20px;font-weight:600">${escHtml(s.status||"")}</span>
          </div>
          <div style="margin-bottom:6px"><span style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px">Alineamientos</span><div style="margin-top:4px">${aligns}</div></div>
          <div><span style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px">Tool Calls</span><div style="margin-top:4px">${tools}</div></div>
        </div>`;
      }).join("") || '<p class="text-muted" style="font-size:13px">Sin pasos.</p>';
      const CTX_CLR={active:"#22c55e",programado:"#818cf8",completed:"#71717a",abandoned:"#f87171"};
      const cs=CTX_CLR[data.status||"active"]||"#71717a";
      content.innerHTML=`
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
          <span class="chip-mono">#${data.id}</span>
          <span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1">${escHtml(data.title||"")}</span>
          <span style="font-size:10px;background:rgba(0,0,0,.2);color:${cs};padding:2px 8px;border-radius:20px;font-weight:600">${escHtml(data.status||"")}</span>
        </div>
        ${data.description?`<p style="font-size:12px;color:var(--text-muted);margin-bottom:14px">${escHtml(data.description)}</p>`:""}
        <div class="detail-section"><label>Pasos</label>${stepsHtml}</div>
      `;
    }).catch(()=>{content.innerHTML='<p style="color:#ef4444;font-size:13px">Error al cargar.</p>';});
}

function closeCtxDetail(e) {
  if (e && e.target !== document.getElementById("ctxDetailOverlay")) return;
  document.getElementById("ctxDetailOverlay").classList.remove("open");
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

const evtSource = new EventSource("/events");
evtSource.addEventListener("ctx_updated", e => {
  const d = JSON.parse(e.data);
  _refreshContexts();
});

evtSource.addEventListener("run_started", e => {
  const d = JSON.parse(e.data);
  prependPendingRow(d);
});
evtSource.addEventListener("run_done", e => {
  const d = JSON.parse(e.data);
  updateRow(d);
  showToast("Run #" + d.run_id + " completado — " + (d.provider || "?") + " " + (d.cost_usd ? _fmtUsd(d.cost_usd) : ""));
});
evtSource.addEventListener("run_failed", e => {
  const d = JSON.parse(e.data);
  markFailed(d);
  showToast("Run #" + d.run_id + " falló: " + d.error, true);
});
evtSource.addEventListener("budget_warning", e => {
  const d = JSON.parse(e.data);
  updateBudgetGauge(d);
});

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
  if (!runId) return;
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
          <span class="chip-mono">#${data.id}</span>
          <span style="background:${provBg};color:${provColor};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600">${escHtml(data.provider)}</span>
          <span class="chip-mono">${escHtml(data.model ? data.model.split('/').pop() : '—')}</span>
          <span class="chip">${data.duration_ms ? (data.duration_ms/1000).toFixed(1)+"s" : "—"}</span>
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
                <td class="td-sm-ts">${a.ts ? new Date(a.ts).toLocaleString("es",{hour12:false,day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : '—'}</td>
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
                <td class="td-sm-ts">${tc.ts ? new Date(tc.ts).toLocaleString("es",{hour12:false,day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : '—'}</td>
                <td class="td-sm-mono">${escHtml(tc.tool_name || '—')}</td>
                <td class="td-sm" style="text-align:center"><span style="font-size:10px;padding:2px 7px;border-radius:20px;background:${tc.status==='ok'?'rgba(34,197,94,0.12)':'rgba(248,113,113,0.12)'};color:${tc.status==='ok'?'#22c55e':'#f87171'};font-weight:600">${escHtml(tc.status || '—')}</span></td>
                <td class="td-sm text-muted" style="text-align:right;font-variant-numeric:tabular-nums">${tc.duration_ms != null ? tc.duration_ms : '—'}</td>
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
                '<td class="td-sm text-muted" style="text-align:right;font-variant-numeric:tabular-nums">' + (h.score != null ? h.score.toFixed(4) : '—') + '</td>' +
              '</tr>').join('')}
            </tbody>
          </table>
        </div>` : ''}
        <div class="detail-section" style="padding-top:8px;border-top:1px solid var(--border-faint)">
          <label>Evaluacion del run</label>
          <div style="display:flex;gap:8px;margin-top:4px">
            <button class="btn btn-secondary rate-btn" data-run="${data.id}" data-rating="useful"
              style="font-size:13px;padding:5px 14px;${data.rating==='useful'?'opacity:1;border-color:#22c55e;color:#22c55e':'opacity:0.4'}"
              onclick="rateRun(${data.id},'useful')">Util</button>
            <button class="btn btn-secondary rate-btn" data-run="${data.id}" data-rating="partial"
              style="font-size:13px;padding:5px 14px;${data.rating==='partial'?'opacity:1;border-color:#f59e0b;color:#f59e0b':'opacity:0.4'}"
              onclick="rateRun(${data.id},'partial')">Parcial</button>
            <button class="btn btn-secondary rate-btn" data-run="${data.id}" data-rating="wrong"
              style="font-size:13px;padding:5px 14px;${data.rating==='wrong'?'opacity:1;border-color:#f87171;color:#f87171':'opacity:0.4'}"
              onclick="rateRun(${data.id},'wrong')">Incorrecto</button>
            ${data.rating ? '<button class="btn btn-secondary" style="font-size:11px;opacity:0.5;padding:5px 10px" onclick="rateRun(' + data.id + ',\\'\\')">Quitar</button>' : ''}
          </div>
        </div>
      `;
    })
    .catch(() => { content.innerHTML = '<p style="color:#ef4444;font-size:13px">Error al cargar detalle.</p>'; });
}

function rateRun(runId, rating) {
  const btns = document.querySelectorAll(".rate-btn[data-run='" + runId + "']");
  btns.forEach(b => { b.disabled = true; });
  fetch("/rate-run", {
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

function toggleContextForm() {
  switchTab("flujos");
}

let _ctxStepCount = 0;
function addCtxStep() {
  _ctxStepCount++;
  const container = document.getElementById("ctxSteps");
  const row = document.createElement("div");
  row.style.cssText = "display:flex;gap:8px;margin-bottom:8px;align-items:center";
  row.innerHTML = `
    <input type="text" placeholder="Título del paso..." style="flex:1" class="ctx-step-title">
    <select class="ctx-step-provider">
      <option value="">auto</option>
      <option value="claude">claude</option>
      <option value="deepseek">deepseek</option>
      <option value="openai">openai</option>
    </select>
    <button onclick="this.parentElement.remove()" class="close-btn" title="Quitar paso">✕</button>
  `;
  container.appendChild(row);
}

function submitContext() {
  const project = document.getElementById("ctxProject").value;
  const title   = document.getElementById("ctxTitle").value.trim();
  const desc    = document.getElementById("ctxDesc").value.trim();
  const status  = document.getElementById("ctxStatus");
  if (!project) { status.textContent = "Seleccioná un proyecto."; return; }
  if (!title)   { status.textContent = "El título no puede estar vacío."; return; }
  const steps = Array.from(document.querySelectorAll("#ctxSteps > div")).map(row => ({
    title:    row.querySelector(".ctx-step-title").value.trim(),
    provider: row.querySelector(".ctx-step-provider").value,
  })).filter(s => s.title);
  status.innerHTML = '<span class="spinner"></span> Creando...';
  fetch("/create-context", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({project, title, description: desc, steps}),
  })
  .then(r => r.json())
  .then(d => {
    if (d.error) { status.textContent = "Error: " + d.error; return; }
    status.textContent = "Contexto #" + d.context_id + " creado con " + (d.steps || []).length + " paso(s).";
    document.getElementById("ctxTitle").value = "";
    document.getElementById("ctxDesc").value = "";
    document.getElementById("ctxSteps").innerHTML = "";
    _ctxStepCount = 0;
    showToast("Contexto '" + d.title + "' creado para " + d.project);
  })
  .catch(() => { status.textContent = "Error al crear."; });
}

function submitTask() {
  const project = document.getElementById("senderProject").value;
  const task    = document.getElementById("senderTask").value.trim();
  const model   = document.getElementById("senderModel").value;
  const status  = document.getElementById("senderStatus");
  if (!project) { status.textContent = "Seleccioná un proyecto."; return; }
  if (!task)    { status.textContent = "La tarea no puede estar vacía."; return; }
  status.innerHTML = '<span class="spinner"></span> Enviando...';
  fetch("/run", {
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

// ── Modal de confirmación reutilizable ─────────────────────────────────────
let _confirmModalCb = null;

function showConfirmModal(title, body, onConfirm, opts = {}) {
  const { okLabel = "Confirmar", okDanger = false } = opts;
  document.getElementById("confirmModalTitle").textContent = title;
  document.getElementById("confirmModalBody").innerHTML = body;
  const okBtn = document.getElementById("confirmModalOk");
  okBtn.textContent = okLabel;
  okBtn.style.background = okDanger ? "#ef4444" : "";
  okBtn.style.color = okDanger ? "#fff" : "";
  _confirmModalCb = onConfirm;
  document.getElementById("confirmModal").classList.add("open");
}

function closeConfirmModal() {
  document.getElementById("confirmModal").classList.remove("open");
  _confirmModalCb = null;
}

function _confirmModalOk() {
  const cb = _confirmModalCb;
  closeConfirmModal();
  if (cb) cb();
}

function _confirmModalBackdrop(e) {
  if (e.target === document.getElementById("confirmModal")) closeConfirmModal();
}
// ────────────────────────────────────────────────────────────────────────────

function showToast(msg, isError) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.background = isError ? "#ef4444" : "";
  t.style.display = "block";
  setTimeout(() => { t.style.display = "none"; }, 4000);
}

// ── Theme selector ────────────────────────────────────────────────────────────
function setTheme(name) {
  if (!name || name === "dark") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", name);
  }
  localStorage.setItem("theme", name || "dark");
  const sel = document.getElementById("themeSelect");
  if (sel) sel.value = name || "dark";
}

(function() {
  const saved = localStorage.getItem("theme") || "dark";
  const sel = document.getElementById("themeSelect");
  if (sel) sel.value = saved;
})();

function escHtml(s) {
  if (s == null) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── Activity bar ─────────────────────────────────────────────────────────────
let _actOpen = false;
let _actUserClosed = false;
const _traceMap = {};

evtSource.addEventListener("trace", e => _handleTrace(JSON.parse(e.data)));

function toggleActivity() {
  _actOpen = !_actOpen;
  _actUserClosed = !_actOpen;
  document.getElementById("activity-log").style.display = _actOpen ? "block" : "none";
  document.getElementById("act-toggle").textContent  = _actOpen ? "▲" : "▼";
}

function _traceKey(d) {
  return ("tr_" + d.name + (d.run_id != null ? "_" + d.run_id : "")).replace(/[^a-z0-9_]/gi, "_");
}

function _fmtTs(iso) {
  try { return new Date(iso).toLocaleTimeString("es", {hour12:false, fractionalSecondDigits:2}); }
  catch { return iso.slice(11, 22); }
}

function _handleTrace(d) {
  const key  = _traceKey(d);
  const log  = document.getElementById("activity-log");
  const dot  = document.getElementById("act-dot");
  const runLabel = d.run_id != null ? "#" + d.run_id : "";
  const detLabel = d.detail ? " · " + escHtml(d.detail) : "";

  if (d.status === "running") {
    const row = document.createElement("div");
    row.id = key;
    row.className = "tr-row tr-running";
    row.innerHTML =
      `<span class="tr-ts">${_fmtTs(d.ts)}</span>` +
      `<span class="tr-run">${escHtml(runLabel)}</span>` +
      `<span class="tr-icon">▶</span>` +
      `<span class="tr-name">${escHtml(d.name)}${detLabel}</span>` +
      `<span class="tr-dur"></span>`;
    _traceMap[key] = row;
    log.insertBefore(row, log.firstChild);
    while (log.children.length > 80) log.removeChild(log.lastChild);
    if (!_actOpen && !_actUserClosed) { _actOpen = true; log.style.display = "block"; document.getElementById("act-toggle").textContent = "▲"; }
  } else {
    const icon = d.status === "done" ? "✓" : "✗";
    const dur  = d.duration_ms != null ? d.duration_ms + "ms" : "";
    const cls  = "tr-row tr-" + d.status;
    const existing = _traceMap[key] || document.getElementById(key);
    if (existing) {
      existing.className = cls;
      existing.querySelector(".tr-icon").textContent = icon;
      existing.querySelector(".tr-dur").textContent  = dur;
      delete _traceMap[key];
    }
  }

  const icon2 = d.status === "done" ? "✓" : d.status === "error" ? "✗" : "▶";
  const dur2  = d.duration_ms ? " " + d.duration_ms + "ms" : "";
  document.getElementById("act-summary").textContent = icon2 + " " + d.name + (runLabel ? " " + runLabel : "") + dur2;
  dot.classList.add("live");
  dot.classList.remove("pulse");
  void dot.offsetWidth;
  dot.classList.add("pulse");
}

// ── Actions menu (doctor / fix / sync / index) ───────────────────────────────
function _actAppend(text, level) {
  const log  = document.getElementById("activity-log");
  const icon = level==="ok"?"✓":level==="fail"?"✗":level==="warn"?"⚠":"·";
  const cls  = level==="ok"?"tr-done":level==="fail"?"tr-error":level==="warn"?"tr-warn":"tr-running";
  const ts   = new Date().toLocaleTimeString("es", {hour12:false});
  const row  = document.createElement("div");
  row.className = "tr-row " + cls;
  row.innerHTML =
    `<span class="tr-ts">${ts}</span>` +
    `<span class="tr-run"></span>` +
    `<span class="tr-icon">${icon}</span>` +
    `<span class="tr-name">${escHtml(text)}</span>` +
    `<span class="tr-dur"></span>`;
  log.insertBefore(row, log.firstChild);
  while (log.children.length > 80) log.removeChild(log.lastChild);
  if (!_actOpen && !_actUserClosed) { _actOpen=true; log.style.display="block"; document.getElementById("act-toggle").textContent="▲"; }
  document.getElementById("act-dot").classList.add("live");
  document.getElementById("act-summary").textContent = icon + "  " + text;
}

function _actBusy(btn, busy, label) {
  if (busy) { btn.disabled=true; btn.classList.add("running"); btn.dataset.lbl=btn.textContent; btn.textContent="…"; }
  else       { btn.disabled=false; btn.classList.remove("running"); btn.textContent=label||btn.dataset.lbl||""; }
}

async function runDoctor(btn) {
  _actBusy(btn, true);
  _actAppend("doctor — diagnosticando...", "info");
  try {
    const r = await fetch("/run-doctor", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    const d = await r.json();
    if (d.error) { _actAppend("doctor — " + d.error, "fail"); return; }
    (d.lines||[]).forEach(l => _actAppend(l.text, l.ok?"ok":l.fail?"fail":l.warn?"warn":"info"));
    _actAppend("doctor — " + d.issues + " error(es) · " + d.warnings + " advertencia(s)",
               d.issues>0?"fail":d.warnings>0?"warn":"ok");
  } catch(e) { _actAppend("doctor — " + e.message, "fail"); }
  finally { _actBusy(btn, false, "doctor"); }
}

async function runFix(btn, opts) {
  closeFixMenu();
  _actBusy(btn, true);
  const keys = Object.keys(opts||{}).filter(k=>opts[k]);
  _actAppend("fix — " + (keys.length ? "[" + keys.join(", ") + "]" : "básico") + "...", "info");
  try {
    const r = await fetch("/run-fix", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(opts||{})});
    const d = await r.json();
    if (d.error) { _actAppend("fix — " + d.error, "fail"); return; }
    (d.lines||[]).forEach(l => _actAppend(l.text, l.ok?"ok":l.fail?"fail":l.warn?"warn":"info"));
    _actAppend("fix — " + d.fixed + " mejora(s) aplicada(s)", d.fixed>0?"ok":"info");
  } catch(e) { _actAppend("fix — " + e.message, "fail"); }
  finally { _actBusy(btn, false, "fix"); }
}

async function runSync(btn) {
  _actBusy(btn, true);
  _actAppend("sync — importando Claude Code + Git...", "info");
  try {
    const [rcc, rg] = await Promise.all([
      fetch("/sync-cc",  {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"}),
      fetch("/sync-git", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"}),
    ]);
    const cc = await rcc.json(); const g = await rg.json();
    _actAppend("sync-cc — " + (cc.imported||0) + " sesión(es) importada(s)", (cc.imported||0)>0?"ok":"info");
    _actAppend("sync-git — " + (g.imported||0) + " commit(s) importado(s)",   (g.imported||0)>0?"ok":"info");
    if ((cc.imported||0)>0 && typeof renderRunsTable==="function") setTimeout(renderRunsTable, 800);
  } catch(e) { _actAppend("sync — " + e.message, "fail"); }
  finally { _actBusy(btn, false, "sync"); }
}

async function runIndexDocs(btn) {
  _actBusy(btn, true);
  const proj = (document.getElementById("senderProject")||document.querySelector("select[name=project]")||{}).value||"";
  if (!proj) { _actAppend("index — seleccioná un proyecto primero", "warn"); _actBusy(btn,false,"index"); return; }
  _actAppend("index — indexando " + proj + "...", "info");
  try {
    const r = await fetch("/index-docs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({project:proj})});
    const d = await r.json();
    if (d.error) { _actAppend("index — " + d.error, "fail"); return; }
    _actAppend("index — " + d.chunks + " chunks indexados para " + proj, "ok");
  } catch(e) { _actAppend("index — " + e.message, "fail"); }
  finally { _actBusy(btn, false, "index"); }
}

function toggleFixMenu(e) {
  e.stopPropagation();
  document.getElementById("fixMenu").classList.toggle("open");
}
function closeFixMenu() {
  const m = document.getElementById("fixMenu");
  if (m) m.classList.remove("open");
}
document.addEventListener("click", function(e) {
  if (!e.target.closest(".act-btn-wrap")) closeFixMenu();
});

let _proyectosLoaded = false;
let _metricsLoaded   = false;
function switchTab(name) {
  document.getElementById("tab-actividad").style.display  = name === "actividad"  ? "" : "none";
  document.getElementById("tab-flujos").style.display     = name === "flujos"     ? "" : "none";
  document.getElementById("tab-proyectos").style.display  = name === "proyectos"  ? "" : "none";
  document.getElementById("tab-metrics").style.display    = name === "metrics"    ? "" : "none";
  document.getElementById("tab-datos").style.display      = name === "datos"      ? "" : "none";
  document.getElementById("tab-config").style.display     = name === "config"     ? "" : "none";
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("tab-active"));
  document.getElementById("tab-btn-" + name).classList.add("tab-active");
  if (name === "proyectos" && !_proyectosLoaded) { _proyectosLoaded = true; loadProyectos(); }
  if (name === "flujos") _refreshContexts();
  if (name === "metrics" && !_metricsLoaded) { _metricsLoaded = true; loadMetrics(); }
  if (name === "datos" && !_datosLoaded) { _datosLoaded = true; loadDatos(); }
  if (name === "config" && !_configLoaded) { _configLoaded = true; loadConfig(); }
}

let _datosLoaded = false;
let _configLoaded = false;

// ── Datos ─────────────────────────────────────────────────────────────────────
function loadDatos() {
  const el = document.getElementById("datos-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Cargando...</p>';
  fetch("/clean-preview")
    .then(r => r.json())
    .then(data => renderDatos(data, el))
    .catch(e => { el.innerHTML = '<p style="color:#f87171">Error: ' + escHtml(String(e)) + '</p>'; });
}

// Providers que son auto-recuperables
const _RECOVERABLE_PROVIDERS = {
  "claude-code": { label: "Re-importable con sync-cc", color: "#22c55e" },
  "git":         { label: "Re-importable con sync-git", color: "#22c55e" },
};
function _provRecovery(providerName) {
  return _RECOVERABLE_PROVIDERS[providerName] || { label: "Sin respaldo — pérdida permanente", color: "#f87171" };
}
function _provBadge(providerName) {
  const r = _provRecovery(providerName);
  return '<span style="font-size:10px;padding:1px 6px;border-radius:8px;background:' + r.color + '22;color:' + r.color + ';white-space:nowrap">' + r.label + '</span>';
}
// Texto para el modal de confirmación de runs
function _runDeleteWarning(providers) {
  const nonRecov = (providers||[]).filter(x => !_RECOVERABLE_PROVIDERS[x.provider]);
  const recov    = (providers||[]).filter(x =>  _RECOVERABLE_PROVIDERS[x.provider]);
  let warn = '';
  if (nonRecov.length) {
    warn += '<div style="margin-top:10px;padding:8px 12px;border-radius:6px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3)">' +
      '<strong style="color:#f87171;font-size:12px">Sin respaldo:</strong>' +
      '<ul style="margin:4px 0 0 16px;padding:0;font-size:12px;color:#f87171">' +
      nonRecov.map(x => '<li>' + escHtml(x.provider) + ' (' + x.runs + ' runs)</li>').join('') +
      '</ul><span style="font-size:11px;color:var(--text-muted)">Estos runs no se pueden recuperar.</span></div>';
  }
  if (recov.length) {
    warn += '<div style="margin-top:8px;padding:8px 12px;border-radius:6px;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2)">' +
      '<strong style="color:#22c55e;font-size:12px">Recuperables:</strong>' +
      '<ul style="margin:4px 0 0 16px;padding:0;font-size:12px;color:var(--text-secondary)">' +
      recov.map(x => '<li>' + escHtml(x.provider) + ' (' + x.runs + ' runs) — ' + _provRecovery(x.provider).label + '</li>').join('') +
      '</ul></div>';
  }
  return warn;
}

function renderDatos(data, el) {
  const projects   = data.projects || [];
  const unmapped   = projects.filter(p => !p.registered);
  const mapped     = projects.filter(p => p.registered);
  const ctxByProj  = data.contexts_by_project || {};
  const chroma     = data.chroma || {};
  const fmtCost    = v => _fmtUsd(parseFloat(v) || 0, 2);

  // ── Panel 1: No mapeados ─────────────────────────────────────────────────
  const unmapRows = unmapped.map(p => {
    const provBadges = (p.providers||[]).map(x => _provBadge(x.provider)).join(' ');
    return '<tr style="border-bottom:1px solid var(--border-faint)">' +
      '<td style="padding:8px 10px;font-size:12px;font-family:monospace;color:var(--text-primary)">' + escHtml(p.project) + '</td>' +
      '<td style="padding:8px 10px;font-size:12px;color:var(--text-muted);text-align:right">' + p.runs + '</td>' +
      '<td style="padding:8px 10px;font-size:12px;color:#22c55e;text-align:right">' + fmtCost(p.cost) + '</td>' +
      '<td style="padding:8px 10px;font-size:11px;line-height:1.8">' + provBadges + '</td>' +
      '<td style="padding:8px 10px">' +
        '<button class="btn btn-secondary" style="font-size:11px;padding:3px 10px;color:#ef4444;border-color:#ef4444" ' +
        'data-proj="' + escHtml(p.project) + '" data-providers="' + escHtml(JSON.stringify(p.providers||[])) + '" onclick="cleanProject(this)">Eliminar</button>' +
      '</td>' +
    '</tr>';
  }).join('');

  // ── Panel 2: Mapeados — runs por provider ────────────────────────────────
  const mapRows = mapped.map(p => {
    const provOpts = (p.providers||[]).map(x =>
      '<option value="' + escHtml(x.provider) + '">' + escHtml(x.provider) + ' (' + x.runs + ')</option>'
    ).join('');
    const provBadges = (p.providers||[]).map(x => _provBadge(x.provider)).join(' ');
    return '<tr style="border-bottom:1px solid var(--border-faint)">' +
      '<td style="padding:8px 10px;font-size:12px;font-family:monospace;color:var(--text-primary)">' + escHtml(p.project) + '</td>' +
      '<td style="padding:8px 10px;font-size:12px;color:var(--text-muted);text-align:right">' + p.runs + '</td>' +
      '<td style="padding:8px 10px;font-size:12px;color:#22c55e;text-align:right">' + fmtCost(p.cost) + '</td>' +
      '<td style="padding:8px 10px;font-size:11px;line-height:1.8">' + provBadges + '</td>' +
      '<td style="padding:8px 10px;white-space:nowrap">' +
        '<select data-proj="' + escHtml(p.project) + '" data-providers="' + escHtml(JSON.stringify(p.providers||[])) + '" style="font-size:11px;margin-right:6px" class="clean-prov-sel">' +
          '<option value="">todos los providers</option>' + provOpts +
        '</select>' +
        '<button class="btn btn-secondary" style="font-size:11px;padding:3px 10px;color:#ef4444;border-color:#ef4444" ' +
        'data-proj="' + escHtml(p.project) + '" data-providers="' + escHtml(JSON.stringify(p.providers||[])) + '" onclick="cleanProjectWithSel(this)">Eliminar</button>' +
      '</td>' +
    '</tr>';
  }).join('');

  // ── Panel 3: ChromaDB ────────────────────────────────────────────────────
  const chromaDocs  = chroma.docs  || {};
  const chromaResp  = chroma.responses || {};
  const docsProjs   = Object.entries(chromaDocs.by_project  || {});
  const respProjs   = Object.entries(chromaResp.by_project  || {});

  const chromaDocsRows = docsProjs.map(([p, n]) =>
    '<tr style="border-bottom:1px solid var(--border-faint)">' +
    '<td style="padding:7px 10px;font-size:12px;font-family:monospace;color:var(--text-primary)">' + escHtml(p) + '</td>' +
    '<td style="padding:7px 10px;font-size:12px;color:var(--text-muted);text-align:right">' + n + '</td>' +
    '<td style="padding:7px 10px;font-size:11px;color:#22c55e">Re-indexable con "Indexar docs"</td>' +
    '<td style="padding:7px 10px">' +
      '<button class="btn btn-secondary" style="font-size:11px;padding:3px 10px;color:#f59e0b;border-color:#f59e0b" ' +
      'data-proj="' + escHtml(p) + '" onclick="purgeChromaDocs(this.dataset.proj, this)">Purgar</button>' +
    '</td>' +
    '</tr>'
  ).join('');

  const chromaRespRows = respProjs.map(([p, n]) =>
    '<tr style="border-bottom:1px solid var(--border-faint)">' +
    '<td style="padding:7px 10px;font-size:12px;font-family:monospace;color:var(--text-primary)">' + escHtml(p) + '</td>' +
    '<td style="padding:7px 10px;font-size:12px;color:var(--text-muted);text-align:right">' + n + '</td>' +
    '<td style="padding:7px 10px;font-size:11px;color:#f59e0b">Reconstruible re-indexando runs existentes</td>' +
    '<td style="padding:7px 10px">' +
      '<button class="btn btn-secondary" style="font-size:11px;padding:3px 10px;color:#f59e0b;border-color:#f59e0b" ' +
      'data-proj="' + escHtml(p) + '" onclick="purgeChromaResponses(this.dataset.proj, this)">Purgar</button>' +
    '</td>' +
    '</tr>'
  ).join('');

  // ── Panel 4: Flujos ──────────────────────────────────────────────────────
  const ctxProjList = Object.keys(ctxByProj);
  const ctxProjOpts = ctxProjList.map(p => '<option value="' + escHtml(p) + '">' + escHtml(p) + ' (' + ctxByProj[p].total + ')</option>').join('');
  const STATUS_LABELS = {active:'Activo', programado:'Programado', completed:'Completado', abandoned:'Abandonado'};

  el.innerHTML =
    '<div style="display:grid;gap:20px;max-width:1100px">' +

    // Panel 1 ─ No mapeados
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:4px">Proyectos no mapeados</h2>' +
    '<p class="text-muted" style="font-size:12px;margin-bottom:12px">Runs de proyectos sin ruta registrada. Los providers verdes son re-importables con <code>sync-cc</code> si después registrás el proyecto.</p>' +
    (unmapped.length ? (
      '<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">' +
        '<button class="btn btn-secondary" style="color:#ef4444;border-color:#ef4444;font-size:12px" onclick="cleanAllUnmapped(this)">Eliminar todos los no mapeados</button>' +
        '<span id="clean-unmapped-status" class="text-muted" style="font-size:12px"></span>' +
      '</div>' +
      '<table style="width:100%;border-collapse:collapse"><thead><tr style="background:var(--bg-elevated)">' +
        '<th style="padding:7px 10px;font-size:10px;text-align:left;text-transform:uppercase;letter-spacing:.5px">Proyecto</th>' +
        '<th style="padding:7px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">Runs</th>' +
        '<th style="padding:7px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">Costo</th>' +
        '<th style="padding:7px 10px;font-size:10px;text-align:left;text-transform:uppercase;letter-spacing:.5px">Recuperabilidad</th>' +
        '<th style="padding:7px 10px;font-size:10px"></th>' +
      '</tr></thead><tbody>' + unmapRows + '</tbody></table>'
    ) : '<p class="text-muted" style="font-size:12px">Todos los proyectos están mapeados. ✓</p>') +
    '</div>' +

    // Panel 2 ─ Runs registrados
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:4px">Runs por proyecto registrado</h2>' +
    '<p class="text-muted" style="font-size:12px;margin-bottom:12px">Seleccioná un provider antes de eliminar. Los providers en <span style="color:#f87171">rojo</span> no tienen respaldo.</p>' +
    (mapped.length ?
      '<table style="width:100%;border-collapse:collapse"><thead><tr style="background:var(--bg-elevated)">' +
        '<th style="padding:7px 10px;font-size:10px;text-align:left;text-transform:uppercase;letter-spacing:.5px">Proyecto</th>' +
        '<th style="padding:7px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">Runs</th>' +
        '<th style="padding:7px 10px;font-size:10px;text-align:right;text-transform:uppercase;letter-spacing:.5px">Costo</th>' +
        '<th style="padding:7px 10px;font-size:10px;text-align:left;text-transform:uppercase;letter-spacing:.5px">Recuperabilidad</th>' +
        '<th style="padding:7px 10px;font-size:10px">Acción</th>' +
      '</tr></thead><tbody>' + mapRows + '</tbody></table>'
    : '<p class="text-muted" style="font-size:12px">Sin proyectos registrados con runs.</p>') +
    '<p id="clean-mapped-status" class="text-muted" style="font-size:12px;margin-top:8px"></p>' +
    '</div>' +

    // Panel 3 ─ ChromaDB
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:4px">ChromaDB — vectores RAG</h2>' +
    '<p class="text-muted" style="font-size:12px;margin-bottom:14px">Purgar vectores no elimina los runs de la DB. Los docs son re-indexables; las respuestas se reconstruyen re-indexando los runs existentes.</p>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">' +

    '<div>' +
    '<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:8px">Docs (RAG) — ' + (chromaDocs.count||0) + ' vectores</div>' +
    (docsProjs.length ?
      '<table style="width:100%;border-collapse:collapse">' +
      '<thead><tr style="background:var(--bg-elevated)"><th style="padding:6px 10px;font-size:10px;text-align:left">Proyecto</th>' +
      '<th style="padding:6px 10px;font-size:10px;text-align:right">Chunks</th>' +
      '<th style="padding:6px 10px;font-size:10px">Estado</th><th></th></tr></thead>' +
      '<tbody>' + chromaDocsRows + '</tbody></table>' +
      '<div style="margin-top:10px">' +
      '<button class="btn btn-secondary" style="font-size:11px;color:#f59e0b;border-color:#f59e0b" onclick="purgeChromaDocs(null, this)">Purgar todos los docs</button>' +
      '</div>'
    : '<p class="text-muted" style="font-size:12px">Sin vectores de docs.</p>') +
    '</div>' +

    '<div>' +
    '<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:8px">Respuestas — ' + (chromaResp.count||0) + ' vectores</div>' +
    (respProjs.length ?
      '<table style="width:100%;border-collapse:collapse">' +
      '<thead><tr style="background:var(--bg-elevated)"><th style="padding:6px 10px;font-size:10px;text-align:left">Proyecto</th>' +
      '<th style="padding:6px 10px;font-size:10px;text-align:right">Vectores</th>' +
      '<th style="padding:6px 10px;font-size:10px">Estado</th><th></th></tr></thead>' +
      '<tbody>' + chromaRespRows + '</tbody></table>' +
      '<div style="margin-top:10px">' +
      '<button class="btn btn-secondary" style="font-size:11px;color:#f59e0b;border-color:#f59e0b" onclick="purgeChromaResponses(null, this)">Purgar todas las respuestas</button>' +
      '</div>'
    : '<p class="text-muted" style="font-size:12px">Sin vectores de respuestas.</p>') +
    '</div>' +

    '</div>' +
    '<p id="clean-chroma-status" class="text-muted" style="font-size:12px;margin-top:10px"></p>' +
    '</div>' +

    // Panel 4 ─ Flujos
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:4px">Flujos y pasos</h2>' +
    '<p class="text-muted" style="font-size:12px;margin-bottom:4px">Los flujos <strong>no tienen respaldo</strong> — se almacenan solo en SQLite y no se pueden recuperar tras eliminarlos.</p>' +
    (ctxProjList.length ? (
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px">' +
        '<select id="clean-ctx-proj" style="font-size:12px;min-width:160px">' +
          '<option value="">todos los proyectos</option>' + ctxProjOpts +
        '</select>' +
        '<select id="clean-ctx-status" style="font-size:12px">' +
          '<option value="">todos los estados</option>' +
          Object.entries(STATUS_LABELS).map(([v,l]) => '<option value="' + v + '">' + l + '</option>').join('') +
        '</select>' +
        '<button class="btn btn-secondary" style="color:#ef4444;border-color:#ef4444;font-size:12px" onclick="deleteContexts()">Eliminar contextos</button>' +
      '</div>' +
      '<div style="margin-top:12px;display:flex;flex-wrap:wrap;gap:10px">' +
        ctxProjList.map(p => {
          const info = ctxByProj[p];
          const byStatus = Object.entries(info.by_status||{})
            .map(([s,n]) => '<span style="font-size:10px;color:var(--text-muted)">' + (STATUS_LABELS[s]||s) + ': ' + n + '</span>')
            .join(' · ');
          return '<div style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-elevated)">' +
            '<div style="font-size:12px;font-family:monospace;color:var(--text-primary)">' + escHtml(p) + '</div>' +
            '<div style="font-size:12px;color:var(--text-muted)">' + info.total + ' contextos</div>' +
            '<div style="margin-top:3px">' + byStatus + '</div>' +
            '</div>';
        }).join('') +
      '</div>'
    ) : '<p class="text-muted" style="font-size:12px;margin-top:8px">Sin contextos registrados.</p>') +
    '<p id="clean-ctx-status" class="text-muted" style="font-size:12px;margin-top:10px"></p>' +
    '</div>' +

    '</div>';
}

function cleanAllUnmapped(btn) {
  // recopilar todos los providers de proyectos no mapeados desde las filas
  const allProvs = [];
  document.querySelectorAll('#datos-content tbody tr [data-providers]').forEach(el => {
    try { JSON.parse(el.dataset.providers || '[]').forEach(x => allProvs.push(x)); } catch(e) {}
  });
  const warn = _runDeleteWarning(allProvs);
  showConfirmModal(
    'Eliminar proyectos no mapeados',
    'Se eliminarán <strong>todos los runs</strong> de proyectos sin ruta registrada.' + warn,
    () => {
      btn.disabled = true;
      const st = document.getElementById('clean-unmapped-status');
      if (st) st.textContent = 'Eliminando...';
      fetch('/clean/unmapped', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
        .then(r => r.json())
        .then(d => {
          if (d.error) { showToast('Error: ' + d.error, true); if (st) st.textContent = ''; btn.disabled = false; return; }
          showToast('✓ ' + d.runs_deleted + ' runs eliminados');
          _datosLoaded = false;
          setTimeout(loadDatos, 600);
        })
        .catch(e => { showToast('Error: ' + e, true); btn.disabled = false; });
    },
    { okLabel: 'Eliminar todos', okDanger: true }
  );
}

function cleanProject(btn) {
  const proj = btn.dataset.proj;
  const providers = JSON.parse(btn.dataset.providers || '[]');
  const warn = _runDeleteWarning(providers);
  showConfirmModal(
    'Eliminar proyecto no mapeado',
    'Se eliminarán todos los runs de <strong>' + escHtml(proj) + '</strong>.' + warn,
    () => {
      btn.disabled = true;
      fetch('/clear-imports', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project: proj})})
        .then(r => r.json())
        .then(d => {
          if (d.error) { showToast('Error: ' + d.error, true); btn.disabled = false; return; }
          showToast('✓ ' + d.runs_deleted + ' runs eliminados');
          _datosLoaded = false;
          setTimeout(loadDatos, 600);
        })
        .catch(e => { showToast('Error: ' + e, true); btn.disabled = false; });
    },
    { okLabel: 'Eliminar', okDanger: true }
  );
}

function cleanProjectWithSel(btn) {
  const proj = btn.dataset.proj;
  const row  = btn.closest('tr');
  const sel  = row ? row.querySelector('.clean-prov-sel') : null;
  const prov = sel ? sel.value : '';
  const allProviders = JSON.parse(btn.dataset.providers || '[]');
  const filteredProvs = prov ? allProviders.filter(x => x.provider === prov) : allProviders;
  const desc = prov
    ? 'los runs de provider <strong>' + escHtml(prov) + '</strong> en <strong>' + escHtml(proj) + '</strong>'
    : 'todos los runs de <strong>' + escHtml(proj) + '</strong>';
  const warn = _runDeleteWarning(filteredProvs);
  showConfirmModal(
    'Limpiar runs',
    'Se eliminarán ' + desc + '.' + warn,
    () => {
      btn.disabled = true;
      const st = document.getElementById('clean-mapped-status');
      if (st) st.textContent = 'Eliminando...';
      fetch('/clear-imports', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: proj, provider: prov || undefined}),
      })
        .then(r => r.json())
        .then(d => {
          if (d.error) { showToast('Error: ' + d.error, true); if (st) st.textContent = ''; btn.disabled = false; return; }
          showToast('✓ ' + d.runs_deleted + ' runs eliminados');
          if (st) st.textContent = '';
          _datosLoaded = false;
          setTimeout(loadDatos, 600);
        })
        .catch(e => { showToast('Error: ' + e, true); btn.disabled = false; });
    },
    { okLabel: 'Eliminar', okDanger: true }
  );
}

function purgeChromaDocs(proj, btn) {
  const desc = proj ? 'los docs de <strong>' + escHtml(proj) + '</strong>' : '<strong>todos los proyectos</strong>';
  showConfirmModal(
    'Purgar vectores de docs',
    'Se eliminarán los vectores RAG de ' + desc + ' de ChromaDB.<br>' +
    '<span style="font-size:12px;color:#22c55e">✓ Recuperable: podés re-indexar con "Actualizar conocimiento" en Proyectos.</span>',
    () => {
      if (btn) btn.disabled = true;
      const st = document.getElementById('clean-chroma-status');
      if (st) st.textContent = 'Purgando...';
      fetch('/purge-chroma-docs', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: proj || null}),
      })
        .then(r => r.json())
        .then(d => {
          if (d.error) { showToast('Error: ' + d.error, true); if (btn) btn.disabled = false; return; }
          showToast('✓ ' + d.purged + ' vectores de docs eliminados');
          _datosLoaded = false;
          setTimeout(loadDatos, 600);
        })
        .catch(e => { showToast('Error: ' + e, true); if (btn) btn.disabled = false; });
    },
    { okLabel: 'Purgar', okDanger: false }
  );
}

function purgeChromaResponses(proj, btn) {
  const desc = proj ? 'las respuestas de <strong>' + escHtml(proj) + '</strong>' : '<strong>todos los proyectos</strong>';
  showConfirmModal(
    'Purgar vectores de respuestas',
    'Se eliminarán los vectores RAG de ' + desc + ' de ChromaDB.<br>' +
    '<span style="font-size:12px;color:#f59e0b">⚠ Semi-recuperable: se pueden reconstruir re-indexando los runs existentes en la DB.</span>',
    () => {
      if (btn) btn.disabled = true;
      const st = document.getElementById('clean-chroma-status');
      if (st) st.textContent = 'Purgando...';
      fetch('/purge-chroma-responses', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: proj || null}),
      })
        .then(r => r.json())
        .then(d => {
          if (d.error) { showToast('Error: ' + d.error, true); if (btn) btn.disabled = false; return; }
          showToast('✓ ' + d.purged + ' vectores de respuestas eliminados');
          _datosLoaded = false;
          setTimeout(loadDatos, 600);
        })
        .catch(e => { showToast('Error: ' + e, true); if (btn) btn.disabled = false; });
    },
    { okLabel: 'Purgar', okDanger: false }
  );
}

function deleteContexts() {
  const proj   = (document.getElementById('clean-ctx-proj')   || {}).value || '';
  const status = (document.getElementById('clean-ctx-status') || {}).value || '';
  const descProj   = proj   ? ' del proyecto <strong>' + escHtml(proj) + '</strong>'   : ' de <strong>todos los proyectos</strong>';
  const descStatus = status ? ' con estado <strong>' + escHtml(status) + '</strong>'   : '';
  showConfirmModal(
    'Eliminar contextos',
    'Se eliminarán los contextos y sus pasos' + descProj + descStatus + '.<br>' +
    '<div style="margin-top:10px;padding:8px 12px;border-radius:6px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3)">' +
    '<strong style="color:#f87171;font-size:12px">Sin respaldo — pérdida permanente.</strong><br>' +
    '<span style="font-size:11px;color:var(--text-muted)">Los contextos solo existen en SQLite y no se pueden recuperar.</span></div>',
    () => {
      const st = document.getElementById('clean-ctx-status');
      if (st) st.textContent = 'Eliminando...';
      fetch('/delete-contexts', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: proj || null, status: status || null}),
      })
        .then(r => r.json())
        .then(d => {
          if (d.error) { showToast('Error: ' + d.error, true); if (st) st.textContent = ''; return; }
          showToast('✓ ' + d.deleted_contexts + ' contextos y ' + d.deleted_steps + ' pasos eliminados');
          _datosLoaded = false;
          setTimeout(loadDatos, 600);
        })
        .catch(e => { showToast('Error: ' + e, true); });
    },
    { okLabel: 'Eliminar contextos', okDanger: true }
  );
}

// ── Configuración ─────────────────────────────────────────────────────────────
function loadConfig() {
  const el = document.getElementById("config-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Cargando...</p>';
  fetch("/integrations/status")
    .then(r => {
      const ct = r.headers.get("content-type") || "";
      if (!ct.includes("application/json")) {
        return r.text().then(t => Promise.reject(new Error("HTTP " + r.status + " — respuesta no-JSON: " + t.slice(0, 120))));
      }
      return r.json();
    })
    .then(data => renderConfig(data, el))
    .catch(e => { el.innerHTML = '<p style="color:#f87171">Error al cargar configuración: ' + escHtml(String(e)) + '</p>'; });
}

function renderConfig(data, el) {
  const PROV_ICON = {claude:'🟠', openai:'🟣', deepseek:'🟢'};
  const provCards = (data.providers||[]).map(p => {
    const icon = PROV_ICON[p.name] || '⚪';
    const ok = p.configured;
    return '<div style="display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid var(--border);border-radius:8px;background:var(--bg-elevated)">' +
      '<span style="font-size:20px">' + icon + '</span>' +
      '<div style="flex:1">' +
        '<div style="font-size:13px;font-weight:600;color:var(--text-primary)">' + escHtml(p.name) + '</div>' +
        '<div style="font-size:11px;color:var(--text-muted)">' + escHtml(p.model || '—') + '</div>' +
      '</div>' +
      '<span style="font-size:11px;font-weight:600;padding:3px 10px;border-radius:10px;background:' +
        (ok ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.12)') + ';color:' + (ok ? '#22c55e' : '#f87171') + '">' +
        (ok ? '✓ Configurado' : '✗ Sin API key') + '</span>' +
    '</div>';
  }).join('');

  // BCCh panel (same logic as before, moved here)
  const bc = data.bcentral || {};
  const ri = bc.rate || {};
  const rateVal = ri.rate ? parseFloat(ri.rate).toLocaleString('es-CL', {minimumFractionDigits:2, maximumFractionDigits:2}) : null;
  const rateDate = ri.date || '';
  const rateDisplay = rateVal
    ? '<span style="color:#22c55e;font-weight:700;font-size:20px">$' + rateVal + '</span>' +
      '<span class="text-muted" style="font-size:11px;margin-left:8px">CLP / USD · ' + escHtml(rateDate) +
      (ri.stale ? ' <span style="color:#f59e0b">⚠ desactualizado</span>' : '') + '</span>'
    : '<span class="text-muted" style="font-size:12px">Sin dato — configurá las credenciales</span>';

  el.innerHTML =
    '<div style="display:grid;gap:20px;max-width:900px">' +

    // Panel proveedores
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:14px">Proveedores de IA</h2>' +
    '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px">' +
    provCards +
    '</div>' +
    '<p class="text-muted" style="font-size:11px;margin-top:12px">Las API keys se configuran en <code>~/.ai-orchestrator/config.yaml</code> — no se muestran por seguridad.</p>' +
    '</div>' +

    // Panel BCCh
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:12px">Banco Central de Chile — Tipo de cambio</h2>' +
    '<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:14px">' +
      rateDisplay +
      '<button class="btn btn-secondary" style="font-size:12px;padding:4px 12px" onclick="refreshRate(this)">↻ Actualizar</button>' +
      '<span id="rate-refresh-status" class="text-muted" style="font-size:12px"></span>' +
    '</div>' +
    '<p class="text-muted" style="font-size:11px;margin:0 0 14px">Dólar observado oficial (F073.TCO.PRE.Z.D) · ' +
    (bc.configured ? 'Cuenta: <strong>' + escHtml(bc.user) + '</strong>' : 'Registrate en <strong>si3.bcentral.cl</strong>') + '</p>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:480px">' +
      '<div><label style="font-size:11px;color:var(--text-muted);display:block;margin-bottom:3px">Usuario (email)</label>' +
        '<input type="email" id="bcentral-user" value="' + escHtml(bc.user||'') + '" placeholder="usuario@email.cl" style="width:100%;font-size:12px;box-sizing:border-box"></div>' +
      '<div><label style="font-size:11px;color:var(--text-muted);display:block;margin-bottom:3px">Contraseña</label>' +
        '<input type="password" id="bcentral-pass" placeholder="••••••••" style="width:100%;font-size:12px;box-sizing:border-box"></div>' +
    '</div>' +
    '<div style="margin-top:10px;display:flex;gap:8px;align-items:center">' +
      '<button class="btn btn-primary" style="font-size:12px" onclick="saveBcentralConfig()">Guardar y probar conexión</button>' +
      '<span id="bcentral-status" class="text-muted" style="font-size:12px"></span>' +
    '</div>' +
    '</div>' +

    '</div>';
}

function loadMetrics() {
  const el = document.getElementById("metrics-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Cargando...</p>';
  fetch("/metrics")
    .then(r => r.json())
    .then(data => {
      if (data.error) { el.innerHTML = '<p style="color:#f87171;font-size:13px">Error: ' + escHtml(data.error) + '</p>'; return; }
      renderMetrics(data, el);
    })
    .catch(err => { el.innerHTML = '<p style="color:#f87171;font-size:13px">Error: ' + escHtml(String(err)) + '</p>'; });
}

function renderMetrics(data, el) {
  const MONTHS = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  const fmtDay = s => { const p = s.split('-'); return p[2] + ' ' + MONTHS[parseInt(p[1],10)-1]; };
  const fmtCost = (v, allowDash) => {
    const n = parseFloat(v) || 0;
    if (n === 0 && allowDash) return '—';
    return _fmtUsd(n, n >= 0.01 ? 2 : 4);
  };
  const fmtMs   = v => v > 0 ? (v/1000).toFixed(1) + 's' : '—';
  const rate    = (data.rate && data.rate.rate) ? parseFloat(data.rate.rate) : null;
  const fmtClp  = v => {
    const n = parseFloat(v) || 0;
    if (!rate || n === 0) return '—';
    const clp = Math.round(n * rate);
    return '$' + clp.toLocaleString('es-CL');
  };
  const rateLabel = rate
    ? '<span style="font-size:11px;color:var(--text-faint);font-weight:400"> · USD/CLP ' + rate.toLocaleString('es-CL') + (data.rate.stale ? ' ⚠ desactualizado' : '') + '</span>'
    : '';
  const RATING_LABEL = {'useful':'Util','partial':'Parcial','wrong':'Incorrecto','sin-rating':'Sin evaluar'};
  const RATING_COLOR = {'useful':'#22c55e','partial':'#f59e0b','wrong':'#f87171','sin-rating':'var(--text-faint)'};

  // Costo diario (14 días)
  const dailyRows = (data.daily || []).map(d =>
    '<tr class="detail-tbody-row">' +
    '<td class="td-sm-mono">' + escHtml(fmtDay(d.day)) + '</td>' +
    '<td class="td-sm text-muted" style="text-align:right">' + d.runs + '</td>' +
    '<td class="td-sm" style="text-align:right;color:#22c55e;font-weight:600">' + fmtCost(d.cost, false) + '</td>' +
    '<td class="td-sm" style="text-align:right;color:var(--text-muted)">' + fmtClp(d.cost) + '</td>' +
    '</tr>'
  ).join('');

  // Por proyecto
  const projRows = (data.by_project || []).map(p =>
    '<tr class="detail-tbody-row">' +
    '<td class="td-sm-mono">' + escHtml(p.project) + '</td>' +
    '<td class="td-sm text-muted" style="text-align:right">' + p.runs + '</td>' +
    '<td class="td-sm" style="text-align:right;color:#22c55e">' + fmtCost(p.cost, true) + '</td>' +
    '<td class="td-sm text-muted" style="text-align:right">' + fmtMs(p.avg_ms) + '</td>' +
    '<td class="td-sm" style="text-align:right;color:#f87171">' + (p.failed > 0 ? p.failed : '—') + '</td>' +
    '</tr>'
  ).join('');

  // Por modelo
  const modelRows = (data.by_model || []).map(m =>
    '<tr class="detail-tbody-row">' +
    '<td class="td-sm-mono">' + escHtml((m.model || '').split('/').pop()) + '</td>' +
    '<td class="td-sm text-muted" style="text-align:right">' + m.runs + '</td>' +
    '<td class="td-sm" style="text-align:right;color:#22c55e">' + fmtCost(m.cost, true) + '</td>' +
    '<td class="td-sm text-muted" style="text-align:right">' + fmtMs(m.avg_ms) + '</td>' +
    '</tr>'
  ).join('');

  // Ratings
  const ratingRows = (data.ratings || []).map(r =>
    '<div style="display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px solid var(--border-faint)">' +
    '<span style="font-size:12px;font-weight:600;color:' + (RATING_COLOR[r.rating] || 'var(--text-muted)') + ';min-width:100px">' + escHtml(RATING_LABEL[r.rating] || r.rating) + '</span>' +
    '<div style="flex:1;height:8px;background:var(--bg-code);border-radius:4px;overflow:hidden">' +
    '<div style="height:100%;background:' + (RATING_COLOR[r.rating] || 'var(--text-faint)') + ';width:' + Math.min(100, Math.round(r.cnt / Math.max(...data.ratings.map(x=>x.cnt)) * 100)) + '%"></div>' +
    '</div>' +
    '<span class="text-muted" style="font-size:12px;min-width:30px;text-align:right">' + r.cnt + '</span>' +
    '</div>'
  ).join('');

  el.innerHTML = (
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;max-width:1100px">' +
    // Diario
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:14px">Costo diario (14d)' + rateLabel + '</h2>' +
    (dailyRows ? '<table style="width:100%;font-size:12px;border-collapse:collapse"><thead><tr class="detail-thead-row"><th class="td-sm">Fecha</th><th class="td-sm" style="text-align:right">Runs</th><th class="td-sm" style="text-align:right">USD</th><th class="td-sm" style="text-align:right">CLP</th></tr></thead><tbody>' + dailyRows + '</tbody></table>' : '<p class="text-muted" style="font-size:12px">Sin datos</p>') +
    '</div>' +
    // Ratings
    '<div class="panel">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:14px">Evaluaciones</h2>' +
    (ratingRows || '<p class="text-muted" style="font-size:12px">Sin evaluaciones aun</p>') +
    '<p style="font-size:11px;color:var(--text-faint);margin-top:10px">Evaluá runs desde su panel de detalle</p>' +
    '</div>' +
    // Por proyecto
    '<div class="panel" style="grid-column:1/-1">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:14px">Por proyecto</h2>' +
    (projRows ? '<table style="width:100%;font-size:12px;border-collapse:collapse"><thead><tr class="detail-thead-row"><th class="td-sm">Proyecto</th><th class="td-sm" style="text-align:right">Runs</th><th class="td-sm" style="text-align:right">Costo</th><th class="td-sm" style="text-align:right">Prom.</th><th class="td-sm" style="text-align:right">Errores</th></tr></thead><tbody>' + projRows + '</tbody></table>' : '<p class="text-muted" style="font-size:12px">Sin datos</p>') +
    '</div>' +
    // Por modelo
    '<div class="panel" style="grid-column:1/-1">' +
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:14px">Por modelo</h2>' +
    (modelRows ? '<table style="width:100%;font-size:12px;border-collapse:collapse"><thead><tr class="detail-thead-row"><th class="td-sm">Modelo</th><th class="td-sm" style="text-align:right">Runs</th><th class="td-sm" style="text-align:right">Costo</th><th class="td-sm" style="text-align:right">Prom.</th></tr></thead><tbody>' + modelRows + '</tbody></table>' : '<p class="text-muted" style="font-size:12px">Sin datos</p>') +
    '<p style="font-size:11px;color:var(--text-faint);margin-top:10px"><button class="btn btn-secondary" style="font-size:11px;padding:4px 10px" onclick="_metricsLoaded=false;loadMetrics()">Refrescar</button></p>' +
    '</div>' +
    '</div>'
  );
}

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
  fetch("/pick-folder")
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
  fetch("/add-project", {
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
  fetch("/pick-folder")
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
  fetch("/project/rename", {
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
  fetch("/add-project", {
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
      <span style="color:var(--text-faint)">${f.file_count} arch.</span>
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
  fetch("/index-docs", {
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
  fetch("/sync-cc", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"})
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
  fetch("/clear-imports", {
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

function refreshRate(btn) {
  const st = document.getElementById("rate-refresh-status");
  if (btn) btn.disabled = true;
  if (st) st.textContent = "Actualizando...";
  fetch("/rates/refresh", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
    .then(r => r.json())
    .then(d => {
      if (d.error) { if (st) st.textContent = "Error: " + d.error; }
      else { if (st) st.textContent = "USD/CLP $" + parseFloat(d.rate).toLocaleString('es-CL', {minimumFractionDigits:2}) + " · " + (d.date || ""); }
      if (btn) btn.disabled = false;
      _metricsLoaded = false;
    })
    .catch(e => { if (st) st.textContent = "Error: " + e; if (btn) btn.disabled = false; });
}

function saveBcentralConfig() {
  const user = (document.getElementById("bcentral-user") || {}).value || "";
  const pass = (document.getElementById("bcentral-pass") || {}).value || "";
  const st = document.getElementById("bcentral-status");
  if (!user || !pass) { if (st) st.textContent = "Ingresá usuario y contraseña."; return; }
  if (st) st.textContent = "Guardando y probando...";
  fetch("/config/bcentral", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({"user": user, "pass": pass}),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) { if (st) st.style.color = "#f87171"; if (st) st.textContent = "Error: " + d.error; }
      else {
        if (st) { st.style.color = "#22c55e"; st.textContent = "✓ Guardado · USD/CLP $" + parseFloat(d.rate).toLocaleString('es-CL', {minimumFractionDigits:2}) + " al " + (d.date || ""); }
        if (document.getElementById("bcentral-pass")) document.getElementById("bcentral-pass").value = "";
        _metricsLoaded = false;
        _configLoaded = false;
      }
    })
    .catch(e => { if (st) { st.style.color = "#f87171"; st.textContent = "Error: " + e; } });
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
  fetch("/import-context", {
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

function fmtTs(iso) {
  try {
    return new Date(iso).toLocaleString("es", {
      day:"2-digit", month:"2-digit", year:"2-digit",
      hour:"2-digit", minute:"2-digit", hour12:false,
    });
  } catch { return iso ? iso.slice(0,16) : "—"; }
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
  const regIndex = data.registered_project_index || {};
  const regEntries = Object.entries(regIndex);
  const regRows2 = regEntries.map(function([alias, projPath]) {
    const ae = escHtml(alias);
    const pe = escHtml(projPath);
    return (
      '<div class="reg-proj-row" id="regrow-' + ae + '" style="display:flex;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid var(--border-faint)">' +
        '<span style="font-size:12px;font-weight:600;color:var(--text-primary);min-width:140px;font-family:monospace;flex-shrink:0">' + ae + '</span>' +
        '<span style="font-size:11px;color:var(--text-faint);flex:1;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + pe + '">' + pe + '</span>' +
        '<button class="btn btn-secondary" style="padding:2px 10px;font-size:11px;flex-shrink:0" onclick="startRenameProject(\\'' + ae + '\\')">✎ Renombrar</button>' +
        '<div id="rename-form-' + ae + '" style="display:none;gap:6px;align-items:center">' +
          '<input id="rename-input-' + ae + '" type="text" value="' + ae + '" style="width:140px;font-size:12px" onkeydown="if(event.key===\\'Enter\\')confirmRenameProject(\\'' + ae + '\\');else if(event.key===\\'Escape\\')cancelRenameProject(\\'' + ae + '\\')">' +
          '<button class="btn btn-primary" style="padding:2px 10px;font-size:11px;flex-shrink:0" onclick="confirmRenameProject(\\'' + ae + '\\')">OK</button>' +
          '<button class="btn btn-secondary" style="padding:2px 10px;font-size:11px;flex-shrink:0" onclick="cancelRenameProject(\\'' + ae + '\\')">✕</button>' +
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

Object.assign(window, {
  addCtxStep,
  addNewProject,
  advanceStep,
  applyRunFilters,
  cancelIndexFlow,
  clearImports,
  cleanAllUnmapped,
  cleanProject,
  cleanProjectWithSel,
  closeConfirmModal,
  closeCtxDetail,
  closeDetail,
  confirmIndex,
  deleteContext,
  deleteContexts,
  exportCSV,
  loadConfig,
  loadDatos,
  loadMetrics,
  loadProyectos,
  openContextDetail,
  openDetail,
  pickFolder,
  pickNewProjectFolder,
  purgeChromaDocs,
  purgeChromaResponses,
  rateRun,
  refreshRate,
  registerProject,
  reloadProyectos,
  startRenameProject,
  cancelRenameProject,
  confirmRenameProject,
  renderRunsTable,
  runDoctor,
  runFix,
  runIndexDocs,
  runSync,
  saveBcentralConfig,
  setCtxFilter,
  setTheme,
  showToast,
  skipStep,
  startIndexFlow,
  submitContext,
  submitImportContext,
  submitTask,
  switchTab,
  toggleActivity,
  toggleContextForm,
  toggleFixMenu,
  toggleSender,
  triggerSyncCC,
  _confirmModalBackdrop,
  _confirmModalOk,
  _onImpAgentChange,
});
"""
