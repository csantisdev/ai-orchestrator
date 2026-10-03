// Pestaña Datos: limpieza de runs y contextos y purga de ChromaDB.
// Archivo del dashboard heredado (ola 2, separación mecánica); no cambiar el comportamiento.

// ── Datos ─────────────────────────────────────────────────────────────────────
function loadDatos() {
  const el = document.getElementById("datos-content");
  el.innerHTML = '<p class="text-muted" style="font-size:13px"><span class="spinner"></span>&nbsp;Cargando...</p>';
  fetch("/clean-preview")
    .then(r => r.json())
    .then(data => renderDatos(data, el))
    .catch(e => { el.innerHTML = '<p style="color:#f87171">Error: ' + escHtml(String(e)) + '</p>'; });
}

function refreshChromaStats(btn) {
  if (btn) btn.disabled = true;
  postJson("/chroma-stats/refresh", "{}")
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(() => { _datosLoaded = false; loadDatos(); })
    .catch(() => showToast("No se pudieron actualizar las estadísticas de ChromaDB.", true))
    .finally(() => { if (btn) btn.disabled = false; });
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
    '<h2 style="font-size:14px;font-weight:700;margin-bottom:4px">ChromaDB — vectores RAG <button class="btn btn-secondary" style="font-size:11px" onclick="refreshChromaStats(this)">Actualizar</button></h2>' +
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
            .map(([s,n]) => '<span style="font-size:10px;color:var(--text-muted)">' + escHtml(STATUS_LABELS[s] || s) + ': ' + safeNumber(n, "0") + '</span>')
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
      postJson('/clean/unmapped', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
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
      postJson('/clear-imports', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project: proj})})
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
      postJson('/clear-imports', {
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
      postJson('/purge-chroma-docs', {
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
      postJson('/purge-chroma-responses', {
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
      postJson('/delete-contexts', {
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
