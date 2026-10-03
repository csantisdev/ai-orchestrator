"""Pestaña Proyectos del dashboard heredado (se carga desde el JS)."""

from __future__ import annotations


def panel() -> str:
    return """<div id="tab-proyectos" style="display:none">
<div class="container">
  <div id="proyectos-content" style="padding-top:4px">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
  </div>
</div>
</div>

"""
