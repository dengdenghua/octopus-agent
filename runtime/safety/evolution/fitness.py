from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from runtime.memory.learning.turn_scoring import (
    analyze_soul_impact,
    read_recent_scores,
)

_LOG = logging.getLogger("octopus.evolution.fitness")


def _publish_fitness_event(report: FitnessReport) -> None:
    from runtime.platform.process.eventbus import FitnessComputed, publish_event
    publish_event(FitnessComputed(
        event_type="fitness.computed",
        agent_id=report.agent_id,
        combined_score=report.combined,
        verdict=report.verdict,
        trend=report.l1.trend,
    ), logger=_LOG)


@dataclass
class FitnessConfig:
    window: int = 20
    l1_weight: float = 0.4
    l2_weight: float = 0.6
    l2_model: str | None = None
    l2_max_tokens: int = 600


@dataclass
class L1Fitness:
    score: float
    trend: str
    success_rate: float
    avg_rounds: float
    soul_impact: dict[str, Any]


@dataclass
class L2Fitness:
    score: float
    dominant_failure: str | None
    action: str
    confidence: str
    raw: dict[str, Any] | None


@dataclass
class FitnessReport:
    agent_id: str
    ts: str
    l1: L1Fitness
    l2: L2Fitness | None
    combined: float
    verdict: str


_L2_SYSTEM = """You are a fitness evaluator for an AI agent. Given recent turn
scores and a heuristic pre-analysis, produce a concise fitness judgment.
Output ONLY a JSON envelope.

Schema:
```json
{
  "fitness_score": 0.0-1.0,
  "dominant_failure": "<tag>" | null,
  "action": "evolve" | "revert" | "hold" | "explore",
  "confidence": "low" | "medium" | "high",
  "rationale": "<1-2 sentences>"
}
```"""


def compute_l1(agent_id: str, *, window: int = 20) -> L1Fitness:
    scores = read_recent_scores(agent_id, limit=window)
    if not scores:
        return L1Fitness(
            score=0.5, trend="stable", success_rate=0.0,
            avg_rounds=0.0, soul_impact={},
        )

    success_rate = sum(1 for s in scores if s.score >= 1.0) / len(scores)
    avg_rounds = sum(s.rounds for s in scores) / max(1, len(scores))

    if len(scores) >= 4:
        first_half = scores[: len(scores) // 2]
        second_half = scores[len(scores) // 2 :]
        avg_first = sum(s.score for s in first_half) / len(first_half)
        avg_second = sum(s.score for s in second_half) / len(second_half)
        delta = avg_second - avg_first
        if delta > 0.1:
            trend = "improving"
        elif delta < -0.1:
            trend = "regressing"
        else:
            trend = "stable"
    else:
        trend = "stable"

    raw_score = sum(s.score for s in scores) / len(scores)
    soul_impact = analyze_soul_impact(agent_id, window=window)

    return L1Fitness(
        score=round(raw_score, 3),
        trend=trend,
        success_rate=round(success_rate, 3),
        avg_rounds=round(avg_rounds, 1),
        soul_impact=soul_impact,
    )


def compute_l2(
    agent_id: str,
    l1: L1Fitness,
    *,
    model: str | None = None,
    window: int = 20,
) -> L2Fitness | None:
    from runtime.platform.process.service_provider import get_provider

    router = get_provider().get("evolve_router")
    if router is None:
        _LOG.debug("evolve_router not wired · skip L2 fitness")
        return None

    from runtime.platform.llm_infra.llm_caller import LLMCaller

    caller = LLMCaller("evolve_router", "evolve_default_model")
    scores = read_recent_scores(agent_id, limit=window)

    rows = "\n".join(
        f"  - {s.ts} score={s.score} reason={s.reason} rounds={s.rounds}"
        for s in scores[:15]
    )
    user_msg = (
        f"AGENT: {agent_id}\n"
        f"L1 heuristic: score={l1.score} trend={l1.trend} "
        f"success_rate={l1.success_rate}\n"
        f"Soul impact: {json.dumps(l1.soul_impact, ensure_ascii=False)[:500]}\n\n"
        f"Recent turns:\n{rows}\n\n"
        "Produce your JSON fitness envelope."
    )

    parsed, meta = caller.call_json(
        system=_L2_SYSTEM,
        user=user_msg,
        model=model,
        max_tokens=400,
        temperature=0.2,
    )

    if parsed is None:
        return L2Fitness(
            score=l1.score,
            dominant_failure=None,
            action="hold",
            confidence="low",
            raw=meta,
        )

    return L2Fitness(
        score=float(parsed.get("fitness_score", l1.score)),
        dominant_failure=parsed.get("dominant_failure"),
        action=parsed.get("action", "hold"),
        confidence=parsed.get("confidence", "low"),
        raw=parsed,
    )


def compute_fitness(
    agent_id: str,
    config: FitnessConfig | None = None,
) -> FitnessReport:
    config = config or FitnessConfig()
    l1 = compute_l1(agent_id, window=config.window)
    l2 = compute_l2(agent_id, l1, model=config.l2_model, window=config.window)

    if l2 is not None:
        combined = round(
            l1.score * config.l1_weight + l2.score * config.l2_weight, 3,
        )
    else:
        combined = l1.score

    if combined >= 0.8:
        verdict = "healthy"
    elif combined >= 0.5:
        verdict = "degraded"
    elif combined >= 0.3:
        verdict = "unhealthy"
    else:
        verdict = "critical"

    report = FitnessReport(
        agent_id=agent_id,
        ts=datetime.now().isoformat(timespec="seconds"),
        l1=l1,
        l2=l2,
        combined=combined,
        verdict=verdict,
    )

    _publish_fitness_event(report)

    return report


__all__ = [
    "FitnessConfig",
    "FitnessReport",
    "L1Fitness",
    "L2Fitness",
    "compute_fitness",
    "compute_l1",
    "compute_l2",
]
