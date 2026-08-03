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
# ``subagent_cheap_model`` service-provider key. ``glm-4-flash`` is
# kept as a sensible fallback so unconfigured deployments still get
# *some* cost reduction instead of falling back to the primary model.
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


def _resolve_cheap_subagent_model() -> str | None:
    """Resolve the model name used for cheap-routed subagent calls.

    Resolution order:
    1. ``OCTOPUS_SUBAGENT_CHEAP_MODEL`` env var (operator override)
    2. ``subagent_cheap_model`` service-provider config key
    3. ``"glm-4-flash"`` (sensible default — operators should override
       to match their org's actual cheap tier)
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
    return _DEFAULT_CHEAP_SUBAGENT_MODEL
