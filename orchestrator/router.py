"""Router automático: decide qué provider conviene para una tarea dada.

Estrategia en dos capas:
1. Señales locales (keyword_hints del context.yaml) se calculan en Python,
   sin llamar a ningún modelo, y se le pasan como contexto al router.
2. Un modelo router liviano (definido en config.yaml, ej. DeepSeek) recibe
   la tarea + las señales + las reglas en texto libre del proyecto, y
   devuelve el provider elegido + una justificación breve.

Si el router falla (red, parsing, etc.) se cae al fallback_provider de
config.yaml, o al default_provider del context.yaml del proyecto.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace as dc_replace

from orchestrator.config import get_default_provider, get_router_config
from orchestrator.context import ProjectContext
from orchestrator.paths import PROVIDERS
from orchestrator.providers.factory import build_provider

ROUTER_SYSTEM_PROMPT = """Sos un router de tareas de desarrollo de software.
Tu único trabajo es elegir, entre "claude", "openai", "deepseek" o "gemini", cuál es
el motor más adecuado para resolver la tarea dada, considerando el stack
del proyecto, sus convenciones, notas de ruteo y señales de keywords.

Reglas generales de referencia (el proyecto puede sobreescribirlas en sus notas):
- claude: tareas de arquitectura, seguridad, decisiones de diseño, código complejo o ambiguo.
- openai: refactors, integración de APIs, tareas de propósito general.
- deepseek: tareas repetitivas, generación de tests, boilerplate, tareas económicas en volumen.
- gemini: tareas con contexto muy largo (>100K tokens), análisis de repositorios completos, multimodal.

Uso de ratings en tareas similares previas:
- Si una tarea similar está marcada como [ERRÓNEO] para un provider, evitá ese provider a menos que no haya alternativa.
- Si está marcada como [ÚTIL], ese provider es buena señal para esta tarea.

Si se incluye una sección "Perfiles de modelos desde el catálogo", usala como señal
adicional sobre el modelo específico a sugerir (no solo el provider):
- Preferí modelos marcados como fuertes en tags relevantes a la tarea.
- Evitá modelos marcados "[SIN PRECIO]" salvo que no haya alternativa con precio.
- Nunca sugieras un modelo marcado "[DEPRECATED]".
Estas reglas del catálogo tienen prioridad sobre las reglas generales de arriba
cuando ambas aplican al mismo proveedor.

Para "model": si la tarea es simple (boilerplate, completar código corto, formateo) sugerí el modelo más liviano del provider.
Si "model" es null, se usará el configurado en config.yaml. Ejemplos orientativos:
- claude + tarea simple → "claude-haiku-4-5-20251001"
- claude + arquitectura/seguridad → null
- deepseek + cualquier tarea → null
- openai + tarea simple → "gpt-4o-mini"
- gemini + tarea simple → "gemini-2.5-flash"
- gemini + contexto largo/análisis → null

Respondé SOLO con un JSON válido, sin texto adicional, sin markdown, con este formato exacto:
{"provider": "claude|openai|deepseek|gemini", "model": "nombre-modelo-o-null", "reason": "justificación breve en una línea"}
"""


@dataclass
class RoutingDecision:
    provider: str
    reason: str
    model: str | None = None
    used_fallback: bool = False
    router_cost_usd: float | None = None
    system_prompt_addition: str | None = None


def _calculate_keyword_signals(task: str, ctx: ProjectContext) -> list[dict]:
    """Calcula coincidencias de keyword_hints contra el texto de la tarea."""
    task_lower = task.lower()
    signals = []
    for hint in ctx.keyword_hints:
        match = hint.get("match", "")
        if match and match.lower() in task_lower:
            signals.append(
                {
                    "match": match,
                    "provider": hint.get("provider"),
                    "weight": hint.get("weight", 1),
                }
            )
    return signals


def _compress_context(ctx: ProjectContext, task: str, threshold_chars: int = 3200) -> ProjectContext:
    if not ctx.conventions:
        return ctx
    total_chars = len(ctx.stack) + len(ctx.description) + sum(len(c) for c in ctx.conventions)
    if total_chars < threshold_chars:
        return ctx
    task_words = set(task.lower().split())
    relevant = [c for c in ctx.conventions if any(w in c.lower() for w in task_words)]
    if not relevant:
        relevant = ctx.conventions[:3]
    return dc_replace(ctx, conventions=relevant)


def _fetch_active_context(project: str) -> dict | None:
    try:
        from orchestrator.db import _conn
        conn = _conn()
        ctx = conn.execute(
            "SELECT * FROM contexts WHERE project=? AND status='active' ORDER BY ts DESC LIMIT 1",
            (project,),
        ).fetchone()
        if ctx is None:
            return None
        step = conn.execute(
            "SELECT * FROM steps WHERE context_id=? AND status='in_progress' ORDER BY order_idx LIMIT 1",
            (ctx["id"],),
        ).fetchone()
        return {
            "title": ctx["title"],
            "description": ctx["description"],
            "active_step": dict(step) if step else None,
        }
    except Exception:
        return None


def _fetch_similar_runs(task: str, n: int = 3) -> list[dict]:
    try:
        from orchestrator.db import get_run
        from orchestrator.similarity import get_backend
        backend = get_backend()
        hits = backend.query(task, n_results=n)
        results = []
        for hit in hits:
            row = get_run(hit["run_id"])
            if row and row["status"] == "done":
                results.append({
                    "project": row["project"],
                    "provider": row["provider"],
                    "routing_reason": row["routing_reason"],
                    "task_preview": row["task_preview"],
                    "rating": row["rating"] if "rating" in row.keys() else None,
                })
        return results
    except Exception:
        return []


def _format_profiles_section(profiles: list[dict]) -> str:
    """Formatea la vista compacta del catalogo (`get_model_profiles`) para el prompt del router."""
    if not profiles:
        return ""
    lines = []
    for p in profiles:
        purpose = p["purpose"]
        strengths = ", ".join(purpose.get("strengths", [])) or "-"
        weaknesses = ", ".join(purpose.get("weaknesses", [])) or "-"
        flags = []
        if not p["has_price"]:
            flags.append("[SIN PRECIO]")
        if p["status"] == "deprecated":
            flags.append("[DEPRECATED]")
        flag_str = f" {' '.join(flags)}" if flags else ""
        lines.append(
            f"- {p['provider']}/{p['id']}: {purpose.get('summary', '')} "
            f"Fuerte en: {strengths}. Evitar: {weaknesses}.{flag_str}"
        )
    return "\nPerfiles de modelos desde el catálogo:\n" + "\n".join(lines) + "\n"


def _build_router_prompt(
    task: str,
    ctx: ProjectContext,
    signals: list[dict],
    similar_runs: list[dict] | None = None,
    active_context: dict | None = None,
    profiles_section: str = "",
) -> str:
    similar_section = ""
    if similar_runs:
        lines = "\n".join(
            f"- [{r['project']}] → {r['provider']}: \"{r['routing_reason']}\""
            f"{' [ÚTIL]' if r.get('rating') == 'useful' else ''}"
            f"{' [PARCIALMENTE ÚTIL]' if r.get('rating') == 'partial' else ''}"
            f"{' [ERRÓNEO — evitar este provider para esta tarea]' if r.get('rating') == 'wrong' else ''}"
            for r in similar_runs
        )
        similar_section = f"\nDecisiones de ruteo previas en tareas similares:\n{lines}\n"

    context_section = ""
    if active_context:
        step_line = ""
        step = active_context.get("active_step")
        if step:
            step_line = (
                f"\n  Paso activo [{step['order_idx']}]: {step['title']}"
                f"\n  Descripción: {step['description']}"
                f"\n  Proveedor recomendado para este paso: {step['provider'] or '(sin definir)'}"
            )
        context_section = (
            f"\nContexto activo del proyecto:"
            f"\n  Objetivo: {active_context['title']}"
            f"\n  {active_context['description']}"
            f"{step_line}\n"
        )

    return f"""Proyecto: {ctx.name}
Stack: {ctx.stack}
Descripción: {ctx.description}
Convenciones: {", ".join(ctx.conventions) if ctx.conventions else "(sin convenciones registradas)"}
Notas de ruteo del proyecto: {ctx.routing_notes or "(sin notas específicas)"}
Proveedor por defecto del proyecto: {ctx.default_provider or "(sin definir)"}
{context_section}
Señales de keywords detectadas en la tarea: {json.dumps(signals, ensure_ascii=False) if signals else "(ninguna)"}
{similar_section}{profiles_section}
Tarea a resolver:
\"\"\"{task}\"\"\"

¿Qué proveedor debería resolver esta tarea?"""


def _safe_agent_model(agent_def, provider: str | None) -> str | None:
    """Modelo del agente, pero solo si es compatible con el provider final.

    Si el agente define su propio `provider` y este difiere del provider que
    efectivamente se va a usar, el `model` del agente casi seguro pertenece a
    OTRO proveedor (ej. un nombre de modelo Claude aplicado a un provider
    OpenAI) — nunca lo devolvemos en ese caso.
    """
    if not agent_def or not agent_def.model:
        return None
    if agent_def.provider and agent_def.provider != provider:
        return None
    return agent_def.model


def decide_provider(task: str, ctx: ProjectContext, config: dict) -> RoutingDecision:
    """Determina el provider a usar para `task` en el contexto `ctx`."""
    router_cfg = get_router_config(config)
    router_provider_name = router_cfg.get("provider", "deepseek")
    fallback = router_cfg.get("fallback_provider") or ctx.default_provider or get_default_provider(config)

    signals = _calculate_keyword_signals(task, ctx)
    similar = _fetch_similar_runs(task, n=3)
    active_ctx = _fetch_active_context(ctx.name)

    agent_def = None
    if active_ctx and active_ctx.get("active_step"):
        step = active_ctx["active_step"]

        if step.get("agent_preset"):
            try:
                from orchestrator.agents import get_agent
                agent_def = get_agent(step["agent_preset"])
            except Exception:
                agent_def = None

        if step.get("provider") and step["provider"] in PROVIDERS:
            return RoutingDecision(
                provider=step["provider"],
                reason=f"Paso activo [{step['order_idx']}]: {step['title']} → provider definido: {step['provider']}",
                model=_safe_agent_model(agent_def, step["provider"]),
                system_prompt_addition=agent_def.system_prompt_addition if agent_def else None,
            )

        if agent_def and agent_def.provider:
            return RoutingDecision(
                provider=agent_def.provider,
                reason=(
                    f"Paso activo [{step['order_idx']}]: {step['title']} → "
                    f"agente '{agent_def.name}' define provider: {agent_def.provider}"
                ),
                model=_safe_agent_model(agent_def, agent_def.provider),
                system_prompt_addition=agent_def.system_prompt_addition,
            )

    try:
        from orchestrator.catalog import get_model_profiles
        include_deprecated = config.get("catalog", {}).get("allow_deprecated_models", False)
        profiles = get_model_profiles(config, include_deprecated=include_deprecated)
    except Exception:
        profiles = []
    profiles_section = _format_profiles_section(profiles)

    ctx_compressed = _compress_context(ctx, task)
    prompt = _build_router_prompt(
        task, ctx_compressed, signals, similar_runs=similar, active_context=active_ctx,
        profiles_section=profiles_section,
    )

    try:
        router = build_provider(config, router_provider_name)
        result = router.complete(prompt=prompt, system=ROUTER_SYSTEM_PROMPT)

        parsed = json.loads(result.text.strip())
        provider = parsed.get("provider")
        reason = parsed.get("reason", "")
        model = parsed.get("model") or None

        if provider not in PROVIDERS:
            raise ValueError(f"Provider inválido devuelto por el router: {provider}")

        # Validar que el provider elegido tenga API key configurada.
        from orchestrator.config import ConfigError, get_provider_config
        try:
            prov_cfg = get_provider_config(config, provider)
            if not (prov_cfg.get("api_key") or "").strip():
                raise ConfigError(f"Provider '{provider}' no tiene API key configurada.")
        except ConfigError as exc:
            return RoutingDecision(
                provider=fallback,
                reason=f"Router eligió '{provider}' sin API key disponible; se usó fallback '{fallback}'. ({exc})",
                used_fallback=True,
            )

        # Validar el modelo sugerido contra el catálogo (si el router propuso uno).
        if model:
            from orchestrator.catalog import validate_model_for_provider
            validation = validate_model_for_provider(config, provider, model)
            if not validation["valid"] or validation["status"] == "deprecated":
                model = None  # descartar modelo inválido o deprecated; se usará el de config.yaml

        from orchestrator.config import get_pricing_table
        from orchestrator.costs import calculate_cost
        router_cost = calculate_cost(result, get_pricing_table(config))

        return RoutingDecision(
            provider=provider,
            model=_safe_agent_model(agent_def, provider) or model,
            reason=reason, used_fallback=False, router_cost_usd=router_cost,
            system_prompt_addition=agent_def.system_prompt_addition if agent_def else None,
        )

    except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier falla del router
        return RoutingDecision(
            provider=fallback,
            reason=f"Router no disponible ({exc}); se usó fallback '{fallback}'.",
            used_fallback=True,
        )


def force_provider(provider: str) -> RoutingDecision:
    """Para cuando el usuario pasa --model explícitamente, sin consultar al router."""
    if provider not in PROVIDERS:
        raise ValueError(f"Proveedor inválido: '{provider}'. Opciones: {', '.join(PROVIDERS)}")
    return RoutingDecision(provider=provider, reason="Elegido manualmente con --model.", used_fallback=False)
