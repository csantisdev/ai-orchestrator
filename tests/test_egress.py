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
