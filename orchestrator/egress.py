"""Política fail-closed para egress con prompt o contexto gobernado."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from orchestrator.context import ProjectContext
from orchestrator.paths import PROVIDERS

SENSITIVITY_RANK = {
    "public": 0,
    "internal": 1,
    "restricted": 2,
    "secret": 3,
}

_REASON_CODES = frozenset({
    "provider_blocked",
    "not_in_allowlist",
    "unknown_clearance",
    "clearance_insufficient",
    "secret_pattern_detected",
    "allowed",
})


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


def _evaluate(policy: EgressPolicy, provider: str) -> tuple[bool, str]:
    if provider in policy.blocked_providers:
        return False, "provider_blocked"
    if policy.allowed_providers and provider not in policy.allowed_providers:
        return False, "not_in_allowlist"

    clearance = policy.provider_clearance.get(provider, "internal")
    if clearance not in SENSITIVITY_RANK:
        return False, "unknown_clearance"
    if SENSITIVITY_RANK[clearance] < SENSITIVITY_RANK[policy.sensitivity]:
        return False, "clearance_insufficient"
    return True, "allowed"


def _can_send(policy: EgressPolicy, provider: str) -> bool:
    return _evaluate(policy, provider)[0]


def can_send(provider: str) -> bool:
    return _can_send(current_policy(), provider)


def log_decision(
    project: str,
    provider: str,
    phase: str,
    decision: str,
    reason_code: str,
    sensitivity: str | None = None,
    clearance: str | None = None,
    run_id: int | None = None,
) -> None:
    if reason_code not in _REASON_CODES:
        raise ValueError(f"reason_code inválido: {reason_code!r}")

    from orchestrator.db import _conn, _write_lock

    conn = _conn()
    with _write_lock:
        conn.execute(
            """INSERT INTO egress_decisions
               (ts, project, provider, phase, decision, reason_code,
                sensitivity, clearance, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                project,
                provider,
                phase,
                decision,
                reason_code,
                sensitivity,
                clearance,
                run_id,
            ),
        )
        conn.commit()


def check(provider: str, phase: str = "provider") -> None:
    policy = current_policy()
    allowed, reason_code = _evaluate(policy, provider)
    log_decision(
        project=policy.project,
        provider=provider,
        phase=phase,
        decision="allowed" if allowed else "blocked",
        reason_code=reason_code,
        sensitivity=policy.sensitivity,
        clearance=policy.provider_clearance.get(provider, "internal"),
    )
    if not allowed:
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
    allowed, reason_code = _evaluate(effective_policy, provider)
    if secret_detected and not allowed:
        reason_code = "secret_pattern_detected"

    log_decision(
        project=policy.project,
        provider=provider,
        phase=phase,
        decision="allowed" if allowed else "blocked",
        reason_code=reason_code,
        sensitivity=effective_policy.sensitivity,
        clearance=effective_policy.provider_clearance.get(provider, "internal"),
    )

    if not allowed:
        if secret_detected:
            raise EgressBlocked("reason_code=secret_pattern_detected")
        raise EgressBlocked(
            f"Provider {provider!r} bloqueado en phase={phase!r} por política de egress."
        )
