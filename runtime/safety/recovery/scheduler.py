
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("octopus.regeneration.scheduler")


@dataclass
class SchedulerConfig:

    interval_sec: int = 600
    initial_delay_sec: int = 30
    output_dir: str = "data"
    enabled: bool = True


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except (AttributeError, TypeError, ValueError):  # noqa: BLE001 — model_dump unsupported; try dataclass next
            pass
    if is_dataclass(obj):
        try:
            return asdict(obj)
        except (TypeError, ValueError):  # noqa: BLE001 — dataclass dump fallthrough
            pass
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(x) for x in obj]
    return str(obj)


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Thin shim around ``runtime.platform.io.atomic_write_json``.

    Kept as a private name because several call sites in this module
    pass non-JSON-native values (dataclasses, sets) that we coerce to
    strings via ``default=str``.
    """
    from runtime.platform.io import atomic_write_json
    atomic_write_json(path, payload, default=str)


class RegenerationScheduler:
    _instance: RegenerationScheduler | None = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls) -> RegenerationScheduler:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Stop the worker thread (if running) and drop the singleton.

        For test isolation only — production keeps a single
        RegenerationScheduler alive for the process lifetime.
        """
        with cls._lock:
            inst = cls._instance
            cls._instance = None
        if inst is not None:
            try:  # noqa: SIM105
                inst.stop(timeout=2.0)
            except Exception:  # noqa: BLE001 — reset must never raise
                pass

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stack: Any = None
        self._config = SchedulerConfig()
        self._tick_count = 0
        self._last_summary: dict[str, Any] = {}
        self._lock = threading.RLock()


    def start(
        self,
        stack: Any,
        config: SchedulerConfig | None = None,
    ) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                _LOG.info("regeneration scheduler already running · skip start")
                return
            if stack is None or getattr(stack, "journal", None) is None:
                _LOG.warning(
                    "regeneration scheduler: stack/journal missing · skipping",
                )
                return
            self._stack = stack
            if config is not None:
                self._config = config
            if not self._config.enabled:
                _LOG.info("regeneration scheduler disabled by config · skip")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="regeneration-scheduler",
                daemon=True,
            )
            self._thread.start()
            _LOG.info(
                "🔁 regeneration scheduler started · interval=%ds initial_delay=%ds",
                self._config.interval_sec,
                self._config.initial_delay_sec,
            )

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._stop_event.set()
            t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "tick_count": self._tick_count,
                "last_summary": dict(self._last_summary),
                "interval_sec": self._config.interval_sec,
            }


    def _run_loop(self) -> None:
        if self._stop_event.wait(timeout=self._config.initial_delay_sec):
            return
        while not self._stop_event.is_set():
            try:
                self._tick_once()
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("regeneration tick failed: %s", exc)
            if self._stop_event.wait(timeout=self._config.interval_sec):
                return

    def _tick_once(self) -> None:
        with self._lock:
            self._tick_count += 1
            n = self._tick_count
        summary: dict[str, Any] = {"tick": n, "ts": time.time()}
        out_dir = Path(self._config.output_dir)
        journal = self._stack.journal

        # ─── 1. RuleExtractor ────────────────────
        try:
            from runtime.safety.recovery.rule_extractor import RuleExtractor
            r = RuleExtractor(journal=journal).extract()
            rules_obj = getattr(r, "rules_produced", []) or []
            payload = {
                "tick": n,
                "ts": time.time(),
                "trajectories_scanned": r.trajectories_scanned,
                "failure_count": r.failure_count,
                "clusters_formed": r.clusters_formed,
                "rules": _to_jsonable(rules_obj),
            }
            _atomic_write_json(out_dir / "learned_rules.json", payload)
            summary["rules"] = len(payload["rules"])
            try:
                planner = getattr(self._stack, "planner", None)
                if planner is not None and hasattr(planner, "update_learned_rules"):
                    planner.update_learned_rules(rules_obj)
                    summary["rules_to_planner"] = len(rules_obj)
            except (AttributeError, TypeError) as exc:
                _LOG.warning("inject rules into planner failed: %s", exc)
        except Exception as exc:
            _LOG.warning("RuleExtractor tick failed: %s", exc)
            summary["rules"] = "err"

        # ─── 2. MemoryConsolidator ──────────────
        try:
            from runtime.safety.recovery.memory_consolidator import (
                MemoryConsolidator,
            )
            r = MemoryConsolidator(journal=journal).consolidate()
            mem_obj = (
                getattr(r, "memories", None)
                or getattr(r, "consolidated", None)
                or []
            )
            payload = {
                "tick": n,
                "ts": time.time(),
                "scanned": getattr(r, "events_scanned", None),
                "produced": getattr(r, "memories_produced", None),
                "memories": _to_jsonable(mem_obj),
            }
            _atomic_write_json(out_dir / "learned_memories.json", payload)
            summary["memories"] = (
                len(payload["memories"])
                if isinstance(payload["memories"], list) else 0
            )
            try:
                planner = getattr(self._stack, "planner", None)
                if (
                    planner is not None
                    and hasattr(planner, "update_learned_memories")
                ):
                    planner.update_learned_memories(mem_obj)
                    summary["memories_to_planner"] = (
                        len(mem_obj) if isinstance(mem_obj, list) else 0
                    )
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("inject memories into planner failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("MemoryConsolidator tick failed: %s", exc)
            summary["memories"] = "err"

        try:
            from runtime.safety.recovery.workflow_rewriter import (
                WorkflowRewriter,
            )
            try:
                with open(out_dir / "learned_rules.json", encoding="utf-8") as fh:
                    _rl = json.load(fh).get("rules", []) or []
            except (OSError, json.JSONDecodeError):
                _rl = []
            r = WorkflowRewriter(journal=journal).analyze(rules=_rl)
            payload = {
                "tick": n,
                "ts": time.time(),
                "proposals": _to_jsonable(
                    getattr(r, "proposals", None) or [],
                ),
                "summary": _to_jsonable(
                    {k: v for k, v in vars(r).items() if k != "proposals"}
                    if hasattr(r, "__dict__") else {},
                ),
            }
            _atomic_write_json(out_dir / "workflow_proposals.json", payload)
            summary["proposals"] = (
                len(payload["proposals"])
                if isinstance(payload["proposals"], list) else 0
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("WorkflowRewriter tick failed: %s", exc)
            summary["proposals"] = "err"

        # ─── 4. RecipeEvaluator ─────────────────
        try:
            from runtime.safety.recovery.recipe_evaluator import (
                RecipeEvaluator,
            )
            r = RecipeEvaluator(journal=journal).evaluate()
            payload = {
                "tick": n,
                "ts": time.time(),
                "scores": _to_jsonable(getattr(r, "scores", None) or []),
            }
            _atomic_write_json(out_dir / "recipe_scores.json", payload)
            summary["recipe_scores"] = (
                len(payload["scores"])
                if isinstance(payload["scores"], list) else 0
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("RecipeEvaluator tick failed: %s", exc)
            summary["recipe_scores"] = "err"

        try:
            from runtime.platform import feature_flags as _ff
            from runtime.safety.recovery import forge_auto_tick as _fat
            _fat.bind_stack(self._stack)
            # Source of truth is the feature-flag system (env → legacy_env →
            # file → default); reading os.environ directly ignored runtime
            # flag changes via feature_flags.json. Default stays disabled.
            _apply = _ff.is_on("regeneration.gepa_auto_apply")
            _tr = _fat.run_tick(apply=_apply, journal=journal)
            payload = {
                "tick": n,
                "ts": time.time(),
                "auto_apply": _apply,
                "elapsed_s": _tr.elapsed_s,
                "recipes_scanned": _tr.recipes_scanned,
                "recipes_promoted": _tr.recipes_promoted,
                "results": _tr.results,
            }
            _atomic_write_json(out_dir / "gepa_proposals.json", payload)
            summary["gepa_proposals"] = len(_tr.results or [])
            summary["gepa_promoted"] = _tr.recipes_promoted
        except Exception as exc:
            _LOG.warning("GEPA dry-run tick failed: %s", exc)
            summary["gepa_proposals"] = "err"

        # ─── 6. SkillForge (need registry) ─────────
        try:
            registry = getattr(
                getattr(self._stack, "executor", None), "registry", None,
            )
            if registry is not None:
                from runtime.safety.recovery.skill_forge import SkillForge
                r = SkillForge(journal=journal, registry=registry).run()
                payload = {
                    "tick": n,
                    "ts": time.time(),
                    "candidates": _to_jsonable(
                        getattr(r, "candidates", None) or [],
                    ),
                }
                _atomic_write_json(out_dir / "forged_skills.json", payload)
                summary["forged"] = (
                    len(payload["candidates"])
                    if isinstance(payload["candidates"], list) else 0
                )
            else:
                summary["forged"] = "skip(no_registry)"
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "SkillForge tick failed (%s): %s", type(exc).__name__, exc,
            )
            # Keep the exception type in the summary so recurring patterns
            # (e.g. a duplicate-name crash loop) are visible without grepping
            # logs — a bare "err" hid the type.
            summary["forged"] = f"err:{type(exc).__name__}"

        # ─── 7. TopologyEvolver ─────────────────────
        # Organization-level reflection: read team-topology
        # performance history and emit ``swap_agent`` /
        # ``switch_protocol`` / ``adjust_quality_threshold``
        # proposals to ``topology_proposals.json``. Gated by
        # ``MutationKind.EVOLVE_TOPOLOGY`` inside ``tick()`` so a
        # PANIC freeze halts organization evolution alongside the
        # individual-agent paths above.
        try:
            from runtime.safety.organization.evolver import TopologyEvolver
            from runtime.safety.organization.forge import load_registry

            topology_registry = load_registry()
            evolver = TopologyEvolver(
                proposals_path=out_dir / "topology_proposals.json",
                registry=topology_registry,
            )
            report = evolver.tick()
            summary["topology_proposals"] = len(report.proposals)
            summary["topology_buckets"] = report.buckets_analysed
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("TopologyEvolver tick failed: %s", exc)
            summary["topology_proposals"] = "err"

        # ─── 8. Evolution Fitness ─────────────────
        try:
            from runtime.safety.evolution.fitness import compute_fitness
            agent_id = getattr(
                getattr(self._stack, "config", None), "name", "default",
            )
            report = compute_fitness(agent_id)
            payload = {
                "tick": n,
                "ts": time.time(),
                "agent_id": report.agent_id,
                "l1_score": report.l1.score,
                "l1_trend": report.l1.trend,
                "l2_score": report.l2.score if report.l2 else None,
                "combined": report.combined,
                "verdict": report.verdict,
            }
            _atomic_write_json(out_dir / "evolution_fitness.json", payload)
            summary["evolution_fitness"] = report.verdict
            summary["evolution_combined"] = report.combined
        except Exception as exc:
            _LOG.warning("Evolution fitness tick failed: %s", exc)
            summary["evolution_fitness"] = "err"

        # ─── 9. Drift Monitor ───────────────────
        try:
            from runtime.safety.evolution.drift_monitor import DriftMonitor
            agent_id = getattr(
                getattr(self._stack, "config", None), "name", "default",
            )
            drift_report = DriftMonitor(agent_id).check()
            payload = {
                "tick": n,
                "ts": time.time(),
                "has_drift": drift_report.has_drift,
                "max_severity": drift_report.max_severity,
                "events": [
                    {"kind": e.kind, "severity": e.severity, "detail": e.detail}
                    for e in drift_report.events
                ],
            }
            _atomic_write_json(out_dir / "evolution_drift.json", payload)
            summary["evolution_drift"] = drift_report.max_severity
        except Exception as exc:
            _LOG.warning("Drift monitor tick failed: %s", exc)
            summary["evolution_drift"] = "err"

        # ─── 10. Canary Check ───────────────────
        try:
            from runtime.safety.evolution.canary import CanaryManager
            cm = CanaryManager()
            active = cm.list_active()
            payload = {
                "tick": n,
                "ts": time.time(),
                "active_canaries": len(active),
                "skills": [
                    {"name": s.skill_name, "phase": s.phase.value, "rate": s.current_rate}
                    for s in active
                ],
            }
            _atomic_write_json(out_dir / "evolution_canary.json", payload)
            summary["evolution_canaries"] = len(active)
        except Exception as exc:
            _LOG.warning("Canary check tick failed: %s", exc)
            summary["evolution_canaries"] = "err"

        with self._lock:
            self._last_summary = summary
        _LOG.info(
            "🔁 regeneration tick #%d done · %s",
            n,
            " ".join(f"{k}={v}" for k, v in summary.items() if k not in ("tick", "ts")),
        )


def get_scheduler() -> RegenerationScheduler:
    return RegenerationScheduler.get()
