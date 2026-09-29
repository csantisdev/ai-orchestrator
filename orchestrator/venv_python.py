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


def repaired_venv_command(
    command: str, project_root: Path, cwd: Path | None = None, is_windows: bool | None = None,
) -> str | None:
    """Command POSIX que reemplaza la ruta Windows del .venv de este repo, o None.

    Solo corrige lo que versiones anteriores generaban en POSIX
    (<repo>/.venv/Scripts/python.exe o la ruta relativa de la plantilla) y
    únicamente si ese archivo no existe. La ruta relativa exige que `cwd` sea
    la raíz del repo; sin cwd conocido no se toca. Cualquier otro command se respeta.
    """
    if _host_is_windows(is_windows):
        return None
    windows_python = Path(project_root) / ".venv" / "Scripts" / "python.exe"
    if windows_python.exists():
        return None
    legacy_absolute = {
        str(windows_python.resolve()),
        os.path.abspath(os.fspath(windows_python)),
    }
    if command in legacy_absolute:
        return venv_python(project_root, is_windows=False)
    if command == venv_python_rel(is_windows=True):
        if cwd is None or Path(cwd).resolve() != Path(project_root).resolve():
            return None
        return venv_python_rel(is_windows=False)
    return None
