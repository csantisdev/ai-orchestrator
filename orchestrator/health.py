"""Salud de los componentes opcionales del dashboard (spec §7, estado "degradado").

Un componente opcional que falla no rompe el dashboard: queda "degraded" y la UI lo avisa con
texto explícito. Los mensajes son fijos por componente (nunca el texto de una excepción).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

# Qué deja de funcionar cuando el componente está degradado (texto fijo para la UI).
EFFECTS = {
    "chroma": "ChromaDB no responde: el routing sigue, sin señales de similitud.",
}

_lock = threading.Lock()
_components: dict[str, dict] = {}


def report(name: str, ok: bool) -> None:
    """Registra el último resultado de un componente conocido."""
    if name not in EFFECTS:
        raise ValueError(f"componente desconocido: {name}")
    with _lock:
        _components[name] = {"state": "ok" if ok else "degraded", "checked_at": datetime.now(timezone.utc).isoformat()}


def snapshot() -> dict[str, dict]:
    """Estado de cada componente conocido; `unknown` si todavía no se verificó."""
    with _lock:
        current = dict(_components)
    result = {}
    for name, effect in EFFECTS.items():
        entry = current.get(name, {"state": "unknown", "checked_at": None})
        result[name] = {**entry, "effect": effect if entry["state"] == "degraded" else None}
    return result


def reset() -> None:
    """Olvida los resultados (para tests)."""
    with _lock:
        _components.clear()
