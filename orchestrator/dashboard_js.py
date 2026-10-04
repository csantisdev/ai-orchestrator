"""JavaScript del dashboard heredado, armado desde un archivo por vista."""

from __future__ import annotations

from pathlib import Path

_JS_DIR = Path(__file__).parent / "legacy_dashboard" / "js"
# core primero (infraestructura compartida) y startup al final (exportaciones y arranque).
_JS_FILES = ("core", "actividad", "flujos", "proyectos", "metrics", "datos", "config", "startup")


def _build_js() -> str:
    return "\n".join((_JS_DIR / f"{name}.js").read_text(encoding="utf-8") for name in _JS_FILES)
