"""Estáticos del dashboard servidos con hash de contenido por directorio (spec §19.4 O3, §23.7).

Al iniciar, el servidor calcula un hash de todo `orchestrator/static/dashboard/` y lo
sirve bajo `/static/dashboard/<hash>/…` con caché inmutable. Los `import` relativos
entre módulos ES siguen funcionando porque todos comparten el mismo prefijo; un cambio
en cualquier archivo cambia el prefijo y el navegador vuelve a descargar.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

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
    root: Path
    version: str
    files: frozenset[str]

    def url(self, relative: str) -> str:
        if relative not in self.files:
            raise KeyError(relative)
        return f"{URL_PREFIX}{self.version}/{relative}"

    def resolve(self, url_path: str) -> Optional[tuple[Path, str]]:
        """(archivo, tipo MIME) para una ruta `/static/dashboard/<hash>/<archivo>`, o None."""
        if not url_path.startswith(URL_PREFIX):
            return None
        version, _, relative = url_path[len(URL_PREFIX):].partition("/")
        if version != self.version or relative not in self.files:
            return None
        return self.root / relative, MEDIA_TYPES[PurePosixPath(relative).suffix]


def _servable(relative: PurePosixPath) -> bool:
    return (
        relative.name not in NOT_SERVED
        and not any(part.startswith(".") for part in relative.parts)
        and relative.suffix in MEDIA_TYPES
    )


def build_bundle(root: Path = STATIC_ROOT) -> StaticBundle:
    """Inventario y hash del directorio; solo se sirven los archivos listados acá.

    El hash cubre la ruta y el contenido de cada archivo servible, así que renombrar,
    agregar, borrar o editar cualquiera cambia la versión.
    """
    digest = hashlib.sha256()
    files = []
    if root.is_dir():
        for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if not _servable(relative):
                continue
            files.append(str(relative))
            digest.update(str(relative).encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return StaticBundle(root=root, version=digest.hexdigest()[:HASH_LENGTH], files=frozenset(files))
