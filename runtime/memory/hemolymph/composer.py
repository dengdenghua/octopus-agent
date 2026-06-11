# ruff: noqa: E402 — module-level imports below are intentionally late

from __future__ import annotations

import contextlib
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Any

from runtime.adapters.instrumentation import trace_stage
from runtime.execution.suckers import SkillRegistry
from runtime.memory.journal import Journal, TrajectoryEvent
from runtime.platform.models import (
    DEFAULT_QUOTAS,
    ArmId,
    ContextPacket,
    ContextSegment,
    ParsedIntent,
    QuotaAllocation,
    TaskGraph,
)

# ── Compose telemetry ring buffer ─────────────────────────
# Each ``compose()`` call records a small snapshot here so the
# observability panel can render a live meter of how each bucket
# (system / suckers / memory / history) was filled on the last N
# composes. Deque is bounded · oldest dropped when full · no
# persistence. Locked for thread safety (composes can happen from
# the SSE pump thread + planner thread concurrently).
_RECENT_COMPOSES_MAX: int = 50
_RECENT_COMPOSES: deque[dict[str, Any]] = deque(maxlen=_RECENT_COMPOSES_MAX)
_RECENT_COMPOSES_LOCK = threading.Lock()


def _record_compose_snapshot(
    *,
    budget_tokens: int,
    quotas: QuotaAllocation,
    segments: list[ContextSegment],
    recipe_id: str | None,
    task_type: str | None,
) -> None:
    """Stash a compact view of one ``compose()`` call for the UI."""
    by_bucket: dict[str, int] = {}
    for s in segments:
        by_bucket[s.bucket] = by_bucket.get(s.bucket, 0) + s.tokens_estimated
    total_used = sum(by_bucket.values())
    alloc = quotas.as_tokens(budget_tokens)
    snapshot = {
        "ts": time.time(),
        "budget_tokens": budget_tokens,
        "tokens_used": total_used,
        "utilization": (
            total_used / budget_tokens if budget_tokens > 0 else 0.0
        ),
        "segment_count": len(segments),
        "by_bucket": {
            bucket: {
                "used": by_bucket.get(bucket, 0),
                "alloc": alloc.get(bucket, 0),
            }
            for bucket in ("system", "suckers", "memory", "history")
        },
        "recipe_id": recipe_id,
        "task_type": task_type,
    }
    with _RECENT_COMPOSES_LOCK:
        _RECENT_COMPOSES.append(snapshot)


def get_recent_compose_snapshots(limit: int = 50) -> list[dict[str, Any]]:
    """Return up to ``limit`` most-recent compose snapshots, newest last.

    Observability panel calls this on a heartbeat interval to render
    the per-bucket utilization bars + a sparkline of recent totals.
    """
    with _RECENT_COMPOSES_LOCK:
        if limit >= len(_RECENT_COMPOSES):
            return list(_RECENT_COMPOSES)
        # deque doesn't slice · tail N via islice
        from itertools import islice
        start = len(_RECENT_COMPOSES) - limit
        return list(islice(_RECENT_COMPOSES, start, None))

# Skills that exist for backward-compatible programmatic paths but should not
# be advertised to the planner as ordinary one-step actions.
_HIDDEN_BY_DEFAULT_SKILLS: frozenset[str] = frozenset({
    "call_agent",
})

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 3)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


from runtime.platform.prompts.budget import DEFAULT_BUDGET

_COMPRESS_ORDER: tuple[str, ...] = DEFAULT_BUDGET.compress_order


def _compress_to_budget(
    segments: list[ContextSegment],
    total_budget: int,
) -> list[ContextSegment]:
    total = sum(s.tokens_estimated for s in segments)
    if total <= total_budget:
        return segments

    by_bucket: dict[str, list[ContextSegment]] = {}
    for s in segments:
        by_bucket.setdefault(s.bucket, []).append(s)

    overflow = total - total_budget
    for bucket_name in _COMPRESS_ORDER:
        if overflow <= 0:
            break
        if bucket_name not in by_bucket:
            continue
        bucket_segs = by_bucket[bucket_name]
        while bucket_segs and overflow > 0:
            popped = bucket_segs.pop()
            overflow -= popped.tokens_estimated

    result: list[ContextSegment] = []
    for bucket_name in ("system", "suckers", "memory", "history"):
        result.extend(by_bucket.get(bucket_name, []))
    return result


# ═══════════════════════════════════════════════════════════
# ContextEngine — pluggable compression strategy
# ═══════════════════════════════════════════════════════════


class ContextEngine(ABC):
    """Abstract base for pluggable context-compression strategies.

    The context-engine pattern keeps compression strategies
    interchangeable so the planner can swap them without touching
    call sites: each engine satisfies the same interface, and the
    composer picks one at startup based on the deployment profile.

    Subclasses implement ``compress`` to reduce a list of
    ``ContextSegment`` objects to fit within ``budget_tokens``.
    The default engine (``TruncationContextEngine``) replicates the
    existing bucket-drop behaviour; richer engines can summarise,
    embed-and-retrieve, or apply LLM-based compression.

    Usage::

        class MyEngine(ContextEngine):
            def compress(self, segments, budget_tokens):
                # custom logic
                return segments[:10]

        composer = ContextComposer(registry, engine=MyEngine())
    """

    @abstractmethod
    def compress(
        self,
        segments: list[ContextSegment],
        budget_tokens: int,
    ) -> list[ContextSegment]:
        """Reduce ``segments`` so their total token estimate fits within
        ``budget_tokens``.

        Parameters
        ----------
        segments:
            Ordered list of segments as produced by the composer's
            bucket-fill phase. Segments are ordered
            system → suckers → memory → history.
        budget_tokens:
            Hard ceiling. The returned list's total
            ``tokens_estimated`` SHOULD be ≤ this value.

        Returns
        -------
        list[ContextSegment]
            A (possibly shorter / truncated) list of segments.
        """


class TruncationContextEngine(ContextEngine):
    """Default engine — drops whole segments from the lowest-priority
    buckets first until the total fits within the budget.

    This replicates the original ``_compress_to_budget`` behaviour so
    existing deployments are unaffected when no custom engine is
    supplied.
    """

    def compress(
        self,
        segments: list[ContextSegment],
        budget_tokens: int,
    ) -> list[ContextSegment]:
        return _compress_to_budget(segments, budget_tokens)


# ═══════════════════════════════════════════════════════════
# ContextComposer
# ═══════════════════════════════════════════════════════════


class ContextComposer:

    def __init__(
        self,
        registry: SkillRegistry,
        journal: Journal | None = None,
        quotas: QuotaAllocation = DEFAULT_QUOTAS,
        engine: ContextEngine | None = None,
    ) -> None:
        self.registry = registry
        self.journal = journal
        self.quotas = quotas
        # Pluggable compression strategy. Falls back to the default
        # TruncationContextEngine when none is supplied so existing
        # callers are unaffected.
        self.engine: ContextEngine = engine or TruncationContextEngine()


    def compose(
        self,
        task_info: TaskGraph | ParsedIntent,
        *,
        system_prompt: str = "",
        budget_tokens: int = 20_000,
        relevant_skills: list[str] | None = None,
        arm_id: ArmId | None = None,
        history_cutoff_n: int = 5,
        recipe_id: str | None = None,
        task_type: str | None = None,
    ) -> ContextPacket:
        with trace_stage(
            "hemolymph.compose",
            arm_id=arm_id or "",
        ) as span:
            span.set_attribute("octopus.compose.budget_tokens", budget_tokens)

            segments: list[ContextSegment] = []
            alloc = self.quotas.as_tokens(budget_tokens)

            # ─── system bucket ────────────────────
            if system_prompt:
                segments.append(
                    ContextSegment(
                        bucket="system",
                        content=system_prompt,
                        tokens_estimated=estimate_tokens(system_prompt),
                        source_refs=["system_prompt"],
                    )
                )

            task_blurb = self._render_task(task_info)
            if task_blurb:
                segments.append(
                    ContextSegment(
                        bucket="system",
                        content=task_blurb,
                        tokens_estimated=estimate_tokens(task_blurb),
                        source_refs=["task_info"],
                    )
                )

            # ─── suckers bucket · progressive disclosure ─
            skill_blurb = self._render_skills(relevant_skills, budget_for_bucket=alloc["suckers"])
            if skill_blurb:
                segments.append(
                    ContextSegment(
                        bucket="suckers",
                        content=skill_blurb,
                        tokens_estimated=estimate_tokens(skill_blurb),
                        source_refs=["skill_registry"],
                    )
                )

            # ─── memory bucket ───────────────────
            if self.journal is not None:
                mem_blurbs = self._render_recent_trajectories(
                    n=history_cutoff_n,
                    arm_id=arm_id,
                    budget_for_bucket=alloc["memory"],
                )
                for blurb, refs in mem_blurbs:
                    segments.append(
                        ContextSegment(
                            bucket="memory",
                            content=blurb,
                            tokens_estimated=estimate_tokens(blurb),
                            source_refs=refs,
                        )
                    )


            final_segments = self.engine.compress(segments, budget_tokens)

            span.set_attribute("octopus.compose.segment_count", len(final_segments))
            span.set_attribute(
                "octopus.compose.tokens_used",
                sum(s.tokens_estimated for s in final_segments),
            )

            # Feed the observability panel's ring buffer. Best-effort ·
            # a bad entry here must not break a compose. Try/except to
            # keep the invariant "compose never raises because of UI
            # telemetry."
            with contextlib.suppress(Exception):
                _record_compose_snapshot(
                    budget_tokens=budget_tokens,
                    quotas=self.quotas,
                    segments=final_segments,
                    recipe_id=recipe_id,
                    task_type=task_type,
                )

            return ContextPacket(
                total_budget_tokens=budget_tokens,
                quotas=self.quotas,
                segments=final_segments,
                recipe_id=recipe_id,
                task_type=task_type,
            )


    @staticmethod
    def _render_task(task_info: Any) -> str:
        if isinstance(task_info, ParsedIntent):
            return (
                f"TASK intent={task_info.intent_type} goal={task_info.normalized_goal!r}"
            )
        if isinstance(task_info, TaskGraph):
            steps = " → ".join(
                f"{n.node_id}:{n.skill_ref}" for n in task_info.nodes
            )
            return f"TASK task_type={task_info.task_type} plan=[{steps}]"
        return ""

    def _render_skills(
        self,
        relevant_skills: list[str] | None,
        budget_for_bucket: int,
    ) -> str:
        if relevant_skills is None or "*" in relevant_skills:
            names = [
                n for n in self.registry.all_names()
                if n not in _HIDDEN_BY_DEFAULT_SKILLS
            ]
        else:
            names = [n for n in relevant_skills if self.registry.has(n)]

        if not names:
            return ""

        lines: list[str] = ["AVAILABLE SKILLS (name · one-liner):"]
        used = estimate_tokens(lines[0])

        for name in names:
            skill = self.registry.get(name)
            line = f"  - {name} · {skill.description or '(no description)'}"
            cost = estimate_tokens(line)
            if used + cost > budget_for_bucket:
                lines.append(f"  ... ({len(names) - (len(lines) - 1)} more truncated)")
                break
            lines.append(line)
            used += cost

        return "\n".join(lines)

    def _render_recent_trajectories(
        self,
        *,
        n: int,
        arm_id: ArmId | None,
        budget_for_bucket: int,
    ) -> list[tuple[str, list[str]]]:
        assert self.journal is not None
        events = self.journal.read_by_type("trajectory")
        grouped: dict[object, list[tuple[int, TrajectoryEvent]]] = {}
        for idx, event in enumerate(events):
            if not isinstance(event, TrajectoryEvent):
                continue
            grouped.setdefault(event.trajectory.task_id, []).append((idx, event))

        deduped: list[TrajectoryEvent] = []
        for bucket in grouped.values():
            # Pick the LAST-WRITTEN swarm aggregate · critical for resume /
            # retry paths that reuse ``task_id``. The earlier
            # ``next(...)``-first behavior could surface a stale failed
            # aggregate to the planner instead of the successful one
            # that followed it. We use append index rather than event.ts
            # because in-memory tests and fast retries can share the same
            # timestamp tick.
            swarm_events = [
                item for item in bucket if item[1].trajectory.strategy_id == "swarm"
            ]
            if swarm_events:
                deduped.append(max(swarm_events, key=lambda item: item[0])[1])
            else:
                deduped.extend(event for _, event in bucket)

        recent = [
            e for e in reversed(deduped)
            if isinstance(e, TrajectoryEvent)
            and (arm_id is None or e.trajectory.arm_id == arm_id)
        ][:n]

        blurbs: list[tuple[str, list[str]]] = []
        used = 0
        for e in recent:
            t = e.trajectory
            summary = (
                f"past trajectory: task={t.task_id} arm={t.arm_id} "
                f"steps={t.step_count} "
                f"ok={'yes' if t.outcome.success else 'no'}"
            )
            cost = estimate_tokens(summary)
            if used + cost > budget_for_bucket:
                break
            blurbs.append((summary, [f"trajectory:{t.trajectory_id}"]))
            used += cost
        return blurbs
