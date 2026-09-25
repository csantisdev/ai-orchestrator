"""Benchmark local y reproducible para validar tests generados.

No invoca proveedores ni persiste prompts, respuestas o comandos. El manifest
queda local y el reporte contiene solo métricas agregadas.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess
import time
from typing import Any

import yaml


TASK_CLASSES = frozenset({
    "unit",
    "integration",
    "regression",
    "schema",
    "edge_case",
})
_CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class BenchmarkManifestError(ValueError):
    """El manifest no representa un benchmark local válido."""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    task_class: str
    test_command: tuple[str, ...]
    mutation_command: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class BenchmarkAssignment:
    case: BenchmarkCase
    model: str


def _command(value: Any, field: str, case_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(arg, str) and arg for arg in value
    ):
        raise BenchmarkManifestError(
            f"{case_id}: {field} debe ser una lista no vacía de strings."
        )
    return tuple(value)


def load_manifest(path: Path) -> list[BenchmarkCase]:
    """Carga y valida un manifest local sin ejecutar comandos."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BenchmarkManifestError(f"No se pudo leer el manifest: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise BenchmarkManifestError("El manifest debe contener una lista 'cases'.")

    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()
    for entry in raw["cases"]:
        if not isinstance(entry, dict):
            raise BenchmarkManifestError("Cada caso debe ser un objeto.")
        case_id = entry.get("case_id")
        task_class = entry.get("task_class")
        if not isinstance(case_id, str) or not _CASE_ID_RE.fullmatch(case_id):
            raise BenchmarkManifestError(
                "case_id debe usar 1-64 caracteres [a-z0-9_-]."
            )
        if case_id in seen_ids:
            raise BenchmarkManifestError(f"case_id duplicado: {case_id}")
        if task_class not in TASK_CLASSES:
            raise BenchmarkManifestError(f"{case_id}: task_class inválido.")
        timeout_seconds = entry.get("timeout_seconds", 60)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 600
        ):
            raise BenchmarkManifestError(
                f"{case_id}: timeout_seconds debe estar entre 1 y 600."
            )
        seen_ids.add(case_id)
        cases.append(BenchmarkCase(
            case_id=case_id,
            task_class=task_class,
            test_command=_command(entry.get("test_command"), "test_command", case_id),
            mutation_command=_command(
                entry.get("mutation_command"), "mutation_command", case_id
            ),
            timeout_seconds=timeout_seconds,
        ))

    if not cases:
        raise BenchmarkManifestError("El manifest debe contener al menos un caso.")
    return cases


def assign_cases(
    cases: list[BenchmarkCase],
    models: list[str],
    seed: str,
) -> list[BenchmarkAssignment]:
    """Asigna modelos por hash, balanceando cada clase con diferencia máxima uno."""
    cleaned_models = [model.strip() for model in models if model.strip()]
    if len(cleaned_models) < 2 or len(set(cleaned_models)) != len(cleaned_models):
        raise BenchmarkManifestError("Se requieren al menos dos modelos distintos.")
    if not seed:
        raise BenchmarkManifestError("seed no puede estar vacío.")

    by_class: dict[str, list[BenchmarkCase]] = defaultdict(list)
    for case in cases:
        by_class[case.task_class].append(case)

    assignments: list[BenchmarkAssignment] = []
    for task_class in sorted(by_class):
        ordered = sorted(
            by_class[task_class],
            key=lambda case: (
                hashlib.sha256(
                    f"{seed}:{task_class}:{case.case_id}".encode("utf-8")
                ).digest(),
                case.case_id,
            ),
        )
        assignments.extend(
            BenchmarkAssignment(case=case, model=cleaned_models[index % len(cleaned_models)])
            for index, case in enumerate(ordered)
        )
    return assignments


def _empty_metrics() -> dict[str, int]:
    return {
        "planned": 0,
        "executed": 0,
        "baseline_passed": 0,
        "baseline_failed": 0,
        "mutation_detected": 0,
        "mutation_missed": 0,
        "timeouts": 0,
    }


def _run_command(command: tuple[str, ...], cwd: Path, timeout_seconds: int) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    return "passed" if completed.returncode == 0 else "failed"


def run_benchmark(
    manifest_path: Path,
    models: list[str],
    seed: str,
    execute: bool = False,
) -> dict[str, Any]:
    """Valida el manifest y, con execute, mide tests y mutaciones localmente."""
    cases = load_manifest(manifest_path)
    assignments = assign_cases(cases, models, seed)
    metrics: dict[tuple[str, str], dict[str, int]] = defaultdict(_empty_metrics)

    for assignment in assignments:
        key = (assignment.model, assignment.case.task_class)
        group = metrics[key]
        group["planned"] += 1
        if not execute:
            continue

        group["executed"] += 1
        baseline = _run_command(
            assignment.case.test_command,
            manifest_path.parent,
            assignment.case.timeout_seconds,
        )
        if baseline == "timeout":
            group["timeouts"] += 1
            group["baseline_failed"] += 1
            continue
        if baseline == "failed":
            group["baseline_failed"] += 1
            continue

        group["baseline_passed"] += 1
        mutation = _run_command(
            assignment.case.mutation_command,
            manifest_path.parent,
            assignment.case.timeout_seconds,
        )
        if mutation == "timeout":
            group["timeouts"] += 1
            continue
        if mutation == "failed":
            group["mutation_detected"] += 1
        else:
            group["mutation_missed"] += 1

    groups = []
    for (model, task_class), group in sorted(metrics.items()):
        baseline_passed = group["baseline_passed"]
        groups.append({
            "model": model,
            "task_class": task_class,
            **group,
            "mutation_detection_rate": (
                group["mutation_detected"] / baseline_passed
                if baseline_passed else None
            ),
        })

    return {
        "executed": execute,
        "planned_cases": len(assignments),
        "groups": groups,
    }
