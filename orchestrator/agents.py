"""Registro global de agentes — presets reutilizables (Fase 1, modulo de agentes).

Un agente es un preset con nombre: opcionalmente fija provider/model y agrega
texto al system prompt de una tarea. Es una capa de conveniencia sobre el
router existente, NO un ejecutor autonomo — un humano sigue disparando cada
run exactamente como hoy (CLI, dashboard, MCP). Ver `steps.agent_preset` y
`orchestrator/router.py:decide_provider` para el punto de resolucion.

Guardado en ~/.ai-orchestrator/agents.yaml (registro GLOBAL, no por proyecto —
a diferencia de context.yaml que es por-proyecto).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field, fields

import yaml

from orchestrator.paths import AGENTS_PATH, PROVIDERS

_log = logging.getLogger(__name__)
_write_lock = threading.Lock()


@dataclass
class AgentDefinition:
    name: str
    display_name: str = ""
    description: str = ""
    provider: str | None = None
    model: str | None = None
    system_prompt_addition: str = ""
    strengths: list[str] = field(default_factory=list)
    recommended_for: list[str] = field(default_factory=list)
    avoid_for: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_KNOWN_FIELDS = {f.name for f in fields(AgentDefinition)} - {"name"}


def _to_agent(name: str, data: dict) -> AgentDefinition:
    """Ignora claves desconocidas (typos, campos de una version futura del schema)
    en vez de romper la carga de todo el registro por una sola entrada mal escrita."""
    known = {k: v for k, v in (data or {}).items() if k in _KNOWN_FIELDS}
    return AgentDefinition(name=name, **known)


def _load_all() -> dict[str, dict]:
    if not AGENTS_PATH.exists():
        return {}
    try:
        with AGENTS_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        _log.warning("agents: no se pudo leer %s: %s", AGENTS_PATH, exc)
        return {}
    if not isinstance(data, dict):
        _log.warning("agents: %s no tiene la forma esperada (dict), se ignora", AGENTS_PATH)
        return {}
    return data.get("agents", {}) or {}


def _save_all(agents: dict[str, dict]) -> None:
    AGENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AGENTS_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"agents": agents}, f, allow_unicode=True, sort_keys=False)


def list_agents() -> list[AgentDefinition]:
    return [_to_agent(name, data) for name, data in sorted(_load_all().items())]


def get_agent(name: str) -> AgentDefinition | None:
    data = _load_all().get(name)
    if data is None:
        return None
    return _to_agent(name, data)


def upsert_agent(agent: AgentDefinition) -> None:
    if agent.provider is not None and agent.provider not in PROVIDERS:
        raise ValueError(f"provider invalido: '{agent.provider}'. Opciones: {', '.join(PROVIDERS)}")
    with _write_lock:
        agents = _load_all()
        d = agent.to_dict()
        del d["name"]
        agents[agent.name] = d
        _save_all(agents)


def delete_agent(name: str) -> bool:
    with _write_lock:
        agents = _load_all()
        if name not in agents:
            return False
        del agents[name]
        _save_all(agents)
        return True
