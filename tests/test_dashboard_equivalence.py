"""Equivalencia del dashboard heredado frente a una instantánea dorada (spec §24.3.1).

La separación por vista no puede cambiar lo que ve el navegador. Con reloj y zona
fijos y datos sintéticos deterministas:

- el HTML de `build_html` y de `_build_contexts_section` y el CSS se comparan byte a
  byte (el bloque de JS embebido se compara aparte);
- el JS se compara como multiconjunto de bloques de nivel superior: agrupar por vista
  cambia el orden de las declaraciones, pero ningún bloque puede cambiar, aparecer o
  desaparecer, y el bloque de exportaciones y arranque sigue al final.

Para regenerar la instantánea (solo si el cambio de salida es intencional):
`python -m tests.test_dashboard_equivalence`.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden" / "dashboard"
TZ = timezone(timedelta(hours=-3), "TST")
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=TZ)
JS_START = "<script>\ntry {\n"
JS_END = "\n} catch(e) {"
JS_PLACEHOLDER = "<script>\ntry {\n/*JS*/\n} catch(e) {"
TAIL_MARKER = "Object.assign(window, {"
CHUNK_START = re.compile(
    r"^(?:async function |function |var |let |const |\(function|document\.|window\.|"
    r"Object\.assign|refreshStaleRateOnLoad\(|// )"
)

RUNS = [
    {"id": 1, "ts": "2026-06-01T10:00:00-03:00", "project": "mi-proyecto", "provider": "claude",
     "model": "claude-opus", "status": "done", "duration_ms": 1500, "input_tokens": 1200,
     "output_tokens": 800, "cost_usd": 0.42, "cache_read_tokens": 300,
     "task_preview": "Revisar el módulo de pagos", "routing_reason": "Elegido por señales"},
    {"id": 2, "ts": "2026-05-31T22:00:00+00:00", "project": "otro-proyecto", "provider": "deepseek",
     "model": "deepseek/deepseek-v4", "status": "done", "duration_ms": 65000, "input_tokens": 50000,
     "output_tokens": 1000000, "cost_usd": 1.5, "cache_read_tokens": 0,
     "task_preview": "x</script><script>window.__xss=1</script>", "routing_reason": "Elegido manualmente"},
    {"id": 3, "ts": "2026-05-20T08:00:00-04:00", "project": "mi-proyecto", "provider": "openai",
     "model": "gpt-5", "status": "error", "duration_ms": None, "input_tokens": None,
     "output_tokens": None, "cost_usd": None, "cache_read_tokens": None,
     "task_preview": "<img src=x onerror=alert(1)>", "routing_reason": "Research mode"},
]
CONTEXTS = [
    {"id": 7, "project": "mi-proyecto", "title": "Flujo de pagos 'beta'", "status": "active",
     "description": "Detalle <b>con</b> marcado",
     "steps": [
         {"id": 70, "order_idx": 1, "title": "Diseño", "status": "completed", "provider": "claude"},
         {"id": 71, "order_idx": 2, "title": "Implementación", "status": "in_progress", "provider": "codex"},
         {"id": 72, "order_idx": 3, "title": "Revisión", "status": "pending", "provider": ""},
     ]},
    {"id": 8, "project": "otro-proyecto", "title": "Sin pasos", "status": "programado",
     "description": "", "steps": []},
    {"id": 9, "project": "otro-proyecto", "title": "Cerrado", "status": "completed",
     "description": None,
     "steps": [{"id": 90, "order_idx": 1, "title": "Único", "status": "skipped", "provider": "deepseek"}]},
]


class _Aware:
    def __init__(self, value: datetime):
        self._value = value

    def astimezone(self, tz=None):
        value = self._value if self._value.tzinfo else self._value.replace(tzinfo=timezone.utc)
        return value.astimezone(tz or TZ)


class _FixedClock:
    @staticmethod
    def now(tz=None):
        return _Aware(NOW)

    @staticmethod
    def fromisoformat(text):
        return _Aware(datetime.fromisoformat(text))


def _fixed_local_date(ts_raw, tz=None):
    try:
        value = datetime.fromisoformat(ts_raw)
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ).date()


def _pin_clock(monkeypatch):
    import orchestrator.dashboard as dashboard

    monkeypatch.setattr(dashboard, "datetime", _FixedClock)
    monkeypatch.setattr(dashboard, "_local_date_from_ts", _fixed_local_date)


def render() -> dict[str, str]:
    """Salidas del dashboard con datos sintéticos; requiere el reloj fijado."""
    from orchestrator.dashboard import _build_contexts_section, build_html
    from orchestrator.dashboard_css import _build_css
    from orchestrator.dashboard_js import _build_js

    return {
        "page_all.html": build_html(RUNS, projects_extra=["proyecto-vacio"], session_token="token-fijo"),
        "page_selected.html": build_html(RUNS, selected_project="mi-proyecto", session_token="token-fijo"),
        "page_empty.html": build_html([], session_token="token-fijo"),
        "contexts.html": _build_contexts_section(CONTEXTS),
        "contexts_empty.html": _build_contexts_section([]),
        "style.css": _build_css(),
        "script.js": _build_js(),
    }


def split_page(page: str) -> tuple[str, str]:
    start = page.index(JS_START) + len(JS_START)
    end = page.index(JS_END, start)
    return page[:start - len(JS_START)] + JS_PLACEHOLDER + page[end + len(JS_END):], page[start:end]


def js_chunks(js: str) -> list[str]:
    """Bloques de nivel superior del JS, sin los que son solo comentarios.

    Los comentarios no cambian el comportamiento; cualquier línea de código distinta
    sí cambia algún bloque.
    """
    chunks: list[list[str]] = []
    for line in js.split("\n"):
        if CHUNK_START.match(line) or not chunks:
            chunks.append([line])
        else:
            chunks[-1].append(line)
    result = []
    for chunk in chunks:
        text = "\n".join(chunk).rstrip()
        if any(line.strip() and not line.startswith("//") for line in chunk):
            result.append(text)
    return result


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")


@pytest.fixture
def outputs(monkeypatch):
    _pin_clock(monkeypatch)
    return render()


@pytest.mark.parametrize("name", ["page_all.html", "page_selected.html", "page_empty.html"])
def test_page_html_is_byte_identical_outside_the_script(outputs, name):
    html, _ = split_page(outputs[name])

    assert html == _golden(name)


@pytest.mark.parametrize("name", ["contexts.html", "contexts_empty.html", "style.css"])
def test_contexts_and_css_are_byte_identical(outputs, name):
    assert outputs[name] == _golden(name)


def test_every_page_embeds_the_same_script(outputs):
    scripts = {split_page(outputs[name])[1] for name in ("page_all.html", "page_selected.html", "page_empty.html")}

    assert scripts == {outputs["script.js"]}


def test_script_has_the_same_top_level_blocks(outputs):
    current = js_chunks(outputs["script.js"])
    golden = js_chunks(_golden("script.js"))

    missing = Counter(golden) - Counter(current)
    extra = Counter(current) - Counter(golden)
    assert not missing and not extra, (list(missing)[:3], list(extra)[:3])


LOAD_TIME_EFFECTS = ("(function", "document.", "const evtSource", "Object.assign", "refreshStaleRateOnLoad()")


def test_code_that_runs_at_load_keeps_its_relative_order(outputs):
    def effects(js):
        return [chunk for chunk in js_chunks(js) if chunk.startswith(LOAD_TIME_EFFECTS)]

    assert effects(outputs["script.js"]) == effects(_golden("script.js"))
    assert len(effects(outputs["script.js"])) == 5


def test_block_boundaries_never_fall_inside_a_template_literal(outputs):
    """El corte por líneas en columna 0 sería engañoso dentro de un template literal."""
    for js in (outputs["script.js"], _golden("script.js")):
        backticks = 0
        for line in js.split("\n"):
            if CHUNK_START.match(line):
                assert backticks % 2 == 0, line
            backticks += len(re.findall(r"(?<!\\)`", line))


def test_exports_and_startup_calls_stay_last(outputs):
    chunks = js_chunks(outputs["script.js"])

    assert chunks[-2].startswith(TAIL_MARKER)
    assert chunks[-1] == "refreshStaleRateOnLoad();"


def _write_golden() -> None:
    import types

    patcher = types.SimpleNamespace(setattr=lambda obj, name, value: setattr(obj, name, value))
    _pin_clock(patcher)
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, text in render().items():
        if name.startswith("page_"):
            text = split_page(text)[0]
        (GOLDEN / name).write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    _write_golden()
