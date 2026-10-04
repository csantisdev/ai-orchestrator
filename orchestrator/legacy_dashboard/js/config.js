// Pestaña Configuración: proveedores, tipo de cambio y credenciales del Banco Central.
// Archivo del dashboard heredado (ola 2, separación mecánica); no cambiar el comportamiento.

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
    (bc.configured ? 'Credenciales configuradas.' : 'Registrate en <strong>si3.bcentral.cl</strong>') + '</p>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:480px">' +
      '<div><label style="font-size:11px;color:var(--text-muted);display:block;margin-bottom:3px">Usuario (email)</label>' +
        '<input type="email" id="bcentral-user" value="" placeholder="usuario@email.cl" style="width:100%;font-size:12px;box-sizing:border-box"></div>' +
      '<div><label style="font-size:11px;color:var(--text-muted);display:block;margin-bottom:3px">Contraseña</label>' +
        '<input type="password" id="bcentral-pass" placeholder="••••••••" style="width:100%;font-size:12px;box-sizing:border-box"></div>' +
    '</div>' +
    '<div style="margin-top:10px;display:flex;gap:8px;align-items:center">' +
      '<button class="btn btn-primary" style="font-size:12px" onclick="saveBcentralConfig()">Guardar y probar conexión</button>' +
      '<span id="bcentral-status" class="text-muted" style="font-size:12px"></span>' +
    '</div>' +
    '</div>' +

    '</div>';
  if (ri.stale) setTimeout(() => refreshRate(), 0);
}

function refreshRate(btn) {
  const st = document.getElementById("rate-refresh-status");
  if (btn) btn.disabled = true;
  if (st) st.textContent = "Actualizando...";
  postJson("/rates/refresh", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
    .then(r => r.json())
    .then(d => {
      if (d.error) { if (st) st.textContent = "Error: " + d.error; }
      else { if (st) st.textContent = "USD/CLP $" + parseFloat(d.rate).toLocaleString('es-CL', {minimumFractionDigits:2}) + " · " + (d.date || ""); }
      if (btn) btn.disabled = false;
      _metricsLoaded = false;
    })
    .catch(e => { if (st) st.textContent = "Error: " + e; if (btn) btn.disabled = false; });
}

function refreshStaleRateOnLoad() {
  fetch("/rates")
    .then(r => r.json())
    .then(rate => { if (!rate || rate.rate == null || rate.stale) refreshRate(); })
    .catch(() => {});
}

function saveBcentralConfig() {
  const user = (document.getElementById("bcentral-user") || {}).value || "";
  const pass = (document.getElementById("bcentral-pass") || {}).value || "";
  const st = document.getElementById("bcentral-status");
  if (!user || !pass) { if (st) st.textContent = "Ingresá usuario y contraseña."; return; }
  if (st) st.textContent = "Guardando y probando...";
  postJson("/config/bcentral", {
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
