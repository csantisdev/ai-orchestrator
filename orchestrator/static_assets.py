"""Estáticos del dashboard servidos con hash de contenido por directorio (spec §19.4 O3, §23.7).

Al iniciar, el servidor lee todo `orchestrator/static/dashboard/`, calcula un hash de rutas
y contenidos y sirve esa instantánea en memoria bajo `/static/dashboard/<hash>/…` con caché
inmutable. Los `import` relativos entre módulos ES siguen funcionando porque todos comparten
el mismo prefijo. Lo servido es exactamente lo que se hasheó: un cambio en el disco después
del arranque no se sirve hasta reiniciar, que es cuando cambia el prefijo.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, Optional

STATIC_ROOT = Path(__file__).parent / "static" / "dashboard"
URL_PREFIX = "/static/dashboard/"
CACHE_CONTROL = "public, max-age=31536000, immutable"
MEDIA_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
}
# Archivos del directorio que existen para Node o el repo y no se sirven al navegador.
NOT_SERVED = {"package.json"}
HASH_LENGTH = 12


@dataclass(frozen=True)
class StaticBundle:
    version: str
    contents: Mapping[str, bytes]

    @property
    def files(self) -> frozenset[str]:
        return frozenset(self.contents)

    def url(self, relative: str) -> str:
        if relative not in self.contents:
            raise KeyError(relative)
        return f"{URL_PREFIX}{self.version}/{relative}"

    def resolve(self, url_path: str) -> Optional[tuple[bytes, str]]:
        """(bytes, tipo MIME) para `/static/dashboard/<hash>/<archivo>`, o None."""
        if not url_path.startswith(URL_PREFIX):
            return None
        version, _, relative = url_path[len(URL_PREFIX):].partition("/")
        if version != self.version or relative not in self.contents:
            return None
        return self.contents[relative], MEDIA_TYPES[PurePosixPath(relative).suffix]


def _servable(relative: PurePosixPath) -> bool:
    return (
        relative.name not in NOT_SERVED
        and not any(part.startswith(".") for part in relative.parts)
        and relative.suffix in MEDIA_TYPES
    )


def build_bundle(root: Path = STATIC_ROOT) -> StaticBundle:
    """Instantánea inmutable del directorio: inventario, contenidos y hash.

    Solo entran archivos regulares (no symlinks) dentro de `root`. El hash cubre la ruta y
    el contenido de cada archivo servible, así que renombrar, agregar, borrar o editar
    cualquiera cambia la versión.
    """
    digest = hashlib.sha256()
    contents: dict[str, bytes] = {}
    if root.is_dir():
        resolved_root = root.resolve()
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            if not path.resolve().is_relative_to(resolved_root):
                continue
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if not _servable(relative):
                continue
            data = path.read_bytes()
            contents[str(relative)] = data
            digest.update(str(relative).encode("utf-8") + b"\0")
            digest.update(data)
            digest.update(b"\0")
    return StaticBundle(version=digest.hexdigest()[:HASH_LENGTH], contents=MappingProxyType(contents))
