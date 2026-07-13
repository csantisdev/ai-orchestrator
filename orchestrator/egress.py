"""Política fail-closed para egress con prompt o contexto gobernado."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field

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


def can_send(provider: str) -> bool:
    policy = current_policy()
    if provider in policy.blocked_providers:
        return False
    if policy.allowed_providers and provider not in policy.allowed_providers:
        return False

    clearance = policy.provider_clearance.get(provider, "internal")
    if clearance not in SENSITIVITY_RANK:
        return False
    return SENSITIVITY_RANK[clearance] >= SENSITIVITY_RANK[policy.sensitivity]


def check(provider: str, phase: str = "provider") -> None:
    if not can_send(provider):
        raise EgressBlocked(
            f"Provider {provider!r} bloqueado en phase={phase!r} por política de egress."
        )
