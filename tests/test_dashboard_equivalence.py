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
# Un bloque empieza en cualquier línea en columna 0 que no cierre una estructura.
# `test_block_boundaries_are_top_level_code` verifica con un analizador léxico que
# cada corte cae en código de nivel superior.
CHUNK_START = re.compile(r"^[^\s})\]]")
DECLARATION = re.compile(r"^(?:async function |function |var |let |const |//)")
REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")
REGEX_KEYWORDS = {"return", "typeof", "case", "in", "of", "new", "delete", "void", "throw", "else", "do"}


def top_level_lines(js: str) -> set[int]:
    """Índices de línea que empiezan en código de nivel superior.

    Recorre el JS siguiendo strings, template literals (con `${}` anidados),
    comentarios y literales de regex, y la profundidad de llaves, paréntesis y
    corchetes; una línea es de nivel superior si empieza fuera de todo eso.
    """
    result = set()
    stack: list[str] = []
    depth = 0
    i, line, n = 0, 0, len(js)
    prev = ""
    word = ""
    at_line_start = True
    while i < n:
        ch = js[i]
        mode = stack[-1] if stack else "code"
        if at_line_start:
            if mode == "code" and depth == 0:
                result.add(line)
            at_line_start = False
        if ch == "\n":
            line += 1
            at_line_start = True
            if mode == "line_comment":
                stack.pop()
            i += 1
            continue
        if mode == "line_comment":
            i += 1
            continue
        if mode == "block_comment":
            if js.startswith("*/", i):
                stack.pop()
                i += 2
                continue
            i += 1
            continue
        if mode in ("'", '"'):
            if ch == "\\":
                i += 2
                continue
            if ch == mode:
                stack.pop()
                prev = ch
            i += 1
            continue
        if mode == "regex":
            if ch == "\\":
                i += 2
                continue
            if ch == "[":
                stack.append("regex_class")
            elif ch == "/":
                stack.pop()
                prev = "a"
            i += 1
            continue
        if mode == "regex_class":
            if ch == "\\":
                i += 2
                continue
            if ch == "]":
                stack.pop()
            i += 1
            continue
        if mode == "template":
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                stack.pop()
                prev = "`"
            elif js.startswith("${", i):
                stack.append("template_expr")
                i += 2
                continue
            i += 1
            continue
        # código (nivel superior o dentro de ${...})
        if ch.isalnum() or ch in "_$":
            word += ch
            prev = ch
            i += 1
            continue
        if word:
            last_word, word = word, ""
        else:
            last_word = ""
        if ch.isspace():
            i += 1
            if last_word:
                prev = "a" if last_word not in REGEX_KEYWORDS else "kw"
            continue
        if js.startswith("//", i):
            stack.append("line_comment")
            i += 2
            continue
        if js.startswith("/*", i):
            stack.append("block_comment")
            i += 2
            continue
        if ch in ("'", '"'):
            stack.append(ch)
        elif ch == "`":
            stack.append("template")
        elif ch == "/" and (prev in REGEX_PRECEDERS or prev in ("", "kw") or last_word in REGEX_KEYWORDS):
            stack.append("regex")
        elif ch in "{([":
            if mode in ("template_expr", "template_brace") and ch == "{":
                stack.append("template_brace")
            else:
                depth += 1
        elif ch in "})]":
            if mode == "template_expr" and ch == "}":
                stack.pop()
            elif mode == "template_brace" and ch == "}":
                stack.pop()
            else:
                depth -= 1
        prev = ch
        i += 1
    return result

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


FUNCTION_DECLARATION = re.compile(r"^(?:async )?function [\w$]+\(")
VARIABLE_DECLARATION = re.compile(r"^(?:var|let|const) [\w$]+\s*(?:=\s*(?P<init>.*?))?;?\s*$", re.S)
STRING_LITERAL = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'")
OBJECT_KEY = re.compile(r"[\w$]+\s*:")
LITERAL_TOKENS = {"{", "}", "[", "]", ",", ":", "S", "true", "false", "null"}


def _is_reorderable(chunk: str) -> bool:
    """Una función declarada (se eleva) o una variable con valor inicial literal puro.

    Todo lo demás —incluidos `const` con llamadas como `new EventSource(...)`— se
    ejecuta al cargar en el orden del archivo.

    Vale para el JS heredado actual, donde ningún código de carga lee estas
    variables. No es una regla general: si se agrega código de carga que las lea,
    una declaración literal también pasa a depender del orden (zona muerta temporal
    de let/const, o `undefined` de un `var` antes de su inicializador).
    """
    code = "\n".join(line for line in chunk.split("\n") if not line.lstrip().startswith("//")).strip()
    if FUNCTION_DECLARATION.match(code):
        return True
    match = VARIABLE_DECLARATION.match(code)
    if not match:
        return False
    init = match.group("init")
    if init is None:
        return True
    rest = OBJECT_KEY.sub(":", STRING_LITERAL.sub("S", init))
    tokens = re.findall(r"[A-Za-z_$][\w$]*|-?\d+(?:\.\d+)?|\S", rest)
    return all(token in LITERAL_TOKENS or re.fullmatch(r"-?\d+(?:\.\d+)?", token) for token in tokens)


def _load_time_code(js: str) -> list[str]:
    """Bloques que se ejecutan al cargar con efectos de orden: todo lo no reordenable."""
    return [chunk for chunk in js_chunks(js) if not _is_reorderable(chunk)]


def test_code_that_runs_at_load_keeps_its_relative_order(outputs):
    current = _load_time_code(outputs["script.js"])

    assert current == _load_time_code(_golden("script.js"))
    assert any(chunk.startswith('const evtSource = new EventSource("/events")') for chunk in current)
    assert any(chunk.startswith('evtSource.addEventListener("trace"') for chunk in current)
    assert current[-2].startswith(TAIL_MARKER) and current[-1] == "refreshStaleRateOnLoad();"


@pytest.mark.parametrize("chunk, reorderable", [
    ("function f() {\n  return 1;\n}", True),
    ("async function g(x) {}", True),
    ("var _page = 0;", True),
    ("let _filter = \"all\";", True),
    ("let _cb = null;", True),
    ("let x;", True),
    ("const _map = {};", True),
    ("const P = {\n  \"claude-code\": { label: \"Sync\", color: \"#22c55e\" },\n  git: { n: -1.5 },\n};", True),
    ("const es = new EventSource(\"/events\");", False),
    ("const f = window.fetch.bind(window);", False),
    ("let n = compute();", False),
    ("const o = { a: helper() };", False),
    ("evtSource.addEventListener(\"x\", e => e);", False),
    ("(function() {})();", False),
    ("refreshStaleRateOnLoad();", False),
])
def test_reorderable_blocks_are_only_hoisted_functions_and_literal_declarations(chunk, reorderable):
    assert _is_reorderable(chunk) is reorderable


def test_block_boundaries_are_top_level_code(outputs):
    """Cada corte cae fuera de strings, template literals, comentarios, regex y llaves."""
    for js in (outputs["script.js"], _golden("script.js")):
        top = top_level_lines(js)
        starts = [i for i, line in enumerate(js.split("\n")) if CHUNK_START.match(line) or line.startswith("//")]
        assert starts and all(i in top for i in starts), [js.split("\n")[i] for i in starts if i not in top][:3]


@pytest.mark.parametrize("snippet, expected_top", [
    ("const a = `\nfunction no() {}\n`;\nfunction si() {}", {0, 3}),
    ("const r = /`[}]/g;\nfunction si() {}", {0, 1}),
    ("const s = '`';\nfunction si() {}", {0, 1}),
    ("// `\nfunction si() {}", {0, 1}),
    ("/* `\n*/\nfunction si() {}", {0, 2}),
    ("const t = `${ {a: 1}.a }`;\nfunction si() {}", {0, 1}),
    ("const u = `a ${ `b ${ `c\n}` }` }`;\nfunction si() {}", {0, 2}),
    ("const x = 4 / 2;\nconst y = `\n}`;\nfunction si() {}", {0, 1, 3}),
    ("function f() {\n  return `x`;\n}\nlet z;", {0, 3}),
])
def test_lexer_recognizes_top_level_lines(snippet, expected_top):
    assert top_level_lines(snippet) == expected_top


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
