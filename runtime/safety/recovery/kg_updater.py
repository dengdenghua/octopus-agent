
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from runtime.adapters.instrumentation import trace_stage
from runtime.memory.journal import Journal, StepEvent, TrajectoryEvent
from runtime.memory.knowledge_graph import AddResult, KnowledgeGraph, Triple
from runtime.platform.models import default_source


class KGUpdateReport(BaseModel):

    model_config = ConfigDict(frozen=True)

    events_scanned: int
    triples_proposed: int
    triples_accepted: int
    triples_superseded: int
    triples_ignored: int


class KGUpdater:

    def __init__(self, journal: Journal, kg: KnowledgeGraph) -> None:
        self.journal = journal
        self.kg = kg


    def update(self) -> KGUpdateReport:
        with trace_stage("regeneration.kg_updater.update"):
            events = self.journal.read_all()

            proposed: list[Triple] = []
            trajectory_buckets: dict[object, list[tuple[int, TrajectoryEvent]]] = {}
            for idx, e in enumerate(events):
                if isinstance(e, StepEvent):
                    proposed.extend(self._triples_from_step(e))
                elif isinstance(e, TrajectoryEvent):
                    trajectory_buckets.setdefault(e.trajectory.task_id, []).append((idx, e))

            for bucket in trajectory_buckets.values():
                swarm_entries = [
                    item for item in bucket if item[1].trajectory.strategy_id == "swarm"
                ]
                if swarm_entries:
                    _idx, event = max(swarm_entries, key=lambda item: item[0])
                    proposed.extend(self._triples_from_trajectory(event))
                else:
                    for _idx, event in bucket:
                        proposed.extend(self._triples_from_trajectory(event))

            accepted = superseded_old = ignored = 0
            for t in proposed:
                r: AddResult = self.kg.add(t)
                if r.verdict == "accepted":
                    accepted += 1
                elif r.verdict == "superseded_old":
                    superseded_old += 1
                    accepted += 1  # Implementation note.
                else:
                    ignored += 1

            return KGUpdateReport(
                events_scanned=len(events),
                triples_proposed=len(proposed),
                triples_accepted=accepted,
                triples_superseded=superseded_old,
                triples_ignored=ignored,
            )


    def _triples_from_step(self, ev: StepEvent) -> list[Triple]:
        step = ev.step
        sucker = step.action.sucker_id
        output = step.result.output

        if not step.success or not isinstance(output, dict):
            return []

        out: list[Triple] = []

        if sucker == "web_search":
            query = output.get("query", "")
            backend = output.get("backend", "unknown")
            if not query:
                return []
            src = default_source(f"web_search:{backend}", "tool")
            for r in output.get("results", []) or []:
                url = r.get("url", "")
                title = r.get("title", "")
                if not url:
                    continue
                out.append(Triple(
                    subject=f"query:{query}",
                    predicate="returned",
                    object=url,
                    confidence=0.70,
                    source=src,
                ))
                if title:
                    out.append(Triple(
                        subject=url,
                        predicate="has_title",
                        object=title[:200],
                        confidence=0.80,
                        source=src,
                    ))

        elif sucker == "fetch_url":
            url = output.get("url", "")
            status = output.get("status_code")
            length = output.get("length")
            if not url:
                return []
            src = default_source(f"fetch_url:{ev.arm_id or 'anon'}", "tool")
            if status is not None:
                out.append(Triple(
                    subject=url,
                    predicate="has_status",
                    object=str(status),
                    confidence=0.95,
                    source=src,
                ))
            if length is not None:
                out.append(Triple(
                    subject=url,
                    predicate="has_size_bytes",
                    object=str(length),
                    confidence=0.90,
                    source=src,
                ))
            ts_iso = step.ts.isoformat()
            out.append(Triple(
                subject=url,
                predicate="fetched_at",
                object=ts_iso,
                confidence=1.0,
                source=src,
            ))

        return out


    def _triples_from_trajectory(self, ev: TrajectoryEvent) -> list[Triple]:
        traj = ev.trajectory
        if not traj.outcome.success:
            return []
        src = default_source(f"trajectory:{traj.trajectory_id}", "trajectory")
        return [
            Triple(
                subject=str(traj.arm_id),
                predicate="completed_strategy",
                object=traj.strategy_id,
                confidence=0.75,
                source=src,
            )
        ]
