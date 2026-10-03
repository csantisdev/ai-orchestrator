"""Pestaña Flujos del dashboard heredado: formulario de nuevo flujo, filtros y tarjetas de contextos."""

from __future__ import annotations

from orchestrator.legacy_dashboard.common import (
    PROVIDER_BG,
    PROVIDER_COLORS,
    _CTX_STATUS_STYLE,
    _STEP_STATUS_STYLE,
    _escape,
    _int_or_none,
    _status_badge,
    _text,
)


def panel(*, project_options_form) -> str:
    return f"""<div id="tab-flujos" style="display:none">
<div class="container">

  <div class="panel" style="margin-bottom:16px">
    <h2>Nuevo flujo</h2>
    <div class="sender-form">
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Proyecto</label>
        <select id="ctxProject" style="width:100%">{project_options_form}</select>
      </div>
      <div>
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Título</label>
        <input id="ctxTitle" type="text" placeholder="Objetivo del contexto..." style="width:100%">
      </div>
      <div class="full">
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Descripción (opcional)</label>
        <input id="ctxDesc" type="text" placeholder="Detalle adicional..." style="width:100%">
      </div>
      <div class="full">
        <label style="display:block;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Pasos</label>
        <div id="ctxSteps"></div>
        <button class="btn btn-secondary" onclick="addCtxStep()" style="margin-top:8px;font-size:12px;padding:5px 12px">+ Paso</button>
      </div>
      <div class="full" style="display:flex;gap:8px;align-items:center">
        <button class="btn btn-primary" onclick="submitContext()">Crear flujo</button>
        <span id="ctxStatus" class="text-muted" style="font-size:12px"></span>
      </div>
    </div>
  </div>

  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px">
    <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-muted)">Estado</span>
    <button class="pg-btn pg-btn-active ctx-filter-btn" id="ctx-filter-all" onclick="setCtxFilter('all')">Todos</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-active" onclick="setCtxFilter('active')">Activo</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-programado" onclick="setCtxFilter('programado')">Programado</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-completed" onclick="setCtxFilter('completed')">Completado</button>
    <button class="pg-btn ctx-filter-btn" id="ctx-filter-abandoned" onclick="setCtxFilter('abandoned')">Abandonado</button>
  </div>

  <div id="contextsSection"></div>

</div>
</div>

"""


def _build_contexts_section(contexts: list[dict]) -> str:
    if not contexts:
        return '<div id="contextsSection"></div>'

    cards = ""
    for ctx in contexts:
        ctx_id = _int_or_none(ctx.get("id"))
        if ctx_id is None:
            continue
        ctx_status = _text(ctx.get("status"), "active")
        sc, sbg = _CTX_STATUS_STYLE.get(ctx_status, ("#6b7280", "#f3f4f6"))
        steps = ctx.get("steps", [])

        steps_html = ""
        for step in steps:
            st = _text(step.get("status"), "pending")
            fc, fbg = _STEP_STATUS_STYLE.get(st, ("#6b7280", "#f3f4f6"))
            provider = _text(step.get("provider"))
            is_active = st == "in_progress"
            left_border = "border-left:2px solid #38bdf8;" if is_active else "border-left:2px solid var(--border);"
            active_bg = "background:rgba(56,189,248,0.06);" if is_active else ""
            prov_html = ""
            if provider:
                pc = PROVIDER_COLORS.get(provider, "var(--text-muted)")
                pbg = PROVIDER_BG.get(provider, "rgba(113,113,122,0.12)")
                prov_html = f'<span style="font-size:10px;background:{pbg};color:{pc};padding:1px 7px;border-radius:20px;font-weight:600">{_escape(provider)}</span>'
            action_html = ""
            if is_active:
                sid = _int_or_none(step.get("id"))
                if sid is None:
                    continue
                action_html = (
                    f'<button class="ctx-step-btn ctx-step-advance" data-step-id="{sid}" onclick="advanceStep(Number(this.dataset.stepId))" title="Completar y continuar">✓</button>'
                    f'<button class="ctx-step-btn ctx-step-skip" data-step-id="{sid}" onclick="skipStep(Number(this.dataset.stepId))" title="Omitir paso">↷</button>'
                )
            steps_html += (
                f'<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;{left_border}{active_bg}border-radius:6px;margin-bottom:2px">'
                f'<span class="step-idx">{_escape(str(_int_or_none(step.get("order_idx")) if _int_or_none(step.get("order_idx")) is not None else "?"))}</span>'
                f'<span class="step-title">{_escape(_text(step.get("title")))}</span>'
                f'{prov_html}'
                f'<span style="font-size:10px;background:{fbg};color:{fc};padding:1px 7px;border-radius:20px;font-weight:600">{_escape(st)}</span>'
                f'{action_html}'
                f'</div>'
            )

        desc_html = ""
        if ctx.get("description"):
            desc_html = f'<p class="ctx-desc">{_escape(_text(ctx.get("description")))}</p>'

        body_html = steps_html if steps_html else '<p class="ctx-desc" style="padding:8px 0">Sin pasos definidos.</p>'

        # Texto de tarea para el botón play: paso in_progress o título del contexto
        active_step = next((s for s in steps if _text(s.get("status")) == "in_progress"), None)
        run_task = _text(active_step.get("title") if active_step else ctx.get("title"))
        run_project = _text(ctx.get("project"))

        play_btn = ""
        if ctx_status == "active":
            play_btn = (
                f'<button class="ctx-step-btn ctx-play-btn" '
                f'data-project="{_escape(run_project)}" data-task="{_escape(run_task)}" '
                f'onclick="runContext(this)" '
                f'title="Ejecutar paso activo como nuevo run">▶ Ejecutar</button>'
            )

        ctx_title_escaped = _escape(_text(ctx.get("title"), "(sin título)"))
        delete_btn = (
            f'<button class="ctx-step-btn ctx-delete-btn" '
            f'data-ctx-id="{ctx_id}" data-ctx-title="{ctx_title_escaped}" '
            f'onclick="deleteContextFromButton(this)" '
            f'title="Eliminar contexto">✕</button>'
        )

        cards += (
            f'<div class="ctx-card">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
            f'<span style="font-size:13px;font-weight:600;color:var(--text-primary);flex:1">{ctx_title_escaped}</span>'
            f'<span style="font-size:11px;color:var(--text-faint);font-family:\'JetBrains Mono\',monospace">{_escape(_text(ctx.get("project")))}</span>'
            f'<span style="font-size:10px;background:{sbg};color:{sc};padding:2px 8px;border-radius:20px;font-weight:600">{_escape(ctx_status)}</span>'
            f'{play_btn}'
            f'<button data-ctx-id="{ctx_id}" onclick="openContextDetail(Number(this.dataset.ctxId))" class="ctx-step-btn" style="font-size:10px;padding:2px 8px;border-radius:20px">→ Detalle</button>'
            f'{delete_btn}'
            f'</div>'
            f'{desc_html}'
            f'<div>{body_html}</div>'
            f'</div>'
        )

    return (
        f'<div id="contextsSection"><div class="panel" style="margin-bottom:20px">'
        f'<h2>Contextos <span style="font-weight:400;text-transform:none;font-size:11px;color:var(--text-faint);letter-spacing:0">({len(contexts)})</span></h2>'
        f'{cards}'
        f'</div></div>'
    )
