import os
from pathlib import Path

import pytest

from orchestrator.venv_python import venv_python, venv_python_rel


def test_windows_path_points_to_scripts_python_exe(tmp_path):
    result = Path(venv_python(tmp_path, is_windows=True))

    assert result.is_absolute()
    assert result.parts[-3:] == (".venv", "Scripts", "python.exe")


def test_posix_path_points_to_bin_python(tmp_path):
    result = Path(venv_python(tmp_path, is_windows=False))

    assert result.is_absolute()
    assert result.parts[-3:] == (".venv", "bin", "python")


@pytest.mark.skipif(os.name == "nt", reason="symlinks de venv POSIX")
def test_posix_venv_python_symlink_is_not_resolved(tmp_path):
    system_python = tmp_path / "system" / "python3"
    system_python.parent.mkdir()
    system_python.write_text("")
    bin_dir = tmp_path / "repo" / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(system_python)

    result = venv_python(tmp_path / "repo", is_windows=False)

    assert result == str(bin_dir / "python")
    assert Path(result).resolve() == system_python.resolve()


def test_relative_paths_per_os():
    assert venv_python_rel(is_windows=True) == ".venv/Scripts/python.exe"
    assert venv_python_rel(is_windows=False) == ".venv/bin/python"
