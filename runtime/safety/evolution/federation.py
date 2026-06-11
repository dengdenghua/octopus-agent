from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("octopus.evolution.federation")

_LOCK = threading.Lock()


@dataclass
class SharedProposal:
    proposal_id: str
    source_agent: str
    kind: str
    description: str
    fitness_delta: float | None
    ts: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FederationConfig:
    shared_dir: str = "data/federation"
    max_proposals_per_agent: int = 50
    adoption_threshold: float = 0.1
    cooldown_sec: int = 300


class FederationHub:
    def __init__(self, config: FederationConfig | None = None) -> None:
        self.config = config or FederationConfig()
        self._dir = Path(self.config.shared_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._last_adopt_ts: dict[str, float] = {}

    def publish(self, agent_id: str, proposal: SharedProposal) -> Path:
        agent_dir = self._dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        path = agent_dir / f"{proposal.proposal_id}.json"
        with _LOCK:
            path.write_text(
                json.dumps(asdict(proposal), ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
        self._trim_agent_dir(agent_dir)
        _LOG.info(
            "federation publish: agent=%s kind=%s id=%s",
            agent_id, proposal.kind, proposal.proposal_id,
        )
        return path

    def discover(
        self,
        agent_id: str,
        *,
        kind: str | None = None,
        min_fitness_delta: float | None = None,
        limit: int = 20,
    ) -> list[SharedProposal]:
        proposals: list[SharedProposal] = []
        for agent_dir in sorted(self._dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            if agent_dir.name == agent_id:
                continue
            for f in sorted(agent_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    p = SharedProposal(
                        proposal_id=d.get("proposal_id", f.stem),
                        source_agent=d.get("source_agent", agent_dir.name),
                        kind=d.get("kind", ""),
                        description=d.get("description", ""),
                        fitness_delta=d.get("fitness_delta"),
                        ts=d.get("ts", ""),
                        metadata=d.get("metadata") or {},
                    )
                    if kind and p.kind != kind:
                        continue
                    if min_fitness_delta is not None:  # noqa: SIM102
                        if p.fitness_delta is None or p.fitness_delta < min_fitness_delta:
                            continue
                    proposals.append(p)
                except Exception as _exc:
                    _LOG.debug("federation proposal parse failed: %s", _exc)
                    continue
                if len(proposals) >= limit:
                    break
            if len(proposals) >= limit:
                break
        return proposals

    def adopt(
        self,
        target_agent: str,
        proposal: SharedProposal,
    ) -> bool:
        import time as _time

        key = f"{target_agent}:{proposal.source_agent}:{proposal.kind}"
        now = _time.time()
        last = self._last_adopt_ts.get(key, 0)
        if now - last < self.config.cooldown_sec:
            _LOG.debug("adopt cooldown: %s", key)
            return False

        if proposal.fitness_delta is not None and proposal.fitness_delta < self.config.adoption_threshold:
            _LOG.debug("adopt rejected: fitness_delta=%.3f < threshold=%.3f",
                       proposal.fitness_delta, self.config.adoption_threshold)
            return False

        adopt_dir = self._dir / target_agent / "adopted"
        adopt_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "adopted_ts": datetime.now().isoformat(timespec="seconds"),
            "source_agent": proposal.source_agent,
            "proposal_id": proposal.proposal_id,
            "kind": proposal.kind,
            "description": proposal.description,
            "fitness_delta": proposal.fitness_delta,
        }
        path = adopt_dir / f"{proposal.proposal_id}.json"
        with _LOCK:
            path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        self._last_adopt_ts[key] = now
        _LOG.info(
            "federation adopt: target=%s source=%s kind=%s",
            target_agent, proposal.source_agent, proposal.kind,
        )
        return True

    def stats(self) -> dict[str, Any]:
        agent_count = 0
        proposal_count = 0
        adopted_count = 0
        for d in self._dir.iterdir():
            if not d.is_dir():
                continue
            agent_count += 1
            proposal_count += len(list(d.glob("*.json")))
            adopted_dir = d / "adopted"
            if adopted_dir.exists():
                adopted_count += len(list(adopted_dir.glob("*.json")))
        return {
            "agents": agent_count,
            "proposals": proposal_count,
            "adopted": adopted_count,
        }

    def _trim_agent_dir(self, agent_dir: Path) -> None:
        files = sorted(agent_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if len(files) > self.config.max_proposals_per_agent:
            for f in files[: len(files) - self.config.max_proposals_per_agent]:
                with contextlib.suppress(OSError):
                    f.unlink()


import contextlib

__all__ = [
    "FederationConfig",
    "FederationHub",
    "SharedProposal",
]
