"""Política fail-closed para egress con prompt o contexto gobernado."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace

from orchestrator.context import ProjectContext
from orchestrator.paths import PROVIDERS

SENSITIVITY_RANK = {
    "public": 0,
    "internal": 1,
    "restricted": 2,
    "secret": 3,
}


class EgressBlocked(Exception):
    """La política activa no autoriza el egress solicitado."""


@dataclass
class EgressPolicy:
    project: str
    sensitivity: str = "internal"
    allowed_providers: list[str] = field(default_factory=list)
    blocked_providers: list[str] = field(default_factory=list)
    provider_clearance: dict[str, str] = field(default_factory=dict)


_POLICY: ContextVar[EgressPolicy] = ContextVar("egress_policy")


def current_policy() -> EgressPolicy:
    try:
        return _POLICY.get()
    except LookupError as exc:
        raise EgressBlocked("Sin política activa, no sale nada.") from exc


def set_policy(policy: EgressPolicy) -> Token[EgressPolicy]:
    if policy.sensitivity not in SENSITIVITY_RANK:
        raise EgressBlocked(
            f"Nivel de sensibilidad desconocido: {policy.sensitivity!r}"
        )
    return _POLICY.set(policy)


def policy_for_project(ctx: ProjectContext, config: dict) -> EgressPolicy:
    """Construye la política de egress de un proyecto y sus providers."""
    from orchestrator import config as config_module
    from orchestrator.config import ConfigError

    provider_clearance = {}
    for provider in PROVIDERS:
        try:
            provider_config = config_module.get_provider_config(config, provider)
        except ConfigError:
            clearance = "internal"
        else:
            clearance = provider_config.get("clearance", "internal")
        provider_clearance[provider] = clearance

    return EgressPolicy(
        project=ctx.name,
        sensitivity=ctx.sensitivity,
        allowed_providers=ctx.allowed_providers,
        blocked_providers=ctx.blocked_providers,
        provider_clearance=provider_clearance,
    )


def _can_send(policy: EgressPolicy, provider: str) -> bool:
    if provider in policy.blocked_providers:
        return False
    if policy.allowed_providers and provider not in policy.allowed_providers:
        return False

    clearance = policy.provider_clearance.get(provider, "internal")
    if clearance not in SENSITIVITY_RANK:
        return False
    return SENSITIVITY_RANK[clearance] >= SENSITIVITY_RANK[policy.sensitivity]


def can_send(provider: str) -> bool:
    return _can_send(current_policy(), provider)


def check(provider: str, phase: str = "provider") -> None:
    if not can_send(provider):
        raise EgressBlocked(
            f"Provider {provider!r} bloqueado en phase={phase!r} por política de egress."
        )


def check_payload(provider: str, prompt: str, system: str, phase: str) -> None:
    """Evalúa el payload, escalando patrones de secreto sin mutar la policy activa."""
    from orchestrator.rag import _contains_secrets

    policy = current_policy()
    secret_detected = _contains_secrets(prompt) or _contains_secrets(system)
    effective_policy = (
        replace(policy, sensitivity="secret") if secret_detected else policy
    )

    if not _can_send(effective_policy, provider):
        if secret_detected:
            raise EgressBlocked("reason_code=secret_pattern_detected")
        raise EgressBlocked(
            f"Provider {provider!r} bloqueado en phase={phase!r} por política de egress."
        )
