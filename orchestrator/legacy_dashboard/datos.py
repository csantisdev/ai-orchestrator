"""Pestaña Datos del dashboard heredado (se carga desde el JS)."""

from __future__ import annotations


def panel() -> str:
    return """<div id="tab-datos" style="display:none">
<div class="container" style="padding-top:20px">
  <div id="datos-content">
    <p class="text-muted" style="font-size:13px">Haz clic en la pestaña para cargar.</p>
  </div>
</div>
</div>

"""
