"""Inventario de rutas POST heredadas (RFC-010 §7 PR 2, invariante I1)."""

import re
from pathlib import Path

from orchestrator.legacy_routes import CATEGORIES, LEGACY_POST_ROUTES, OWNERS, by_path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "orchestrator" / "server.py"
STATIC = ROOT / "orchestrator" / "static" / "dashboard"
# Archivo heredado de cada vista dueña (la barra vive en core.js).
OWNER_FILES = {
    "flujos": "legacy/flujos.js",
    "actividad": "legacy/actividad.js",
    "proyectos": "legacy/proyectos.js",
    "datos": "legacy/datos.js",
    "config": "legacy/config.js",
    "barra": "legacy/core.js",
}


def _do_post_source() -> str:
    text = SERVER.read_text(encoding="utf-8")
    start = text.index("        def do_POST(self):")
    end = text.index("\n        def ", start + 1)
    return text[start:end]


def _server_post_routes() -> set[str]:
    source = _do_post_source()
    routes = set(re.findall(r'"(/[^"]+)":\s*self\._post_', source))
    prefixes = set(re.findall(r'self\.path\.startswith\("([^"]+)"\)', source))
    if 'self.path.startswith("/context/") and self.path.endswith("/delete")' in source:
        routes.add("/context/{id}/delete")
        prefixes.discard("/context/")
    # Cualquier otro despacho por prefijo fuera de /api/v1/ tiene que agregarse acá a mano.
    assert prefixes == set(), f"despacho POST por prefijo sin inventariar: {prefixes}"
    return routes


def test_every_post_route_outside_the_api_is_in_the_inventory():
    server = _server_post_routes()
    inventory = set(by_path())
    assert len(LEGACY_POST_ROUTES) == len(inventory), "rutas repetidas en el inventario"
    assert server - inventory == set(), "ruta POST nueva fuera de /api/v1/ y del inventario (I1)"
    assert inventory - server == set(), "el inventario lista rutas que el servidor ya no atiende"
    assert len(server) == 27


def test_each_route_has_valid_owners_category_and_command():
    for route in LEGACY_POST_ROUTES:
        assert route.owners and set(route.owners) <= set(OWNERS), route.path
        if route.command is None:
            assert route.category is None and route.note, route.path
        else:
            assert route.category in CATEGORIES, route.path
            assert re.fullmatch(r"[a-z][a-z_]*", route.command), route.path
        if route.provider:
            assert route.job, f"{route.path}: una llamada a proveedor corre como trabajo (RFC-010 §3.3)"
        if route.destructive:
            assert route.category in {"maintenance", "project_admin"}, route.path
    assert {route.category for route in LEGACY_POST_ROUTES if route.category} <= CATEGORIES


def _static_sources() -> dict[str, str]:
    return {str(path.relative_to(STATIC)).replace("\\", "/"): path.read_text(encoding="utf-8")
            for path in STATIC.rglob("*.js")}


def _mentions(source: str, path: str) -> bool:
    if path == "/context/{id}/delete":
        return bool(re.search(r"/context/[^\"'`]*/delete|/delete[\"'`]", source))
    return f'"{path}"' in source or f"'{path}'" in source or f"`{path}" in source


def test_owners_match_the_files_that_call_each_route():
    sources = _static_sources()
    for route in LEGACY_POST_ROUTES:
        callers = {name for name, text in sources.items() if _mentions(text, route.path)}
        if route.owners == ("ninguna",):
            assert callers == set(), f"{route.path} figura sin llamador pero lo usa {callers}"
            continue
        expected = {OWNER_FILES[owner] for owner in route.owners}
        assert expected <= callers, f"{route.path}: no lo llama {expected - callers}"
        unexpected = {name for name in callers - expected if name.startswith("legacy/")}
        assert unexpected == set(), f"{route.path}: también lo llama {unexpected}; agregá la vista dueña"
