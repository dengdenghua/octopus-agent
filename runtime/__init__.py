"""octopus-agent · biomimetic self-evolving agent OS.

Engineering-name package. The package layout uses engineering names for
most subsystems, with a small set of brand terms (cerebrum, hearts, nerves,
arms, swarm, suckers, tentacle) preserved as project vocabulary.

Subpackages are physically organized under 7 semantic groups:
    core/      cerebrum graph_runtime hearts nerves (incl. nerves/reflex)
    execution/ agents arms tool_engine suckers parallel_agents swarm
    sensing/   model_router gateway server normalize
    memory/    journal hemolymph knowledge_graph threads
    safety/    auth budget_breaker validation recovery experiments
               chromatophores invariants
    adapters/  channels integrations mcp_client scheduler instrumentation
    platform/  config models ui i18n

Prefer the explicit group path `from runtime.<group>.X` in new code.
"""

__version__ = "0.2.0"

# ─── re-exports (flat-form import surface) ─────────────────────
from runtime.adapters import (
    channels,
    instrumentation,
    integrations,
    mcp_client,
    scheduler,
)
from runtime.core import cerebrum, graph_runtime, hearts, nerves
from runtime.core.nerves import reflex  # noqa: F401
from runtime.execution import (
    agents,
    arms,
    parallel_agents,
    suckers,
    swarm,
    tool_engine,
)
from runtime.memory import hemolymph, journal, knowledge_graph, threads
from runtime.platform import config, i18n, models, ui  # noqa: F401
from runtime.safety import (
    auth,
    budget_breaker,
    chromatophores,
    experiments,
    invariants,
    recovery,
)
from runtime.sensing import gateway, model_router, normalize, server

__all__ = [
    "__version__",
    # core
    "cerebrum", "graph_runtime", "hearts", "nerves", "reflex",
    # execution
    "agents", "arms", "tool_engine", "suckers", "parallel_agents", "swarm",
    # sensing
    "model_router", "normalize", "gateway", "server",
    # memory
    "journal", "hemolymph", "knowledge_graph", "threads",
    # safety
    "auth", "budget_breaker", "invariants", "recovery",
    "experiments", "chromatophores",
    # adapters
    "channels", "integrations", "mcp_client", "scheduler",
    "instrumentation",
    # platform
    "config", "models", "ui", "i18n",
]
