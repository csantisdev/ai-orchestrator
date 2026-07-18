"""Tests de providers con mock HTTP y secret filter expandido."""
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.providers.base import BaseProvider, CompletionResult


def test_provider_cannot_override_complete():
    with pytest.raises(TypeError, match=r"implement _complete\(\) instead"):
        class InvalidProvider(BaseProvider):
            def complete(self, prompt: str, system: str = "") -> CompletionResult:
                raise NotImplementedError


def test_provider_cannot_override_complete_stream():
    with pytest.raises(TypeError, match=r"implement _complete_stream\(\) instead"):
        class InvalidProvider(BaseProvider):
            def complete_stream(self, prompt: str, system: str = ""):
                raise NotImplementedError


# ── Provider mock tests ─────────────────────────────────────────────────────

def _mock_response(data: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def test_claude_provider_parses_response():
    from orchestrator.providers.claude import ClaudeProvider
    data = {
        "content": [{"type": "text", "text": "respuesta claude"}],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 5,
        },
        "model": "claude-sonnet-4-6",
    }
    with patch("httpx.post", return_value=_mock_response(data)):
        p = ClaudeProvider(api_key="sk-test", model="claude-sonnet-4-6")
        r = p.complete("hola", system="eres un asistente")
    assert r.text == "respuesta claude"
    assert r.provider == "claude"
    assert r.model == "claude-sonnet-4-6"
    assert r.input_tokens == 100
    assert r.output_tokens == 50
    assert r.cache_creation_tokens == 10
    assert r.cache_read_tokens == 5


def test_claude_provider_raises_on_http_error():
    import httpx
    from orchestrator.providers.claude import ClaudeProvider
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock()
    )
    with patch("httpx.post", return_value=mock_resp):
        p = ClaudeProvider(api_key="bad-key", model="claude-sonnet-4-6")
        try:
            p.complete("hola")
            assert False, "should have raised"
        except httpx.HTTPStatusError:
            pass


def test_deepseek_provider_parses_response():
    from orchestrator.providers.deepseek import DeepSeekProvider
    data = {
        "choices": [{"message": {"content": "respuesta deepseek"}}],
        "usage": {"prompt_tokens": 80, "completion_tokens": 40},
        "model": "deepseek-v4-flash",
    }
    with patch("httpx.post", return_value=_mock_response(data)):
        p = DeepSeekProvider(api_key="sk-test", model="deepseek-v4-flash")
        r = p.complete("tarea", system="eres router")
    assert r.text == "respuesta deepseek"
    assert r.provider == "deepseek"
    assert r.input_tokens == 80
    assert r.output_tokens == 40


def test_openai_provider_parses_response():
    from orchestrator.providers.openai import OpenAIProvider
    data = {
        "choices": [{"message": {"content": "respuesta openai"}}],
        "usage": {"prompt_tokens": 60, "completion_tokens": 30},
    }
    with patch("httpx.post", return_value=_mock_response(data)):
        p = OpenAIProvider(api_key="sk-test", model="gpt-4o")
        r = p.complete("test")
    assert r.text == "respuesta openai"
    assert r.provider == "openai"
    assert r.input_tokens == 60
    assert r.output_tokens == 30


def test_provider_sends_system_prompt():
    from orchestrator.providers.deepseek import DeepSeekProvider
    data = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    with patch("httpx.post", return_value=_mock_response(data)) as mock_post:
        p = DeepSeekProvider(api_key="sk-test", model="deepseek-v4-flash")
        p.complete("tarea", system="eres un experto")
    call_kwargs = mock_post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
    messages = body["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "eres un experto"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "tarea"


# ── Secret filter expansion tests ───────────────────────────────────────────

def test_secret_filter_aws():
    from orchestrator.rag import _contains_secrets
    assert _contains_secrets("AKIAIOSFODNN7EXAMPLE")
    assert _contains_secrets("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert not _contains_secrets("no credentials here")


def test_secret_filter_github_pat():
    from orchestrator.rag import _contains_secrets
    assert _contains_secrets("ghp_" + "A" * 36)
    assert _contains_secrets("github_pat_" + "A" * 82)
    assert _contains_secrets("gho_" + "A" * 36)


def test_secret_filter_jwt():
    from orchestrator.rag import _contains_secrets
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36P"
    assert _contains_secrets(jwt)


def test_secret_filter_gcp_service_account():
    from orchestrator.rag import _contains_secrets
    assert _contains_secrets('"type": "service_account"')
    assert not _contains_secrets('"type": "user_account"')


def test_secret_filter_existing_patterns_still_work():
    from orchestrator.rag import _contains_secrets
    assert _contains_secrets("sk-ant-api01-" + "A" * 30)
    assert _contains_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIEo...")
    assert not _contains_secrets("este archivo es seguro sin credenciales")
