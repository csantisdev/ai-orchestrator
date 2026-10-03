"""Pestaña Métricas del dashboard heredado (se carga desde el JS)."""

from __future__ import annotations


def panel() -> str:
    return """<div id="tab-metrics" style="display:none">
<div class="container">
  <div id="metrics-content" style="padding-top:4px">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
  </div>
</div>
</div>

"""
