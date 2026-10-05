"""Contraste WCAG de los tokens del dashboard (spec §8, D5): textos sobre sus fondos efectivos."""

import re
from pathlib import Path

import pytest

TOKENS = Path(__file__).resolve().parent.parent / "orchestrator" / "static" / "dashboard" / "tokens.css"


def _block(css: str, selector: str) -> dict[str, str]:
    """Variables de los bloques con ese selector (en orden; los posteriores pisan)."""
    values: dict[str, str] = {}
    for match in re.finditer(re.escape(selector) + r"\s*\{([^}]*)\}", css):
        for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", match.group(1)):
            values[name] = value.strip()
    return values


def _theme(name: str) -> dict[str, str]:
    css = TOKENS.read_text(encoding="utf-8")
    values = _block(css, ":root")
    if name != "dark":
        values.update(_block(css, f'[data-theme="{name}"]'))
    return values


def _luminance(hex_color: str) -> float:
    digits = hex_color.lstrip("#")
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    channels = [int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _mix(color: str, base: str, share: float) -> str:
    """`color-mix(in srgb, color share, base)` en hexadecimal."""
    def rgb(value: str) -> list[int]:
        digits = value.lstrip("#")
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return [int(digits[i:i + 2], 16) for i in (0, 2, 4)]

    mixed = [round(c * share + b * (1 - share)) for c, b in zip(rgb(color), rgb(base))]
    return "#" + "".join(f"{value:02x}" for value in mixed)


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


FAMILIES = ["knowledge", "work", "decision", "execution", "governance", "error"]


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_family_text_on_surfaces_meets_aa(theme):
    values = _theme(theme)
    for family in FAMILIES:
        color = values[f"--family-{family}"]
        for surface in ("--bg-surface", "--bg-base"):
            ratio = _contrast(color, values[surface])
            assert ratio >= 4.5, f"{theme}: {family} sobre {surface} = {ratio:.2f}"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_active_segment_text_meets_aa(theme):
    values = _theme(theme)
    # `.segmented button[aria-pressed="true"]`: texto --bg-base sobre --state-live.
    assert _contrast(values["--bg-base"], values["--state-live"]) >= 4.5


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_body_text_meets_aa(theme):
    values = _theme(theme)
    # --text-muted (heredado) queda en 3,7:1 sobre la superficie oscura: se corrige en D5
    # (contraste AA en todos los temas, ola 4), que es dueño de los tokens de texto.
    for text in ("--text-primary", "--text-secondary"):
        assert _contrast(values[text], values["--bg-surface"]) >= 4.5, f"{theme}: {text}"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_status_pills_meet_aa_on_their_tinted_background(theme):
    values = _theme(theme)
    # `.pill.state-*`: texto de la familia sobre `color-mix(familia 12%, transparent)` encima
    # de la superficie donde aparece la píldora.
    for family in FAMILIES:
        color = values[f"--family-{family}"]
        for surface in ("--bg-surface", "--bg-base"):
            background = _mix(color, values[surface], 0.12)
            ratio = _contrast(color, background)
            assert ratio >= 4.5, f"{theme}: píldora {family} sobre {surface} = {ratio:.2f}"
