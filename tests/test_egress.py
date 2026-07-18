import inspect
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import egress
from orchestrator.context import ProjectContext
from orchestrator.egress import (
    EgressBlocked,
    EgressPolicy,
    can_send,
    check,
    current_policy,
    policy_for_project,
    set_policy,
)
from orchestrator.providers.base import BaseProvider, CompletionResult


class StubProvider(BaseProvider):
    name = "stub"

    def _complete(self, prompt: str, system: str = "") -> CompletionResult:
        return CompletionResult(text="unused", provider=self.name, model=self.model)


@pytest.mark.no_default_policy
def test_no_policy_blocks_provider_complete():
    with pytest.raises(EgressBlocked, match="Sin política activa"):
        check("claude")


def test_restricted_project_blocks_public_provider():
    policy = EgressPolicy(
        project="sensitive-project-marker",
        sensitivity="restricted",
        provider_clearance={"deepseek": "public"},
    )
    token = set_policy(policy)
    try:
        assert can_send("deepseek") is False
        with pytest.raises(EgressBlocked) as exc_info:
            check("deepseek", phase="provider")
        message = str(exc_info.value)
        assert "deepseek" in message
        assert "provider" in message
        assert policy.project not in message
    finally:
        egress._POLICY.reset(token)


def test_blocked_provider_overrides_clearance():
    token = set_policy(EgressPolicy(
        project="test",
        sensitivity="restricted",
        blocked_providers=["claude"],
        provider_clearance={"claude": "secret"},
    ))
    try:
        assert can_send("claude") is False
    finally:
        egress._POLICY.reset(token)


def test_allowed_providers_restricts_even_with_clearance():
    token = set_policy(EgressPolicy(
        project="test",
        sensitivity="internal",
        allowed_providers=["openai"],
        provider_clearance={"openai": "internal", "claude": "secret"},
    ))
    try:
        assert can_send("openai") is True
        assert can_send("claude") is False
    finally:
        egress._POLICY.reset(token)


def test_unknown_project_sensitivity_fails_closed():
    with pytest.raises(EgressBlocked, match="sensibilidad desconocido"):
        set_policy(EgressPolicy(project="test", sensitivity="confidencial"))


def test_unknown_provider_clearance_fails_closed():
    token = set_policy(EgressPolicy(
        project="test",
        provider_clearance={"claude": "confidencial"},
    ))
    try:
        assert can_send("claude") is False
        with pytest.raises(EgressBlocked):
            check("claude")
    finally:
        egress._POLICY.reset(token)


def test_policy_reset_restores_previous_policy():
    policy_a = EgressPolicy(project="operation-a", sensitivity="internal")
    policy_b = EgressPolicy(project="operation-b", sensitivity="restricted")

    token_a = set_policy(policy_a)
    try:
        token_b = set_policy(policy_b)
        assert current_policy() is policy_b
        egress._POLICY.reset(token_b)
        assert current_policy() is policy_a
    finally:
        egress._POLICY.reset(token_a)


@pytest.mark.no_default_policy
def test_policy_does_not_leak_between_operations():
    token = set_policy(EgressPolicy(project="operation-a"))
    try:
        assert current_policy().project == "operation-a"
    finally:
        egress._POLICY.reset(token)

    with pytest.raises(EgressBlocked, match="Sin política activa"):
        current_policy()


def test_complete_invokes_check_before__complete():
    provider = StubProvider(api_key="test", model="test-model")
    provider._complete = MagicMock()
    token = set_policy(EgressPolicy(project="test", blocked_providers=["stub"]))
    try:
        with pytest.raises(EgressBlocked):
            provider.complete("prompt")
        provider._complete.assert_not_called()
    finally:
        egress._POLICY.reset(token)


def test_complete_stream_check_is_eager_not_deferred():
    assert inspect.isgeneratorfunction(BaseProvider.complete_stream) is False


def test_streaming_http_not_reached_when_blocked():
    from orchestrator.providers.claude import ClaudeProvider

    provider = ClaudeProvider(api_key="test", model="test-model")
    token = set_policy(EgressPolicy(project="test", blocked_providers=["claude"]))
    try:
        with patch("orchestrator.providers.claude.httpx.stream") as mock_stream:
            with pytest.raises(EgressBlocked):
                provider.complete_stream("prompt")
            mock_stream.assert_not_called()
    finally:
        egress._POLICY.reset(token)


def test_policy_for_restricted_project_uses_provider_clearances():
    ctx = ProjectContext(
        name="restricted-project",
        sensitivity="restricted",
        blocked_providers=["deepseek", "gemini"],
    )
    config = {
        "providers": {
            "deepseek": {"clearance": "public"},
            "gemini": {"clearance": "public"},
            "openai": {"clearance": "internal"},
            "claude": {"clearance": "restricted"},
        }
    }

    policy = policy_for_project(ctx, config)
    token = set_policy(policy)
    try:
        assert can_send("deepseek") is False
        assert can_send("claude") is True
    finally:
        egress._POLICY.reset(token)


def test_secret_in_prompt_escalates_to_secret_and_blocks():
    secret = "AKIAIOSFODNN7EXAMPLE"
    provider = StubProvider(api_key="test", model="test-model")
    provider._complete = MagicMock()
    token = set_policy(EgressPolicy(
        project="test",
        sensitivity="internal",
        provider_clearance={"stub": "restricted"},
    ))
    try:
        with pytest.raises(EgressBlocked, match="secret_pattern_detected"):
            provider.complete(f"Usa esta credencial: {secret}")
        provider._complete.assert_not_called()
    finally:
        egress._POLICY.reset(token)


def test_secret_in_system_escalates_before_streaming():
    secret = "ghp_" + "A" * 36
    provider = StubProvider(api_key="test", model="test-model")
    provider._complete_stream = MagicMock()
    token = set_policy(EgressPolicy(
        project="test",
        sensitivity="internal",
        provider_clearance={"stub": "restricted"},
    ))
    try:
        with pytest.raises(EgressBlocked, match="secret_pattern_detected"):
            provider.complete_stream("prompt", system=f"Token: {secret}")
        provider._complete_stream.assert_not_called()
    finally:
        egress._POLICY.reset(token)


def test_unrecognized_generic_api_key_does_not_escalate():
    provider = StubProvider(api_key="test", model="test-model")
    expected = CompletionResult(text="ok", provider="stub", model="test-model")
    provider._complete = MagicMock(return_value=expected)
    token = set_policy(EgressPolicy(
        project="test",
        sensitivity="internal",
        provider_clearance={"stub": "internal"},
    ))
    try:
        result = provider.complete("API_KEY=ordinary-placeholder-value")
        assert result is expected
        provider._complete.assert_called_once()
    finally:
        egress._POLICY.reset(token)


def test_egress_error_message_never_contains_payload():
    secret = "sk-ant-" + "A" * 24
    provider = StubProvider(api_key="test", model="test-model")
    token = set_policy(EgressPolicy(
        project="test",
        sensitivity="internal",
        provider_clearance={"stub": "restricted"},
    ))
    try:
        with pytest.raises(EgressBlocked) as exc_info:
            provider.complete(f"credential={secret}")
        message = str(exc_info.value)
        assert "secret_pattern_detected" in message
        assert secret not in message
    finally:
        egress._POLICY.reset(token)


def test_secret_escalation_does_not_mutate_active_policy():
    policy = EgressPolicy(
        project="test",
        sensitivity="internal",
        provider_clearance={"stub": "restricted"},
    )
    provider = StubProvider(api_key="test", model="test-model")
    token = set_policy(policy)
    try:
        with pytest.raises(EgressBlocked):
            provider.complete("AKIAIOSFODNN7EXAMPLE")
        assert current_policy() is policy
        assert current_policy().sensitivity == "internal"
    finally:
        egress._POLICY.reset(token)


def _logged_decisions(project: str):
    from orchestrator.db import _conn

    return _conn().execute(
        "SELECT * FROM egress_decisions WHERE project=? ORDER BY id",
        (project,),
    ).fetchall()


def test_egress_log_does_not_store_payload():
    payload = "PAYLOAD_MARKER_MUST_NEVER_BE_STORED"
    provider = StubProvider(api_key="test", model="test-model")
    token = set_policy(EgressPolicy(
        project="payload-log-test",
        provider_clearance={"stub": "internal"},
    ))
    try:
        with patch(
            "orchestrator.egress.log_decision",
            wraps=egress.log_decision,
        ) as mock_log_decision:
            provider.complete(payload, system=f"system {payload}")
    finally:
        egress._POLICY.reset(token)

    rows = _logged_decisions("payload-log-test")
    assert len(rows) == 1
    assert all(payload not in str(value) for value in rows[0])
    assert payload not in repr(mock_log_decision.call_args)


def test_blocked_decision_is_logged():
    token = set_policy(EgressPolicy(
        project="blocked-log-test",
        sensitivity="restricted",
        blocked_providers=["claude"],
        provider_clearance={"claude": "secret", "openai": "internal"},
    ))
    try:
        with pytest.raises(EgressBlocked):
            check("claude")
        with pytest.raises(EgressBlocked):
            check("openai")
    finally:
        egress._POLICY.reset(token)

    rows = _logged_decisions("blocked-log-test")
    assert [(row["decision"], row["reason_code"]) for row in rows] == [
        ("blocked", "provider_blocked"),
        ("blocked", "clearance_insufficient"),
    ]


def test_allowed_decision_is_logged():
    token = set_policy(EgressPolicy(
        project="allowed-log-test",
        sensitivity="internal",
        provider_clearance={"claude": "restricted"},
    ))
    try:
        check("claude", phase="provider")
    finally:
        egress._POLICY.reset(token)

    rows = _logged_decisions("allowed-log-test")
    assert len(rows) == 1
    assert rows[0]["decision"] == "allowed"
    assert rows[0]["reason_code"] == "allowed"
    assert rows[0]["phase"] == "provider"


def test_can_send_does_not_log():
    token = set_policy(EgressPolicy(
        project="pure-query-log-test",
        provider_clearance={"claude": "internal"},
    ))
    try:
        assert can_send("claude") is True
        assert can_send("claude") is True
        assert can_send("openai") is True
    finally:
        egress._POLICY.reset(token)

    assert _logged_decisions("pure-query-log-test") == []


def test_secret_detection_logs_secret_pattern_reason_code():
    provider = StubProvider(api_key="test", model="test-model")
    token = set_policy(EgressPolicy(
        project="secret-log-test",
        sensitivity="internal",
        provider_clearance={"stub": "restricted"},
    ))
    try:
        with pytest.raises(EgressBlocked):
            provider.complete("AKIAIOSFODNN7EXAMPLE")
    finally:
        egress._POLICY.reset(token)

    rows = _logged_decisions("secret-log-test")
    assert len(rows) == 1
    assert rows[0]["decision"] == "blocked"
    assert rows[0]["reason_code"] == "secret_pattern_detected"
    assert rows[0]["sensitivity"] == "secret"
