from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.context import ProjectContext
from orchestrator.egress import EgressBlocked, current_policy


_CLI_CONFIG = {
    "providers": {
        "deepseek": {"model": "deepseek-v4-flash", "clearance": "public"},
        "gemini": {"model": "gemini-2.5-flash", "clearance": "public"},
        "openai": {"model": "gpt-4o", "clearance": "internal"},
        "claude": {"model": "claude-sonnet-4-6", "clearance": "restricted"},
    }
}


@pytest.mark.no_default_policy
def test_cli_run_sets_project_egress_policy():
    runner = CliRunner()
    ctx = ProjectContext(
        name="restricted-project",
        sensitivity="restricted",
        blocked_providers=["deepseek", "gemini"],
    )
    observed = {}

    def assert_active_policy(**kwargs):
        observed["policy"] = current_policy()

    with patch("orchestrator.cli._ensure_db"), \
         patch("orchestrator.cli.load_config", return_value=_CLI_CONFIG), \
         patch("orchestrator.cli.index_module.get_project_path", return_value=Path(".")), \
         patch("orchestrator.cli.context_module.load_context", return_value=ctx), \
         patch("orchestrator.cli._execute_run", side_effect=assert_active_policy):
        result = runner.invoke(
            app,
            ["run", "--task", "revisar seguridad", "--project", "restricted-project"],
        )

    assert result.exit_code == 0, result.output
    policy = observed["policy"]
    assert policy.project == "restricted-project"
    assert policy.sensitivity == "restricted"
    assert policy.blocked_providers == ["deepseek", "gemini"]
    with pytest.raises(EgressBlocked):
        current_policy()


@pytest.mark.no_default_policy
def test_cli_run_resets_project_policy_when_execution_fails():
    runner = CliRunner()
    ctx = ProjectContext(name="project-that-fails", sensitivity="restricted")

    with patch("orchestrator.cli._ensure_db"), \
         patch("orchestrator.cli.load_config", return_value=_CLI_CONFIG), \
         patch("orchestrator.cli.index_module.get_project_path", return_value=Path(".")), \
         patch("orchestrator.cli.context_module.load_context", return_value=ctx), \
         patch("orchestrator.cli._execute_run", side_effect=RuntimeError("boom")):
        result = runner.invoke(
            app,
            ["run", "--task", "fallar", "--project", "project-that-fails"],
        )

    assert result.exit_code != 0
    with pytest.raises(EgressBlocked):
        current_policy()


def test_router_eval_offline_warns_below_two_hundred_runs():
    runner = CliRunner()
    report = {
        "evaluated_runs": 199,
        "skipped_runs": 1,
        "agreement_rate": 0.5,
        "rating_coverage": 0.5,
        "external_router_spend_usd": None,
        "router_cost_observed_runs": 0,
        "router_cost_missing_runs": 199,
    }

    with patch("orchestrator.cli._ensure_db"), \
         patch("orchestrator.cli.load_config", return_value=_CLI_CONFIG), \
         patch("orchestrator.cli.eval_module.offline_router_eval", return_value=report):
        result = runner.invoke(
            app,
            ["router-eval", "--offline", "--project", "demo", "--limit", "199"],
        )

    assert result.exit_code == 0, result.output
    normalized_output = " ".join(result.output.split())
    assert "se requieren al menos 200 runs evaluados" in normalized_output


def test_model_eval_prints_only_aggregated_metrics():
    runner = CliRunner()
    report = {
        "evaluated_runs": 2,
        "rated_runs": 1,
        "rating_coverage": 0.5,
        "groups": [{
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "task_class": "unit",
            "verification_result": "passed",
            "runs": 2,
            "useful_runs": 1,
            "partial_runs": 0,
            "wrong_runs": 0,
            "cost_usd": 0.02,
            "avg_duration_ms": 1200,
        }],
    }

    with patch("orchestrator.cli._ensure_db"), \
         patch(
             "orchestrator.cli.eval_module.local_model_eval",
             return_value=report,
         ) as local_eval:
        result = runner.invoke(app, ["model-eval", "--task-class", "unit"])

    assert result.exit_code == 0, result.output
    local_eval.assert_called_once_with(project=None, task_class="unit")
    assert "Runs evaluados: 2" in result.output


def test_doctor_masks_api_key_prefix(tmp_path):
    runner = CliRunner()
    key = "sk-proj-SECRETPREFIX-0123456789WXYZ"
    config = {"providers": {"openai": {"model": "gpt-4o", "api_key": key}}}

    with patch("orchestrator.cli._ensure_db"), \
         patch("orchestrator.cli.HOME_DIR", tmp_path), \
         patch("orchestrator.cli.load_config", return_value=config):
        result = runner.invoke(app, ["doctor"])

    assert "API key configurada […WXYZ]" in result.output
    assert "sk-proj" not in result.output
    assert "SECRETPREFIX" not in result.output
