from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_INVISIBLE = {chr(0xFEFF): "U+FEFF", chr(0x200B): "U+200B", chr(0x200C): "U+200C", chr(0x200D): "U+200D"}


@pytest.mark.parametrize("path", sorted(
    p for folder in ("orchestrator", "tests", "scripts") for p in (_ROOT / folder).rglob("*.py")
), ids=lambda p: str(p.relative_to(_ROOT)))
def test_python_sources_have_no_invisible_characters(path):
    text = path.read_text(encoding="utf-8")
    found = [
        f"{line_no}: {name}"
        for line_no, line in enumerate(text.splitlines(), 1)
        for char, name in _INVISIBLE.items() if char in line
    ]
    assert not found, f"usá escapes (p. ej. \ufeff) en vez de caracteres invisibles: {found}"
