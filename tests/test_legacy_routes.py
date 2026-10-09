"""Inventario de rutas POST heredadas (RFC-010 §7 PR 2, invariante I1).

El servidor despacha las rutas heredadas desde el inventario (`LEGACY_POST_HANDLERS`), así que
una ruta que no está ahí no existe. Estos tests impiden además las otras formas de agregar una
ruta: otro verbo HTTP, comparar `self.path` en `do_POST`, un handler `_post_*` que no esté en el
inventario o una llamada desde el frontend que el inventario no declara.
"""

import ast
import re
from pathlib import Path

from orchestrator.legacy_routes import (
    CATEGORIES, CONTEXT_DELETE_ROUTE, LEGACY_POST_HANDLERS, LEGACY_POST_ROUTES, OWNERS, by_path,
)

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "orchestrator" / "server.py"
STATIC = ROOT / "orchestrator" / "static" / "dashboard"
# Archivo de cada vista dueña (la barra vive en core.js).
# Métodos `_post_*` que no atienden una ruta (ayudantes del despacho).
POST_HELPERS = {"_post_body_length"}
OWNER_FILES = {
    "flujos": "legacy/flujos.js",
    "actividad": "legacy/actividad.js",
    "proyectos": "legacy/proyectos.js",
    "datos": "legacy/datos.js",
    "config": "legacy/config.js",
    "barra": "legacy/core.js",
}


def _handler_class() -> ast.ClassDef:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "DashboardHandler"]
    assert len(classes) == 1
    return classes[0]


def _methods() -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in _handler_class().body if isinstance(node, ast.FunctionDef)}


def test_only_get_and_post_are_dispatched():
    # El resto de los verbos responde 405 en handle_one_request (RFC-009).
    assert sorted(name for name in _methods() if name.startswith("do_")) == ["do_GET", "do_POST"]


def test_do_post_dispatches_only_from_the_inventory():
    do_post = _methods()["do_POST"]
    paths = {node.value for node in ast.walk(do_post)
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/")}
    assert paths <= {"/context/", "/delete"}, f"rutas fijas en do_POST fuera del inventario: {paths}"
    names = {node.id for node in ast.walk(do_post) if isinstance(node, ast.Name)}
    assert {"LEGACY_POST_HANDLERS", "CONTEXT_DELETE_ROUTE"} <= names
    # Nada de `self.path == "/x"` ni `self._post_*` llamados directo desde do_POST.
    for node in ast.walk(do_post):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute) and node.left.attr == "path":
            assert not any(isinstance(op, (ast.Eq, ast.In)) for op in node.ops), "do_POST compara self.path"
        if isinstance(node, ast.Attribute) and node.attr.startswith("_post_") and node.attr not in POST_HELPERS:
            raise AssertionError(f"do_POST llama {node.attr} sin pasar por el inventario")


def test_every_post_handler_is_inventoried_and_exists():
    methods = set(_methods())
    handlers = {name for name in methods if name.startswith("_post_")} - POST_HELPERS
    inventoried = set(LEGACY_POST_HANDLERS.values())
    assert handlers == inventoried, (
        f"sin inventariar: {handlers - inventoried}; inexistentes: {inventoried - handlers}")
    assert len(LEGACY_POST_ROUTES) == len(by_path()) == 27, "rutas repetidas o faltantes"
    assert CONTEXT_DELETE_ROUTE in by_path()


def test_each_route_has_valid_owners_category_and_flags():
    for route in LEGACY_POST_ROUTES:
        assert route.owners and set(route.owners) <= set(OWNERS), route.path
        if route.command is None:
            assert route.category is None and route.note, route.path
        else:
            assert route.category in CATEGORIES, route.path
            assert re.fullmatch(r"[a-z][a-z_]*", route.command), route.path
        if route.llm_provider:
            assert route.job and route.egress, f"{route.path}: una llamada a un proveedor es trabajo y egress"
        if route.destructive:
            assert route.category in {"maintenance", "project_admin"}, route.path
        if route.category == "append":
            assert route.command in {"run_task"}, f"{route.path}: `append` solo agrega (RFC-008)"


def _static_sources() -> dict[str, str]:
    return {str(path.relative_to(STATIC)).replace("\\", "/"): path.read_text(encoding="utf-8")
            for path in STATIC.rglob("*.js")}


POST_CALL = re.compile(r"\bpostJson\(\s*([^,)]+)")
# La única ruta armada que se admite: "/context/" + <id> + "/delete".
CONTEXT_DELETE_CALL = re.compile(
    r"""postJson\(\s*(['"])/context/\1\s*\+\s*(?:Number\(\s*\w+\s*\)|\w+)\s*\+\s*(['"])/delete\2\s*,""")


def test_post_calls_use_literal_routes():
    # Una ruta armada en tiempo de ejecución esconde a su llamador del inventario. Excepciones:
    # el borrado de contexto ("/context/" + id + "/delete") y `_syncOne(url)`, cuyos
    # llamadores pasan literales.
    for name, text in _static_sources().items():
        for match in POST_CALL.finditer(text):
            argument = match.group(1).strip()
            if re.fullmatch(r"""(['"`])/[^'"`$]*\1""", argument):
                continue
            if argument.startswith(('"/context/"', "'/context/'")):
                assert CONTEXT_DELETE_CALL.match(text, match.start()), (
                    f"{name}: solo se admite \"/context/\" + id + \"/delete\": {text[match.start():match.start() + 80]}")
                continue
            if name == "legacy/core.js" and argument == "url":
                continue
            raise AssertionError(f"{name}: postJson con ruta no literal: {argument}")
    core = _static_sources()["legacy/core.js"]
    for call in re.findall(r"_syncOne\(\s*([^,)]+)", core):
        assert call.strip() == "url" or re.fullmatch(r"""(['"])/[a-z-]+\1""", call.strip()), call


def _called_routes(text: str) -> set[str]:
    routes = set()
    # Literales completos; el "/context/" que se concatena con el id es el borrado de contexto.
    for match in re.finditer(r"""\b(?:postJson|_syncOne)\(\s*(['"`])(/[^'"`$]*)\1(\s*\+)?""", text):
        if not match.group(3):
            routes.add(match.group(2))
    if CONTEXT_DELETE_CALL.search(text):
        routes.add(CONTEXT_DELETE_ROUTE)
    return routes


def test_owners_match_the_files_that_call_each_route():
    callers: dict[str, set[str]] = {}
    for name, text in _static_sources().items():
        for route in _called_routes(text):
            callers.setdefault(route, set()).add(name)
    for route in LEGACY_POST_ROUTES:
        found = callers.pop(route.path, set())
        expected = set() if route.owners == ("ninguna",) else {OWNER_FILES[owner] for owner in route.owners}
        assert found == expected, f"{route.path}: lo llaman {found}, el inventario dice {expected}"
    # Llamadas POST a rutas que no son heredadas (ni de /api/v1/, que usa core/api.js).
    assert callers == {}, f"postJson a rutas fuera del inventario: {callers}"
