"""Organization-level evolution.

Where ``camouflage`` evolves a single agent's prompt and ``regeneration``
extracts rules / memories from individual trajectories, **organization**
evolves *how agents work together*: which role runs which agent, what
coordination protocol drives the team, and which team recipe wins on
which task class.

Anthropic's harness-design research (May 2026) showed that a fixed
``planner / generator / evaluator`` three-agent topology produces
qualitatively better long-running output than a single agent. This
module makes that topology a first-class, observable, mutable artifact:

  * ``TeamTopology``  — typed recipe (roles → agents, coordination protocol)
  * ``TeamRunner``    — executor for a topology
  * ``performance_log`` — append-only JSONL recording every run's metrics
  * ``evolver``       — proposes topology mutations from the log
  * ``forge``         — shadow-validates a candidate, promotes it through
                        ``gene_locks.PROMOTE_TOPOLOGY``

Storage layout::

    data/topology_registry.json     — active topology library
    data/topology_proposals.json    — candidate topologies (one tick per write)
    data/topology_performance.jsonl — per-run trace (append-only)
"""

from .topology import (
    AgentSpec,
    CoordinationProtocol,
    Role,
    RoutingRule,
    TeamTopology,
)

__all__ = [
    "AgentSpec",
    "CoordinationProtocol",
    "Role",
    "RoutingRule",
    "TeamTopology",
]
