"""JavaScript del dashboard heredado: un archivo clásico por vista en static/dashboard/legacy."""

from __future__ import annotations

from pathlib import Path

_JS_DIR = Path(__file__).parent / "static" / "dashboard" / "legacy"
# Orden de carga: core primero (infraestructura compartida) y startup al final
# (exportaciones y arranque). La página los incluye como <script> clásicos en este orden.
_JS_FILES = ("core", "actividad", "flujos", "proyectos", "metrics", "datos", "config", "startup")


def _build_js() -> str:
    """Los archivos unidos en orden; lo usan los tests de estructura y de orden de carga."""
    return "\n".join((_JS_DIR / f"{name}.js").read_text(encoding="utf-8") for name in _JS_FILES)
