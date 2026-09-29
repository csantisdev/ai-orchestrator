"""Rutas al intérprete del .venv del repo según el sistema operativo."""

from __future__ import annotations

import os
from pathlib import Path


def _host_is_windows(is_windows: bool | None) -> bool:
    return os.name == "nt" if is_windows is None else is_windows


def venv_python_rel(is_windows: bool | None = None) -> str:
    """Ruta relativa al repo: .venv/Scripts/python.exe o .venv/bin/python."""
    return ".venv/Scripts/python.exe" if _host_is_windows(is_windows) else ".venv/bin/python"


def venv_python(project_root: Path, is_windows: bool | None = None) -> str:
    """Ruta absoluta al Python del .venv de `project_root`.

    En Windows conserva el comportamiento histórico (Path.resolve). En POSIX
    usa os.path.abspath: .venv/bin/python suele ser un symlink al Python del
    sistema y resolverlo haría que el cliente MCP arranque fuera del venv.
    """
    if _host_is_windows(is_windows):
        return str((Path(project_root) / ".venv" / "Scripts" / "python.exe").resolve())
    return os.path.abspath(os.path.join(os.fspath(project_root), ".venv", "bin", "python"))
