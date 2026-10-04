"""API JSON del dashboard nuevo (spec §24.3.2).

Cada vertical declara sus endpoints en su propio módulo (`api_v1/<vertical>.py`) con el
decorador `route`; `discover()` importa todos los módulos del paquete al iniciar. Ni
`server.py` ni un archivo central de rutas se editan al sumar un vertical.

Los handlers son funciones puras respecto del transporte: reciben un `Request` y devuelven
un dict (200) o `(status, dict)`. El servidor aplica antes los controles de RFC-009 y se
encarga de serializar y de las cabeceras.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

_log = logging.getLogger(__name__)
PREFIX = "/api/v1/"
METHODS = ("GET", "POST")

Payload = Union[dict, tuple[int, dict]]


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    params: dict[str, str] = field(default_factory=dict)
    query: dict[str, list[str]] = field(default_factory=dict)
    body: Optional[dict] = None

    def arg(self, name: str, default: Optional[str] = None) -> Optional[str]:
        values = self.query.get(name)
        return values[0] if values else default


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    regex: re.Pattern
    handler: Callable[[Request], Payload]
    module: str


_PARAM = re.compile(r"\{([a-z_]+)\}")


def _compile(pattern: str) -> re.Pattern:
    if not pattern.startswith(PREFIX):
        raise ValueError(f"la ruta debe empezar con {PREFIX}: {pattern!r}")
    regex = ""
    last = 0
    for match in _PARAM.finditer(pattern):
        regex += re.escape(pattern[last:match.start()]) + rf"(?P<{match.group(1)}>[^/]+)"
        last = match.end()
    regex += re.escape(pattern[last:])
    return re.compile(f"^{regex}$")


class Registry:
    """Rutas registradas; el paquete usa una instancia y los tests pueden crear otras."""

    def __init__(self) -> None:
        self.routes: list[Route] = []

    def route(self, method: str, pattern: str):
        """Registra un endpoint; `{nombre}` en el patrón captura un segmento de la ruta."""
        if method not in METHODS:
            raise ValueError(f"método no soportado: {method!r}")
        compiled = _compile(pattern)

        def decorator(handler: Callable[[Request], Payload]):
            for existing in self.routes:
                if existing.method == method and existing.pattern == pattern:
                    raise ValueError(f"ruta duplicada: {method} {pattern} ({existing.module})")
            self.routes.append(Route(method, pattern, compiled, handler, handler.__module__))
            return handler

        return decorator

    def match(self, method: str, path: str) -> tuple[Optional[Route], dict[str, str], bool]:
        """(ruta, parámetros decodificados, la ruta existe con otro método)."""
        other_method = False
        for candidate in self.routes:
            found = candidate.regex.match(path)
            if not found:
                continue
            if candidate.method == method:
                params = {}
                for name, raw in found.groupdict().items():
                    value = urllib.parse.unquote(raw)
                    # Un segmento codificado no puede convertirse en varios: `%2F` y `%5C`
                    # inyectarían separadores que el patrón no aceptó.
                    if "/" in value or "\\" in value or "\x00" in value:
                        return None, {}, False
                    params[name] = value
                return candidate, params, False
            other_method = True
        return None, {}, other_method

    def dispatch(self, request: Request) -> tuple[int, dict]:
        """Ejecuta el endpoint y normaliza la respuesta a `(status, payload)`.

        `ValueError` del handler es un error del cliente (400) y su mensaje se devuelve: los
        handlers lo usan para explicar qué parámetro es inválido. Cualquier otra excepción, o
        una respuesta que no sea un objeto con un status válido, es un 500 genérico: el
        detalle (rutas, SQL, configuración) se registra en el servidor y no viaja al cliente.
        Un endpoint inexistente es 404 y uno que existe con otro método, 405.
        """
        found, params, other_method = self.match(request.method, request.path)
        if found is None:
            return (405, {"error": "method not allowed"}) if other_method else (404, {"error": "not found"})
        try:
            result = found.handler(Request(request.method, request.path, params, request.query, request.body))
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except Exception:
            _log.exception("api_v1: error en %s %s", request.method, found.pattern)
            return 500, {"error": "internal error"}
        status, payload = result if isinstance(result, tuple) and len(result) == 2 else (200, result)
        if not isinstance(status, int) or isinstance(status, bool) or not 200 <= status <= 599 \
                or not isinstance(payload, dict):
            _log.error("api_v1: respuesta inválida de %s %s", request.method, found.pattern)
            return 500, {"error": "internal error"}
        return status, payload


REGISTRY = Registry()
route = REGISTRY.route
match = REGISTRY.match
dispatch = REGISTRY.dispatch


def discover() -> list[Route]:
    """Importa todos los módulos del paquete y devuelve las rutas registradas."""
    for module in pkgutil.iter_modules(__path__):
        if not module.name.startswith("_"):
            importlib.import_module(f"{__name__}.{module.name}")
    return list(REGISTRY.routes)
