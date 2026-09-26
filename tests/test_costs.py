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
