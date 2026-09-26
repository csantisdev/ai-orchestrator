from datetime import datetime, timezone

from orchestrator.costs import (
    calculate_cost,
    calculate_cost_with_key,
    is_approximate_price_key,
    resolve_price_key,
)
from orchestrator.db import _conn, _write_lock, run_cost_quality, update_run
from orchestrator.providers.base import CompletionResult

_PRICING = {
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus": {"input": 99.0, "output": 99.0},
    "gpt-5.5": {"input": 1.0, "output": 2.0},
}


def _result(model: str) -> CompletionResult:
    return CompletionResult(
        text="", provider="test", model=model,
        input_tokens=1_000_000, output_tokens=1_000_000,
    )


def test_exact_key_is_not_approximate():
    cost, key = calculate_cost_with_key(_result("gpt-5.5"), _PRICING)

    assert (cost, key) == (3.0, "gpt-5.5")
    assert not is_approximate_price_key("gpt-5.5", key)


def test_provider_prefixed_model_uses_short_key_exactly():
    key = resolve_price_key("openai/gpt-5.5", _PRICING)

    assert key == "gpt-5.5"
    assert not is_approximate_price_key("openai/gpt-5.5", key)


def test_substring_fallback_uses_longest_key_and_is_approximate():
    cost, key = calculate_cost_with_key(_result("claude-opus-5-5"), _PRICING)

    assert key == "claude-opus-5"
    assert cost == 30.0
    assert is_approximate_price_key("claude-opus-5-5", key)


def test_unknown_model_has_no_cost_or_key():
    assert calculate_cost_with_key(_result("mystery-model"), _PRICING) == (None, None)
    assert calculate_cost(_result(""), _PRICING) is None


def _insert_run(model: str, cost_usd, key, tokens: int = 10, provider: str = "codex") -> None:
    conn = _conn()
    with _write_lock:
        conn.execute(
            """INSERT INTO runs (ts, project, provider, model, status, input_tokens, output_tokens,
                                 cost_usd, cost_pricing_key)
               VALUES (?, 'cost-quality', ?, ?, 'done', ?, 0, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), provider, model, tokens, cost_usd, key),
        )
        conn.commit()


def test_run_cost_quality_classifies_runs():
    _insert_run("cq-missing-model", None, None)
    _insert_run("cq-missing-model", None, None)
    _insert_run("cq-opus-5-5", 1.0, "cq-opus-5")
    _insert_run("cq-exact", 1.0, "cq-exact")
    _insert_run("cq-legacy", 1.0, None)
    _insert_run("cq-no-tokens", None, None, tokens=0)
    _insert_run("cq-git-author", None, None, provider="git")

    summary = run_cost_quality()

    assert summary["missing"]["cq-missing-model"] == 2
    assert summary["approximate"]["cq-opus-5-5 → cq-opus-5"] == 1
    assert "cq-no-tokens" not in summary["missing"]
    assert "cq-git-author" not in summary["missing"]
    assert not any(label.startswith("cq-exact") for label in summary["approximate"])
    assert summary["untracked"] >= 1


def test_update_run_stores_cost_pricing_key():
    conn = _conn()
    with _write_lock:
        run_id = conn.execute(
            "INSERT INTO runs (ts, project, status) VALUES (?, 'cost-key', 'pending')",
            (datetime.now(timezone.utc).isoformat(),),
        ).lastrowid
        conn.commit()

    update_run(run_id, _result("claude-opus-5-5"), 10, "test", cost_usd=30.0, cost_pricing_key="claude-opus-5")

    row = conn.execute("SELECT cost_usd, cost_pricing_key FROM runs WHERE id=?", (run_id,)).fetchone()
    assert (row["cost_usd"], row["cost_pricing_key"]) == (30.0, "claude-opus-5")


def _insert_priced_run(model: str, cost_usd, key, project: str) -> int:
    conn = _conn()
    with _write_lock:
        run_id = conn.execute(
            """INSERT INTO runs (ts, project, provider, model, status, input_tokens, output_tokens,
                                 cost_usd, cost_pricing_key)
               VALUES (?, ?, 'codex', ?, 'done', 1000000, 1000000, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), project, model, cost_usd, key),
        ).lastrowid
        conn.commit()
    return run_id


def _cost_row(run_id: int):
    return _conn().execute("SELECT cost_usd, cost_pricing_key FROM runs WHERE id=?", (run_id,)).fetchone()


def test_recompute_plan_and_apply_only_touch_fixable_runs(tmp_path):
    from orchestrator.db import apply_cost_recompute, backup_database, plan_cost_recompute

    pricing = {"rc-model": {"input": 1.0, "output": 2.0}, "rc": {"input": 50.0, "output": 50.0}}
    missing = _insert_priced_run("rc-model", None, None, "rc")
    approximate = _insert_priced_run("rc-model", 100.0, "rc", "rc")
    legacy = _insert_priced_run("rc-model", 7.0, None, "rc")
    exact = _insert_priced_run("rc-model", 3.0, "rc-model", "rc")
    unpriced = _insert_priced_run("rc-unpriced-x", None, None, "rc")

    plan = {item["id"]: item for item in plan_cost_recompute(pricing, model="rc-model")}
    assert set(plan) == {missing, approximate}
    assert plan[missing]["new_cost"] == 3.0 and plan[missing]["reason"] == "missing"
    assert plan[approximate]["new_key"] == "rc-model" and plan[approximate]["reason"] == "approximate"

    unpriced_plan = plan_cost_recompute(pricing, model="rc-unpriced-x")
    assert [(i["id"], i["new_key"]) for i in unpriced_plan] == [(unpriced, None)]

    with_legacy = {item["id"] for item in plan_cost_recompute(pricing, include_untracked=True, model="rc-model")}
    assert with_legacy == {missing, approximate, legacy}

    backup = backup_database(tmp_path / "backups" / "runs.db")
    import sqlite3
    assert sqlite3.connect(backup).execute("SELECT cost_usd FROM runs WHERE id=?", (approximate,)).fetchone() == (100.0,)

    assert apply_cost_recompute(list(plan.values()) + unpriced_plan) == 2
    assert tuple(_cost_row(missing)) == (3.0, "rc-model")
    assert tuple(_cost_row(approximate)) == (3.0, "rc-model")
    assert tuple(_cost_row(legacy)) == (7.0, None)
    assert tuple(_cost_row(exact)) == (3.0, "rc-model")
    assert tuple(_cost_row(unpriced)) == (None, None)
    assert plan_cost_recompute(pricing, model="rc-model") == []


def test_apply_recompute_skips_rows_changed_since_plan():
    from orchestrator.db import apply_cost_recompute, plan_cost_recompute

    pricing = {"rc2-model": {"input": 1.0, "output": 2.0}}
    run_id = _insert_priced_run("rc2-model", None, None, "rc2")
    plan = plan_cost_recompute(pricing, model="rc2-model")
    conn = _conn()
    with _write_lock:
        conn.execute("UPDATE runs SET cost_usd=9.0, cost_pricing_key='rc2-model' WHERE id=?", (run_id,))
        conn.commit()

    assert apply_cost_recompute(plan) == 0
    assert tuple(_cost_row(run_id)) == (9.0, "rc2-model")


def test_pricing_recompute_cli_is_dry_run_by_default(tmp_path, monkeypatch):
    from unittest.mock import patch
    from typer.testing import CliRunner
    import orchestrator.paths as paths_module
    from orchestrator.cli import app

    run_id = _insert_priced_run("rc3-model", None, None, "rc3")
    config = {"pricing": {"rc3-model": {"input": 1.0, "output": 2.0}}}
    runner = CliRunner()
    with patch("orchestrator.cli.load_config", return_value=config):
        dry = runner.invoke(app, ["pricing", "recompute", "--model", "rc3-model"])
        assert dry.exit_code == 0, dry.output
        assert "simulación" in dry.output
        assert tuple(_cost_row(run_id)) == (None, None)

        monkeypatch.setattr(paths_module, "HOME_DIR", tmp_path)
        applied = runner.invoke(app, ["pricing", "recompute", "--model", "rc3-model", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert "1 run(s) actualizados" in applied.output
    assert tuple(_cost_row(run_id)) == (3.0, "rc3-model")
    assert len(list((tmp_path / "backups").glob("runs-*.db"))) == 1
