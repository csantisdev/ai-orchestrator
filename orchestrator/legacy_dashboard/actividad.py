"""Pestaña Actividad del dashboard heredado: envío de tareas, tarjetas, gráficos y tabla de runs."""

from __future__ import annotations

from orchestrator.legacy_dashboard.common import _fmt_ms


def panel(*, project_options_form, total, cost_display, tokens_display, cache_display, avg_dur, provider_bars, model_bars, purpose_bars, filter_project_opts, filter_model_opts) -> str:
    return f"""<div id="tab-actividad">
<div class="container">

  <div class="sender-panel" id="senderPanel">
    <h2 style="font-size:13px;font-weight:700;color:var(--text-muted);margin-bottom:14px;text-transform:uppercase;letter-spacing:.4px">Enviar tarea</h2>
    <div class="sender-form">
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Proyecto</label>
        <select id="senderProject" style="width:100%">{project_options_form}</select>
      </div>
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Modelo (opcional)</label>
        <select id="senderModel" style="width:100%">
          <option value="">Router automático</option>
          <option value="claude">Claude</option>
          <option value="openai">OpenAI</option>
          <option value="deepseek">DeepSeek</option>
        </select>
      </div>
      <div class="full">
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Tarea</label>
        <textarea id="senderTask" placeholder="Describí la tarea que querés resolver..."></textarea>
      </div>
      <div class="full" style="display:flex;gap:8px;align-items:center">
        <button class="btn btn-primary" onclick="submitTask()">Enviar</button>
        <span id="senderStatus" class="text-muted" style="font-size:12px"></span>
      </div>
    </div>
  </div>

  <div class="cards">
    <div class="card">
      <div class="label">Total Runs</div>
      <div class="value" id="card-total">{total}</div>
    </div>
    <div class="card">
      <div class="label">Costo Hoy</div>
      <div class="value" id="card-cost">{cost_display}</div>
      <div class="sub">dólares estadounidenses (USD)</div>
    </div>
    <div class="card">
      <div class="label">Tokens Usados</div>
      <div class="value">{tokens_display}</div>
    </div>
    <div class="card">
      <div class="label">Ahorro en Caché</div>
      <div class="value">{cache_display}</div>
      <div class="sub">de tokens vía caché</div>
    </div>
    <div class="card">
      <div class="label">Duración Prom.</div>
      <div class="value">{_fmt_ms(avg_dur)}</div>
    </div>
  </div>

  <div id="budgetSection"></div>

  <div class="grid-charts">
    <div class="panel"><h2>Por Proveedor</h2>{provider_bars}</div>
    <div class="panel"><h2>Por Modelo</h2>{model_bars}</div>
    <div class="panel"><h2>Por Propósito</h2>{purpose_bars}</div>
  </div>

  <div class="panel" style="margin-bottom:20px;overflow-x:auto">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px">
      <h2 style="margin-bottom:0">Runs <span id="runs-count" style="font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;color:var(--text-faint)"></span></h2>
      <div style="display:flex;align-items:center;gap:6px;margin-left:auto;flex-wrap:wrap">
        <label style="font-size:11px;color:var(--text-muted)">Proyecto</label>
        <select id="filterProject" onchange="applyRunFilters()" style="font-size:12px;padding:4px 8px">{filter_project_opts}</select>
        <label style="font-size:11px;color:var(--text-muted)">Modelo</label>
        <select id="filterModel" onchange="applyRunFilters()" style="font-size:12px;padding:4px 8px">{filter_model_opts}</select>
        <button class="btn btn-secondary" onclick="exportCSV()" style="font-size:12px;padding:5px 12px">↓ CSV</button>
      </div>
    </div>
    <table id="runs-table" style="display:none"><thead><tr><th>Fecha</th><th>Proyecto</th><th>Proveedor</th><th>Modelo</th><th style="text-align:right">Dur.</th><th style="text-align:right">Tokens</th><th style="text-align:right">Costo (USD)</th><th style="text-align:center">Cache</th><th>Tarea</th><th>Estado</th></tr></thead><tbody id="runs-body"></tbody></table>
    <p class="empty" id="empty-msg" style="display:none">No hay runs aún. Usá el botón <strong>+ Nueva tarea</strong> para enviar una.</p>
    <div id="runs-pagination"></div>
  </div>

</div>
</div>

"""
