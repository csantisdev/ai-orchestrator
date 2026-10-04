// Pestaña Métricas.
// Archivo del dashboard heredado (ola 2, separación mecánica); no cambiar el comportamiento.

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
