"""Línea base de estilos y colores literales del dashboard (spec §23.7).

Se cuentan tres clases de literales por archivo:

- estilos en línea: atributos `style="…"`, `setAttribute("style", …)` y `cssText`;
- asignaciones de estilo desde JS: `.style.` y `["style"]`;
- colores literales: hexadecimales y funciones `rgb()`, `rgba()`, `hsl()`, `hsla()`.

Los nombres de color CSS (`red`, `white`…) no se cuentan: no hay forma confiable de
distinguirlos de texto común sin un parser de CSS.

- Código heredado: los conteos por archivo no pueden subir. Cada PR que migra una vista
  baja los de su archivo y actualiza `BASELINE` en el mismo PR.
- Archivos nuevos en `orchestrator/static/dashboard/`: ninguno de los tres, salvo colores
  en `tokens.css`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ORCHESTRATOR = Path(__file__).parent.parent / "orchestrator"
INLINE_STYLE = re.compile(r"\bstyle=\\?[\"']|setAttribute\(\s*[\"']style[\"']|\.cssText\b")
# `["style"]` solo cuenta cuando se escribe una propiedad o se asigna: `el["style"].x`
# o `el["style"] = …`. Leer una clave "style" de un objeto cualquiera no es un estilo.
STYLE_PROPERTY = re.compile(r"\.style\.|\[\s*[\"']style[\"']\s*\]\s*(?:\.|=(?!=))")
# Funciones de color de CSS: argumento numérico, porcentaje o var(). Una función JS
# propia llamada `rgb(x)` con un identificador como argumento no cuenta.
COLOR = re.compile(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b|(?<![\w.$])(?:rgba?|hsla?)\(\s*(?:[\d.%-]|var\()")

# (estilos en línea, asignaciones de estilo, colores) por archivo, medidos en D1b (ola 2).
BASELINE = {
    "dashboard.py": (22, 0, 2),
    "legacy_dashboard/__init__.py": (0, 0, 0),
    "legacy_dashboard/actividad.py": (24, 0, 0),
    "legacy_dashboard/common.py": (0, 0, 32),
    "legacy_dashboard/config.py": (3, 0, 0),
    "legacy_dashboard/datos.py": (3, 0, 0),
    "legacy_dashboard/flujos.py": (25, 0, 7),
    "legacy_dashboard/metrics.py": (3, 0, 0),
    "legacy_dashboard/proyectos.py": (3, 0, 0),
    "static/dashboard/legacy/actividad.js": (48, 11, 43),
    "static/dashboard/legacy/config.js": (29, 3, 10),
    "static/dashboard/legacy/core.js": (11, 14, 3),
    "static/dashboard/legacy/datos.js": (105, 0, 37),
    "static/dashboard/legacy/flujos.js": (31, 1, 18),
    "static/dashboard/legacy/metrics.js": (46, 0, 9),
    "static/dashboard/legacy/proyectos.js": (98, 26, 26),
    "static/dashboard/legacy/startup.js": (0, 0, 0),
    "static/dashboard/legacy/legacy.css": (0, 0, 45),
}
LEGACY_GLOBS = ("dashboard.py", "legacy_dashboard/*.py", "static/dashboard/legacy/*.js", "static/dashboard/legacy/*.css")


def counts(text: str) -> tuple[int, int, int]:
    return (len(INLINE_STYLE.findall(text)), len(STYLE_PROPERTY.findall(text)), len(COLOR.findall(text)))


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
        if not path.is_file() or path.suffix not in (".js", ".mjs", ".css", ".html", ".svg"):
            continue
        if path.relative_to(root).parts[0] == "legacy":
            continue  # código heredado: lo cubre BASELINE
        inline, prop, hexes = counts(path.read_text(encoding="utf-8"))
        if path.name == "tokens.css":
            hexes = 0
        if inline or prop or hexes:
            offenders[path.relative_to(root).as_posix()] = (inline, prop, hexes)

    assert offenders == {}


def test_new_css_does_not_use_important():
    """Entre capas, `!important` invierte la prioridad: uno del shell competiría con los
    `!important` heredados de la capa `legacy`. Solo se permite la regla de `[hidden]`."""
    root = ORCHESTRATOR / "static" / "dashboard"
    allowed = "[hidden] { display: none !important; }"
    offenders = []
    for path in root.rglob("*.css"):
        if path.relative_to(root).parts[0] == "legacy":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "!important" in line and line.strip() != allowed:
                offenders.append(f"{path.name}:{number}")

    assert offenders == []


@pytest.mark.parametrize("text, expected", [
    ('<div style="color:red">', (1, 0, 0)),
    ("'<span style=\\\"x\\\">'", (1, 0, 0)),
    ("el.style.display = 'none'", (0, 1, 0)),
    ("color:#22c55e;background:#fff", (0, 0, 2)),
    ("&#x2715; #confirmModal id#abc", (0, 0, 0)),
    ('el.setAttribute("style", "x"); el.style.cssText = "y"', (2, 1, 0)),
    ("el['style'].color = c; el[ \"style\" ] = s", (0, 2, 0)),
    ("const x = theme['style']; if (o[\"style\"] == y) {}", (0, 0, 0)),
    ("color: rgb(1,2,3); background: rgba(0,0,0,.5); x: hsl(1,2%,3%) hsla(var(--h),2%,3%,1)", (0, 0, 4)),
    ("const rgbValue = 1; myrgb(2); rgb(value); color.rgb(1); function hsl(h) {}", (0, 0, 0)),
])
def test_counters(text, expected):
    assert counts(text) == expected
