// Infraestructura compartida del dashboard heredado: POST con sesión, formato, paginación, modal, toast, tema, SSE, barra de actividad, menú de acciones y pestañas.
// Archivo del dashboard heredado (ola 2, separación mecánica); no cambiar el comportamiento.

const _nativeFetch = window.fetch.bind(window);

function postJson(url, body) {
  const session = (document.querySelector('meta[name="orchestrator-session"]') || {}).content || "";
  if (body && typeof body === "object" && Object.prototype.hasOwnProperty.call(body, "body")) body = body.body;
  return _nativeFetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Orchestrator-Session": session},
    body: body === undefined ? "{}" : (typeof body === "string" ? body : JSON.stringify(body)),
  }).then(async response => {
    if (response.status === 403) {
      const payload = await response.clone().json().catch(() => ({}));
      if (payload.reason === "session_expired") {
        if (!window.__sessionExpiredNotified) {
          window.__sessionExpiredNotified = true;
          alert("El servidor se reinició. Recargá la página para continuar.");
        }
        throw new Error("session_expired");
      }
    }
    return response;
  });
}

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

const evtSource = new EventSource("/events");
window.__dashboardEvents = evtSource;
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

function safeNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? String(number) : (fallback === undefined ? "—" : fallback);
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
      `<span class="tr-ts">${escHtml(_fmtTs(d.ts))}</span>` +
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
    `<span class="tr-ts">${escHtml(ts)}</span>` +
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
    const r = await postJson("/run-doctor", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
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
    const r = await postJson("/run-fix", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(opts||{})});
    const d = await r.json();
    if (d.error) { _actAppend("fix — " + d.error, "fail"); return; }
    (d.lines||[]).forEach(l => _actAppend(l.text, l.ok?"ok":l.fail?"fail":l.warn?"warn":"info"));
    _actAppend("fix — " + d.fixed + " mejora(s) aplicada(s)", d.fixed>0?"ok":"info");
  } catch(e) { _actAppend("fix — " + e.message, "fail"); }
  finally { _actBusy(btn, false, "fix"); }
}

async function _syncOne(url, label, unit) {
  // Cada fuente se maneja de forma independiente: si una falla (red, HTTP,
  // JSON), las demas igual se intentan - antes un error en sync-cc cortaba
  // toda la cadena y Git/Codex ni se pedian.
  try {
    const r = await postJson(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    let d, parseFailed = false;
    try { d = await r.json(); } catch (e) { d = {}; parseFailed = true; }
    // "busy" (409) va PRIMERO: r.ok es false en un 409, asi que si el
    // chequeo de !r.ok fuera antes, el 409 real caia en la rama de error y
    // esta rama quedaba inalcanzable.
    if (d.status === "busy") {
      _actAppend(label + " — ya hay una sincronización en curso, probá de nuevo en un rato", "warn");
      return 0;
    }
    if (!r.ok || d.error || parseFailed) {
      const msg = d.error || ("HTTP " + r.status + (parseFailed ? " (respuesta inválida)" : ""));
      _actAppend(label + " — " + msg, "fail");
      return 0;
    }
    const n = d.imported || 0;
    _actAppend(label + " — " + n + " " + unit + " importado(s)", n > 0 ? "ok" : "info");
    return n;
  } catch (e) {
    _actAppend(label + " — " + e.message, "fail");
    return 0;
  }
}

async function runSync(btn) {
  _actBusy(btn, true);
  _actAppend("sync — importando Claude Code + Git + Codex...", "info");
  try {
    // Secuencial, no Promise.all: los tres endpoints comparten un mismo lock
    // no-bloqueante en el servidor - en paralelo, solo el primero en llegar
    // adquiere el lock y los otros dos responden 409 "busy".
    const nCc = await _syncOne("/sync-cc", "sync-cc", "sesión(es)");
    const nGit = await _syncOne("/sync-git", "sync-git", "commit(s)");
    const nCodex = await _syncOne("/sync-codex", "sync-codex", "sesión(es)");
    if ((nCc + nGit + nCodex) > 0 && typeof renderRunsTable === "function") setTimeout(renderRunsTable, 800);
  } finally { _actBusy(btn, false, "sync"); }
}

async function runIndexDocs(btn) {
  _actBusy(btn, true);
  const proj = (document.getElementById("senderProject")||document.querySelector("select[name=project]")||{}).value||"";
  if (!proj) { _actAppend("index — seleccioná un proyecto primero", "warn"); _actBusy(btn,false,"index"); return; }
  _actAppend("index — indexando " + proj + "...", "info");
  try {
    const r = await postJson("/index-docs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({project:proj})});
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

function fmtTs(iso) {
  try {
    return new Date(iso).toLocaleString("es", {
      day:"2-digit", month:"2-digit", year:"2-digit",
      hour:"2-digit", minute:"2-digit", hour12:false,
    });
  } catch { return iso ? iso.slice(0,16) : "—"; }
}
