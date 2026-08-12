"""Sub-agent identity helpers: codename, avatar, and cheap-model resolution.

Extracted from ``bridge.py`` as part of a structural refactor. These are
pure functions / constants with no dependency on bridge module-level state,
so they are safe to import eagerly.
"""

from __future__ import annotations

import os
import random
import uuid

# Permissive default for the cheap subagent model. Operators should
# override this to point at their org's actual cheap model — either
# via the ``OCTOPUS_SUBAGENT_CHEAP_MODEL`` env var or via the
# ``subagent_cheap_model`` service-provider key. When neither is set we
# prefer a self-configured OpenAI-compatible model from
# ``custom_models.json`` (see ``_resolve_cheap_custom_model``) so cheap
# subagents land on a real, working endpoint; ``glm-4-flash`` is the
# last-resort fallback for deployments with no custom models at all.
_DEFAULT_CHEAP_SUBAGENT_MODEL: str = "glm-4-flash"


# ── Sub-agent visualisation: codename + avatar ────────────────
#
# Every spawned sub-agent gets a friendly codename ("Spark / Nova /
# Quark / Atlas / ...") and a role-specific emoji avatar. Both flow
# out as ``subagent_spawned`` lifecycle events so the frontend
# Workbench panel can show a card the moment the agent starts —
# instead of waiting for its first tool call to leak the role string
# through ``sub_tool_*`` events.

_CODENAME_POOL: tuple[str, ...] = (
    "Spark",
    "Nova",
    "Quark",
    "Atlas",
    "Echo",
    "Lyra",
    "Vega",
    "Pixel",
    "Halo",
    "Comet",
    "Drift",
    "Ember",
    "Flux",
    "Glow",
    "Helios",
    "Iris",
    "Juno",
    "Kite",
    "Lumen",
    "Maple",
    "Nimbus",
    "Orbit",
    "Prism",
    "Quest",
    "Rune",
    "Sable",
    "Tide",
    "Umbra",
    "Volt",
    "Whisk",
    "Xeno",
    "Yarrow",
    "Zenith",
    "Aurora",
    "Blaze",
    "Cinder",
    "Dune",
    "Frost",
)

# Role → emoji avatar. Falls back to 🐙 (octopus mascot) for unknown
# roles. Kept short so the UI doesn't have to ship an icon library
# just for sub-agent tiles.
_ROLE_AVATAR: dict[str, str] = {
    "researcher": "🔍",
    "research": "🔍",
    "explorer": "🧭",
    "fact_checker": "✅",
    "fact-checker": "✅",
    "critic": "🛡️",
    "reviewer": "🛡️",
    "security": "🛡️",
    "security-review": "🛡️",
    "performance": "⚡",
    "style": "🎨",
    "synthesizer": "✍️",
    "writer": "✍️",
    "architect": "🏗️",
    "designer": "📐",
    "implementer": "🔧",
    "coder": "🔧",
    "reproducer": "🐛",
    "hypothesizer": "💡",
    "verifier": "🧪",
    "debugger": "🐛",
    "planner": "📋",
    "evaluator": "⚖️",
    "generator": "✨",
}
_DEFAULT_AVATAR = "🐙"


def _codename_for_role(role: str) -> str:
    """Pick a stable-but-friendly codename for a sub-agent.

    Random within the pool so callers can't accidentally rely on a
    specific name; UI uses the codename only as a display label, not
    an identifier. Counter suffix prevents collisions inside one
    parent turn.
    """
    name = random.choice(_CODENAME_POOL)
    suffix = uuid.uuid4().hex[:3]
    return f"{name}-{suffix}"


def _avatar_for_role(role: str) -> str:
    if not isinstance(role, str):
        return _DEFAULT_AVATAR
    key = role.strip().lower()
    return _ROLE_AVATAR.get(key, _DEFAULT_AVATAR)


# URL markers for single-model "Agent Plan" style endpoints. Cheap-routed
# subagents must never be pointed at these (see _is_agent_plan_endpoint).
_AGENT_PLAN_URL_MARKERS: tuple[str, ...] = (
    "/plan/",
    "/api/plan",
    "agent-plan",
)


def _is_agent_plan_endpoint(base_url: str) -> bool:
    """True when ``base_url`` is a single-model "Agent Plan" style endpoint.

    Volcengine's Agent Plan (``ark.cn-beijing.volces.com/api/plan/v3``)
    answers HTTP 404 for any model id outside its allowlist (kimi-k3 /
    ark-code-latest / ...). Routing an arbitrary cheap model id such as
    ``glm-4-flash`` there fails every call, so the cheap-model picker must
    never select these.
    """
    url = (base_url or "").strip().lower()
    return any(marker in url for marker in _AGENT_PLAN_URL_MARKERS)


def _resolve_cheap_custom_model() -> str | None:
    """Pick a cheap-routable model id from ``custom_models.json``, or None.

    Selects the first OpenAI-compatible entry (provider ``openai`` / empty)
    that declares a ``base_url`` and is NOT a single-model Agent-Plan
    endpoint — those 404 for any model id outside their allowlist. The pick
    is deterministic (model ids sorted) so operators and tests get a stable
    choice. Returns ``None`` when no usable entry exists; callers then fall
    back to ``_DEFAULT_CHEAP_SUBAGENT_MODEL``.
    """
    try:
        from runtime.platform.models.custom_model_flags import read_custom_models

        data = read_custom_models()
    except Exception:  # noqa: BLE001 — best-effort, never break dispatch
        return None
    if not isinstance(data, dict):
        return None
    candidates: list[str] = []
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        provider = str(entry.get("provider") or "").lower()
        if provider not in ("openai", ""):
            continue
        base_url = entry.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            continue
        if _is_agent_plan_endpoint(base_url):
            continue
        model_id = str(entry.get("id") or entry.get("name") or "").strip()
        if not model_id:
            raw_models = entry.get("models")
            if isinstance(raw_models, list) and raw_models:
                model_id = str(raw_models[0]).strip()
        if model_id:
            candidates.append(model_id)
    if not candidates:
        return None
    candidates.sort()
    return candidates[0]


def _resolve_cheap_subagent_model() -> str | None:
    """Resolve the model name used for cheap-routed subagent calls.

    Resolution order:
    1. ``OCTOPUS_SUBAGENT_CHEAP_MODEL`` env var (operator override)
    2. ``subagent_cheap_model`` service-provider config key
    3. a self-configured OpenAI-compatible model from ``custom_models.json``
       (so unconfigured deployments route cheap subagents to a real,
       working endpoint — the hard-coded fallback below used to land on a
       single-model Agent-Plan endpoint and 404 every call)
    4. ``"glm-4-flash"`` (last resort when no custom models are declared)
    """
    env_val = os.environ.get("OCTOPUS_SUBAGENT_CHEAP_MODEL")
    if env_val and env_val.strip():
        return env_val.strip()
    try:
        from runtime.platform.process.service_provider import get_provider

        cfg_val = get_provider().get("subagent_cheap_model")
        if isinstance(cfg_val, str) and cfg_val.strip():
            return cfg_val.strip()
    except Exception:  # noqa: BLE001 — config lookup is best-effort
        pass
    custom = _resolve_cheap_custom_model()
    if custom:
        return custom
    return _DEFAULT_CHEAP_SUBAGENT_MODEL
