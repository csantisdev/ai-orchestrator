// Pestaña Flujos: filtros, acciones y detalle de contextos, y formulario de nuevo flujo.
// Archivo del dashboard heredado (ola 2, separación mecánica); no cambiar el comportamiento.

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
  postJson("/advance-step",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_id:stepId})})
    .then(r=>r.json())
    .then(d=>{
      if (d.error){showToast("Error: "+d.error,true);return;}
      showToast(d.context_done?"Flujo completado":"Paso avanzado");
      _refreshContexts();
    }).catch(()=>showToast("Error de conexión",true));
}

function skipStep(stepId, ctxId) {
  postJson("/skip-step",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step_id:stepId,reason:"omitido desde dashboard"})})
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
  postJson("/run", {method:"POST", headers:{"Content-Type":"application/json"},
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

function deleteContextFromButton(button) {
  deleteContext(Number(button.dataset.ctxId), button.dataset.ctxTitle || "");
}

function deleteContext(ctxId, title) {
  showConfirmModal(
    "Eliminar contexto",
    "Se eliminarán permanentemente el contexto <strong>" + escHtml(title) + "</strong>, todos sus pasos, alineamientos y tool calls registrados.<br><br>Los runs históricos se conservan pero perderán la referencia al paso.",
    function() {
      postJson("/context/" + Number(ctxId) + "/delete", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
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
  ctxId = Number(ctxId);
  if (!Number.isInteger(ctxId)) return;
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
          <span style="color:var(--text-faint);white-space:nowrap">${escHtml(a.ts?new Date(a.ts).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"—")}</span>
          <span style="color:${a.confirmed?"#22c55e":"#f87171"};font-weight:700">${a.confirmed?"✓":"✗"}</span>
          <span style="color:var(--text-secondary)">${escHtml(a.checkpoint||"")}</span>
          <span style="color:var(--text-faint)">${escHtml(a.agent||"")}</span>
        </div>`).join("") || '<span style="font-size:11px;color:var(--text-faint)">Sin alineamientos.</span>';
        const tools=(s.tool_calls||[]).map(tc=>`<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border-faint);display:flex;gap:8px">
          <span style="color:var(--text-faint);white-space:nowrap">${escHtml(tc.ts?new Date(tc.ts).toLocaleString("es",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"—")}</span>
          <span style="font-family:'JetBrains Mono',monospace;color:var(--text-primary)">${escHtml(tc.tool_name||"")}</span>
          <span style="color:${tc.status==="ok"?"#22c55e":"#f87171"}">${escHtml(tc.status||"")}</span>
          <span style="color:var(--text-faint)">${tc.duration_ms!=null?safeNumber(tc.duration_ms)+"ms":""}</span>
        </div>`).join("") || '<span style="font-size:11px;color:var(--text-faint)">Sin tool calls.</span>';
        return `<div style="margin-bottom:14px;padding:10px;background:var(--bg-elevated);border-radius:10px;border-left:3px solid ${sc}">
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
            <span style="font-size:11px;font-weight:700;color:var(--text-faint);font-family:'JetBrains Mono',monospace">${safeNumber(s.order_idx,"?")}</span>
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
          <span class="chip-mono">#${safeNumber(data.id)}</span>
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
  postJson("/create-context", {
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
