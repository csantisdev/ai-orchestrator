"""Línea base de estilos y colores literales del dashboard (spec §23.7).

- Código heredado: los conteos de `style="…"`, asignaciones `.style.` y colores
  hexadecimales por archivo no pueden subir. Cada PR que migra una vista baja los de su
  archivo y actualiza `BASELINE` en el mismo PR.
- Archivos nuevos en `orchestrator/static/dashboard/`: sin estilos en línea ni `.style.`,
  y hexadecimales solo en `tokens.css`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ORCHESTRATOR = Path(__file__).parent.parent / "orchestrator"
INLINE_STYLE = re.compile(r"\bstyle=\\?[\"']")
STYLE_PROPERTY = re.compile(r"\.style\.")
HEX_COLOR = re.compile(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b")

# (style="…", .style., hexadecimales) por archivo, medidos sobre production@ec1b212.
BASELINE = {
    "dashboard.py": (22, 1, 4),
    "legacy_dashboard/__init__.py": (0, 0, 0),
    "legacy_dashboard/actividad.py": (24, 0, 0),
    "legacy_dashboard/common.py": (0, 0, 16),
    "legacy_dashboard/config.py": (3, 0, 0),
    "legacy_dashboard/datos.py": (3, 0, 0),
    "legacy_dashboard/flujos.py": (25, 0, 5),
    "legacy_dashboard/metrics.py": (3, 0, 0),
    "legacy_dashboard/proyectos.py": (3, 0, 0),
    "legacy_dashboard/js/actividad.js": (48, 11, 29),
    "legacy_dashboard/js/config.js": (29, 3, 8),
    "legacy_dashboard/js/core.js": (11, 14, 3),
    "legacy_dashboard/js/datos.js": (105, 0, 31),
    "legacy_dashboard/js/flujos.js": (30, 1, 16),
    "legacy_dashboard/js/metrics.js": (46, 0, 9),
    "legacy_dashboard/js/proyectos.js": (98, 26, 26),
    "legacy_dashboard/js/startup.js": (0, 0, 0),
}
LEGACY_GLOBS = ("dashboard.py", "legacy_dashboard/*.py", "legacy_dashboard/js/*.js")


def counts(text: str) -> tuple[int, int, int]:
    return (len(INLINE_STYLE.findall(text)), len(STYLE_PROPERTY.findall(text)), len(HEX_COLOR.findall(text)))


def _legacy_files() -> dict[str, Path]:
    files = {}
    for pattern in LEGACY_GLOBS:
        for path in ORCHESTRATOR.glob(pattern):
            files[path.relative_to(ORCHESTRATOR).as_posix()] = path
    return files


def test_every_legacy_file_has_a_baseline():
    assert sorted(_legacy_files()) == sorted(BASELINE)


@pytest.mark.parametrize("relative", sorted(BASELINE))
def test_legacy_counts_never_go_up(relative):
    path = ORCHESTRATOR / relative
    current = counts(path.read_text(encoding="utf-8"))

    assert all(now <= base for now, base in zip(current, BASELINE[relative])), (
        f"{relative}: {current} supera la línea base {BASELINE[relative]} "
        "(style=, .style., hexadecimales)"
    )


def test_baseline_is_kept_tight():
    """Cuando un PR baja un conteo, también baja la línea base: nunca queda holgura."""
    loose = {relative: (counts((ORCHESTRATOR / relative).read_text(encoding="utf-8")), base)
             for relative, base in BASELINE.items()
             if counts((ORCHESTRATOR / relative).read_text(encoding="utf-8")) != base}

    assert loose == {}


def test_new_dashboard_files_have_no_literal_styles():
    root = ORCHESTRATOR / "static" / "dashboard"
    offenders = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in (".js", ".css", ".html"):
            continue
        inline, prop, hexes = counts(path.read_text(encoding="utf-8"))
        if path.name == "tokens.css":
            hexes = 0
        if inline or prop or hexes:
            offenders[path.relative_to(root).as_posix()] = (inline, prop, hexes)

    assert offenders == {}


@pytest.mark.parametrize("text, expected", [
    ('<div style="color:red">', (1, 0, 0)),
    ("'<span style=\\\"x\\\">'", (1, 0, 0)),
    ("el.style.display = 'none'", (0, 1, 0)),
    ("color:#22c55e;background:#fff", (0, 0, 2)),
    ("&#x2715; #confirmModal id#abc", (0, 0, 0)),
])
def test_counters(text, expected):
    assert counts(text) == expected
