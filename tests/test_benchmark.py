import sys

import pytest
import yaml

from orchestrator.benchmark import (
    BenchmarkManifestError,
    assign_cases,
    load_manifest,
    run_benchmark,
)


def _manifest(tmp_path, cases):
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump({"cases": cases}), encoding="utf-8")
    return path


def _case(case_id, task_class="unit", test_command=None, mutation_command=None):
    return {
        "case_id": case_id,
        "task_class": task_class,
        "test_command": test_command or [sys.executable, "-c", "raise SystemExit(0)"],
        "mutation_command": mutation_command or [
            sys.executable,
            "-c",
            "raise SystemExit(1)",
        ],
    }


def test_assign_cases_is_reproducible_and_balanced_per_task_class(tmp_path):
    cases = [
        _case(f"unit-{index}", "unit") for index in range(5)
    ] + [
        _case(f"schema-{index}", "schema") for index in range(4)
    ]
    manifest = _manifest(tmp_path, cases)
    loaded = load_manifest(manifest)

    first = assign_cases(loaded, ["model-a", "model-b"], "seed-a")
    second = assign_cases(loaded, ["model-a", "model-b"], "seed-a")

    assert first == second
    for task_class in ("unit", "schema"):
        counts = {
            model: sum(
                assignment.model == model and assignment.case.task_class == task_class
                for assignment in first
            )
            for model in ("model-a", "model-b")
        }
        assert abs(counts["model-a"] - counts["model-b"]) <= 1


def test_manifest_rejects_non_command_and_unknown_task_class(tmp_path):
    manifest = _manifest(tmp_path, [{
        **_case("invalid-case"),
        "task_class": "free-form",
        "test_command": "pytest",
    }])

    with pytest.raises(BenchmarkManifestError, match="task_class inválido"):
        load_manifest(manifest)


def test_benchmark_measures_baseline_and_mutation_without_output(tmp_path):
    manifest = _manifest(tmp_path, [
        _case("detected"),
        _case(
            "missed",
            mutation_command=[sys.executable, "-c", "raise SystemExit(0)"],
        ),
    ])

    report = run_benchmark(
        manifest,
        ["model-a", "model-b"],
        "seed-a",
        execute=True,
    )

    assert report["executed"] is True
    assert report["planned_cases"] == 2
    totals = {
        key: sum(group[key] for group in report["groups"])
        for key in ("baseline_passed", "mutation_detected", "mutation_missed", "timeouts")
    }
    assert totals == {
        "baseline_passed": 2,
        "mutation_detected": 1,
        "mutation_missed": 1,
        "timeouts": 0,
    }
    assert all("case_id" not in group for group in report["groups"])


def test_benchmark_requires_two_distinct_models(tmp_path):
    manifest = _manifest(tmp_path, [_case("one-case")])

    with pytest.raises(BenchmarkManifestError, match="dos modelos distintos"):
        run_benchmark(manifest, ["model-a", "model-a"], "seed-a")
