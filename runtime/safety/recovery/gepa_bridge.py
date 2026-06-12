"""
Bridge between Octopus's existing reflection layer and the
GEPA prompt optimizer.

Why
---

``gepa_optimizer.py`` is generic · it takes an ``eval_fn`` and
optimizes any prompt. This module wires it up to Octopus's
specific data sources:

* Failure samples come from ``RecipeEvaluator``'s losing recipes
  (the trajectories the planner under-performed on)
* Evaluation uses an LLM-as-judge over those goals · much
  cheaper than re-executing each plan against the real arms +
  tools, which would need full sandbox infrastructure
* The winner is persisted as a planner system-prompt section
  via the same ``prompt_persistence`` machinery already used
  for ``learned_rules_section`` and ``learned_memories_section``

Trade-off acknowledged
----------------------

LLM-as-judge introduces self-referential bias · the same model
family that wrote the candidate also scores it. Mitigations:

* Use a DIFFERENT model for judging when possible (e.g.
  candidates from claude-haiku, judged by claude-sonnet)
* Eval set draws from REAL past failures, not synthetic
  scenarios · the judge has to predict whether the new prompt
  would have helped on a goal that genuinely went wrong
* The user always reviews + manually applies the winner ·
  no auto-rollout · so a bad GEPA run can't degrade prod

This is the tier we ship by default. For research-grade GEPA
with replay-based evaluation, swap to ``dspy.GEPA`` (50 MB dep
+ DSPy program shape required).
"""

from __future__ import annotations

# ╔════════════════════════════════════════════════════════════════════════╗
# ║ gepa_bridge.py · navigation map (1263 lines).                          ║
# ║                                                                        ║
# ║ Bridge between Octopus's reflection layer and the GEPA optimizer.      ║
# ║                                                                        ║
# ║   §1 failure collection (journal + ledger)           ~L97              ║
# ║   §2 dataset merging + canary keys                   ~L226             ║
# ║   §3 replay summaries (candidate/sandbox/turn/LLM)   ~L292             ║
# ║   §4 winner sidecar persistence                      ~L388             ║
# ║   §5 recipe scope splitting + winner resolution      ~L407             ║
# ║   §6 mark_winner_proposal_applied                    ~L492             ║
# ║   §7 canary outcome recording                        ~L560             ║
# ║   §8 record_winner_proposal_and_canary (main hook)   ~L588             ║
# ║   §9 eval_fn factory (LLM-as-judge)                  ~L866             ║
# ║   §10 failure sampler factory                        ~L939             ║
# ║   §11 optimize_for_recipe (GEPA entrypoint)          ~L955             ║
# ║   §12 persist_winner + propose_for_losing_recipes    ~L1129            ║
# ╚════════════════════════════════════════════════════════════════════════╝
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from runtime.safety.evolution.canary import CanaryConfig, CanaryManager
from runtime.safety.evolution.proposal_ledger import ProposalLedger
from runtime.safety.recovery.evolution_constraints import (
    EvolutionConstraintValidator,
    serialize_constraint_results,
)
from runtime.safety.recovery.evolution_dataset import (
    EvolutionDataset,
    EvolutionDatasetBuilder,
)
from runtime.safety.recovery.external_importers import (
    build_external_session_dataset,
    collect_external_session_failures,
)
from runtime.safety.recovery.gepa_optimizer import (
    GepaConfig,
    GepaResult,
    gepa_optimize,
)
from runtime.safety.recovery.native_evolution_eval import (
    evaluate_front_native,
    score_candidate_native,
)
from runtime.safety.recovery.native_llm_replay import (
    LLMReplayReport,
    replay_llm_candidates,
)
from runtime.safety.recovery.native_replay import (
    ReplayReport,
    replay_candidates,
)
from runtime.safety.recovery.native_replay_sandbox import (
    SandboxReplayReport,
    run_sandbox_replay,
)
from runtime.safety.recovery.native_turn_replay import (
    TurnReplayReport,
    replay_turn_candidates,
)

_LOG = logging.getLogger("octopus.gepa.bridge")


# ═══════════════════════════════════════════════════════════
# Failure sampling · pulls real losing trajectories from journal
# ═══════════════════════════════════════════════════════════


def collect_failures_from_journal(
    journal: Any, *, recipe_id: str | None = None, limit: int = 10,
) -> list[dict[str, Any]]:
    """Pull failed trajectories · optionally filter by recipe.

    Returns descriptors the LLM mutator can read · keeps each
    entry small (< 400 chars) so the mutation prompt stays
    tractable even with 5 failures bundled in.

    SKIPS empty-goal entries · these slip in from reflex-only
    turns and synthetic test data, and feeding them to the
    LLM-as-judge produces all-zero scores (no goal text means
    nothing to score). Empty-goal failures still WERE failures,
    but they aren't actionable without re-running them with
    the goal preserved · cleaner to skip than to noise the
    optimizer's signal.
    """
    try:
        evs = journal.read_by_type("trajectory")
    except (OSError, TypeError, ValueError, AttributeError):  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    skipped_empty = 0
    for ev in reversed(evs):  # newest first
        outcome = getattr(ev, "outcome", None)
        success = bool(getattr(outcome, "success", False)) if outcome else False
        if success:
            continue
        rid = getattr(ev, "recipe_id", None)
        if recipe_id and rid != recipe_id:
            continue
        # Pull goal text + step count + last error if any.
        goal = (
            getattr(ev, "goal", "")
            or getattr(getattr(ev, "intent", None), "normalized_goal", "")
            or ""
        )[:200]
        # Drop entries with no goal text · the judge can't score them
        # and the mutator can't reason about them (would just see
        # "{}"). These typically come from short-circuit paths
        # (reflex hits, error envelopes) that don't preserve the
        # original prompt. Keep a counter for the caller to surface
        # in admin UI ("we skipped N entries · check what's
        # writing trajectory events without goals").
        if not goal.strip():
            skipped_empty += 1
            continue
        steps = getattr(ev, "steps", None) or []
        last_err = ""
        if steps:
            last_step = steps[-1]
            last_err = str(
                getattr(getattr(last_step, "result", None), "error", "")
                or getattr(last_step, "error", "")
                or ""
            )[:150]
        out.append({
            "goal": goal,
            "step_count": len(steps),
            "last_error": last_err,
            "recipe_id": rid,
        })
        if len(out) >= limit:
            break
    if skipped_empty:
        _LOG.info(
            "gepa: skipped %d empty-goal failure(s) · returned %d usable",
            skipped_empty, len(out),
        )
    return out


def collect_failures_from_ledger(
    *,
    ledger_path: Any = "data/proposal_ledger.jsonl",
    recipe_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Pull realtime failed-turn records from ProposalLedger."""

    try:
        records = ProposalLedger(ledger_path).query(
            kind="turn_failure",
            limit=max(limit * 4, limit),
        )
    except (OSError, TypeError, ValueError, AttributeError):  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    skipped_empty = 0
    for record in reversed(records):
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        rid = metadata.get("recipe_id")
        if recipe_id and isinstance(rid, str) and rid.strip() and rid != recipe_id:
            continue
        goal = str(metadata.get("goal") or "").strip()[:200]
        if not goal:
            skipped_empty += 1
            continue
        item_counts = metadata.get("item_counts")
        step_count = 0
        if isinstance(item_counts, dict):
            for value in item_counts.values():
                try:
                    step_count += int(value or 0)
                except (TypeError, ValueError):
                    continue
        out.append({
            "goal": goal,
            "step_count": step_count,
            "last_error": str(metadata.get("error") or record.description or "")[:150],
            "recipe_id": rid if isinstance(rid, str) else None,
            "source": "proposal_ledger",
            "proposal_id": record.proposal_id,
            "turn_id": metadata.get("turn_id"),
            "thread_id": metadata.get("thread_id"),
            "failure_source": metadata.get("failure_source"),
            "code_change_paths": metadata.get("code_change_paths") or [],
        })
        if len(out) >= limit:
            break
    if skipped_empty:
        _LOG.info(
            "gepa: skipped %d empty-goal ledger failure(s) · returned %d usable",
            skipped_empty, len(out),
        )
    return out


def _merge_failure_samples(
    primary: list[dict[str, Any]],
    supplemental: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_signatures: set[tuple[str, str]] = set()
    for sample in [*primary, *supplemental]:
        goal = str(sample.get("goal") or "").strip()
        if not goal:
            continue
        stable_id = str(sample.get("turn_id") or sample.get("proposal_id") or "").strip()
        error = str(sample.get("last_error") or sample.get("failure_source") or "")[:120]
        signature = (goal, error)
        if stable_id and stable_id in seen_ids:
            continue
        if signature in seen_signatures:
            continue
        if stable_id:
            seen_ids.add(stable_id)
        seen_signatures.add(signature)
        merged.append(sample)
        if len(merged) >= limit:
            break
    return merged


def _merge_positive_datasets(
    primary: EvolutionDataset,
    supplemental: EvolutionDataset,
    *,
    limit: int,
) -> EvolutionDataset:
    examples = []
    seen: set[tuple[str, str]] = set()
    for example in [*primary.all_examples, *supplemental.all_examples]:
        signature = (example.source, example.task_input)
        if signature in seen:
            continue
        seen.add(signature)
        examples.append(example)
        if len(examples) >= max(1, int(limit)):
            break
    return EvolutionDatasetBuilder()._split(examples)


def _safe_canary_part(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:80] or fallback


def _winner_canary_key(
    *,
    recipe_id: str | None,
    candidate_id: str,
) -> str:
    scope = _safe_canary_part(recipe_id, fallback="__global__")
    candidate = _safe_canary_part(candidate_id, fallback="winner")
    return f"prompt_optimizer_{scope}_{candidate}"


def _candidate_replay_summary(
    report: ReplayReport | None,
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    if report is None:
        return None
    for candidate in report.candidates:
        if candidate.candidate_id != candidate_id:
            continue
        return {
            "candidate_id": candidate.candidate_id,
            "total": candidate.total,
            "reasons": candidate.reasons,
            "case_count": len(candidate.case_results),
            "weak_cases": [
                result.to_dict()
                for result in candidate.case_results
                if result.score < 0.55
            ][:5],
        }
    return None


def _candidate_sandbox_replay_summary(
    report: SandboxReplayReport | None,
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    if report is None:
        return None
    for candidate in report.candidates:
        if candidate.candidate_id != candidate_id:
            continue
        return {
            "candidate_id": candidate.candidate_id,
            "total": candidate.total,
            "passed": candidate.passed,
            "case_count": len(candidate.case_results),
            "weak_cases": [
                result.to_dict()
                for result in candidate.case_results
                if result.score < 0.55 or not result.sandbox_passed
            ][:5],
        }
    return None


def _candidate_turn_replay_summary(
    report: TurnReplayReport | None,
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    if report is None:
        return None
    for candidate in report.candidates:
        if candidate.candidate_id != candidate_id:
            continue
        return {
            "candidate_id": candidate.candidate_id,
            "total": candidate.total,
            "passed": candidate.passed,
            "case_count": len(candidate.case_results),
            "weak_cases": [
                result.to_dict()
                for result in candidate.case_results
                if not result.passed
            ][:5],
        }
    return None


def _candidate_llm_replay_summary(
    report: LLMReplayReport | None,
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    if report is None:
        return None
    for candidate in report.candidates:
        if candidate.candidate_id != candidate_id:
            continue
        return {
            "candidate_id": candidate.candidate_id,
            "total": candidate.total,
            "passed": candidate.passed,
            "case_count": len(candidate.case_results),
            "weak_cases": [
                result.to_dict()
                for result in candidate.case_results
                if not result.passed
            ][:5],
        }
    return None


def _winner_sidecar_path(
    *,
    recipe_id: str | None,
    variant_id: str | None = None,
    metadata_root: Any = None,
) -> Path:
    root = Path(metadata_root) if metadata_root is not None else None
    if root is None:
        from runtime.safety.recovery.gepa_addendum_store import _root as _addendum_root

        root = _addendum_root()
    root.mkdir(parents=True, exist_ok=True)
    scope = _safe_canary_part(recipe_id, fallback="__global__")
    if variant_id and variant_id != "__default__":
        variant = _safe_canary_part(variant_id, fallback="variant")
        return root / f"{scope}__{variant}__winner.json"
    return root / f"{scope}__winner.json"


def _split_recipe_scope(recipe_hash: str | None) -> tuple[str | None, str | None]:
    if not recipe_hash:
        return None, None
    if "#" not in recipe_hash:
        return recipe_hash, None
    base, suffix = recipe_hash.split("#", 1)
    return (base or None, suffix or None)


def write_applied_winner_sidecar(
    *,
    recipe_id: str | None,
    candidate_id: str,
    proposal_id: str | None = None,
    canary_key: str | None = None,
    avg_score: float | None = None,
    variant_id: str | None = None,
    metadata_root: Any = None,
) -> dict[str, Any]:
    base_recipe_id, parsed_variant_id = _split_recipe_scope(recipe_id)
    effective_recipe_id = base_recipe_id or recipe_id
    effective_variant_id = variant_id if variant_id is not None else parsed_variant_id
    sidecar = _winner_sidecar_path(
        recipe_id=effective_recipe_id,
        variant_id=effective_variant_id,
        metadata_root=metadata_root,
    )
    payload = {
        "recipe_id": effective_recipe_id,
        "variant_id": effective_variant_id,
        "candidate_id": candidate_id,
        "proposal_id": proposal_id,
        "canary_key": canary_key,
        "avg_score": avg_score,
    }
    try:
        sidecar.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "path": str(sidecar), **payload}
    except (OSError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", **payload}


def resolve_applied_winner_sidecar(
    recipe_hash: str | None,
    *,
    metadata_root: Any = None,
) -> dict[str, Any] | None:
    base_recipe_id, variant_id = _split_recipe_scope(recipe_hash)
    candidates: list[Path] = []
    if variant_id and variant_id != "__default__":
        candidates.append(
            _winner_sidecar_path(
                recipe_id=base_recipe_id,
                variant_id=variant_id,
                metadata_root=metadata_root,
            ),
        )
    if base_recipe_id:
        candidates.append(
            _winner_sidecar_path(
                recipe_id=base_recipe_id,
                metadata_root=metadata_root,
            ),
        )
    candidates.append(
        _winner_sidecar_path(
            recipe_id=None,
            metadata_root=metadata_root,
        ),
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("canary_key"):
            return data
    return None


def mark_winner_proposal_applied(
    *,
    recipe_id: str | None,
    candidate_id: str | None = None,
    variant_id: str | None = None,
    proposal_id: str | None = None,
    canary_key: str | None = None,
    ledger_path: Any = "data/proposal_ledger.jsonl",
    metadata_root: Any = None,
    fitness_after: float | None = None,
) -> dict[str, Any]:
    ledger = ProposalLedger(ledger_path)
    winner: Any | None = None
    target_base, target_variant = _split_recipe_scope(recipe_id)
    if proposal_id:
        for record in ledger.query(kind="prompt_optimizer_winner", limit=500):
            if record.proposal_id == proposal_id:
                winner = record
                break
    if winner is None:
        for record in reversed(ledger.query(kind="prompt_optimizer_winner", limit=500)):
            metadata = record.metadata if isinstance(record.metadata, dict) else {}
            record_base, record_variant = _split_recipe_scope(
                str(metadata.get("recipe_id") or "") or None,
            )
            if target_base is not None and record_base is not None:
                if target_base != record_base:
                    continue
                if target_variant is not None and record_variant is not None and target_variant != record_variant:
                    continue
            elif recipe_id is not None and metadata.get("recipe_id") != recipe_id:
                continue
            if candidate_id is not None and metadata.get("candidate_id") != candidate_id:
                continue
            winner = record
            break
    if winner is None:
        return {"ok": False, "skipped": True, "reason": "winner_proposal_not_found"}

    applied = ledger.mark_applied(winner.proposal_id, fitness_after=fitness_after)
    metadata = applied.metadata if applied is not None and isinstance(applied.metadata, dict) else {}
    resolved_canary_key = canary_key or str(metadata.get("canary_key") or "")
    resolved_candidate_id = str(candidate_id or metadata.get("candidate_id") or "")
    resolved_recipe_id = recipe_id if recipe_id is not None else metadata.get("recipe_id")
    resolved_variant_id = variant_id if variant_id is not None else metadata.get("variant_id")
    sidecar = write_applied_winner_sidecar(
        recipe_id=resolved_recipe_id if isinstance(resolved_recipe_id, str) else None,
        candidate_id=resolved_candidate_id,
        proposal_id=winner.proposal_id,
        canary_key=resolved_canary_key or None,
        avg_score=(
            float(metadata.get("avg_score"))
            if isinstance(metadata.get("avg_score"), (int, float))
            else None
        ),
        variant_id=resolved_variant_id if isinstance(resolved_variant_id, str) else None,
        metadata_root=metadata_root,
    )
    return {
        "ok": True,
        "proposal_id": winner.proposal_id,
        "proposal_status": applied.status.value if applied is not None else winner.status.value,
        "canary_key": resolved_canary_key or None,
        "sidecar": sidecar,
        "candidate_id": resolved_candidate_id,
    }


def record_winner_canary_outcome(
    recipe_hash: str | None,
    *,
    success: bool,
    metadata_root: Any = None,
    canary_config: CanaryConfig | None = None,
) -> dict[str, Any]:
    metadata = resolve_applied_winner_sidecar(recipe_hash, metadata_root=metadata_root)
    if not metadata:
        return {"ok": False, "skipped": True, "reason": "no_applied_winner_sidecar"}
    canary_key = str(metadata.get("canary_key") or "").strip()
    if not canary_key:
        return {"ok": False, "skipped": True, "reason": "missing_canary_key"}
    state = CanaryManager(canary_config).record_outcome(canary_key, success=success)
    if state is None:
        return {"ok": False, "skipped": True, "reason": "canary_not_registered", "canary_key": canary_key}
    return {
        "ok": True,
        "canary_key": canary_key,
        "phase": state.phase.value,
        "sample_count": state.sample_count,
        "success_count": state.success_count,
        "failure_count": state.failure_count,
        "current_rate": state.current_rate,
        "success": success,
    }


def record_winner_proposal_and_canary(
    result: GepaResult,
    *,
    recipe_id: str | None = None,
    trigger: str = "manual",
    ledger_path: Any = "data/proposal_ledger.jsonl",
    canary_config: CanaryConfig | None = None,
    run_ts: float | None = None,
    require_improvement: bool = True,
    min_score_delta: float = 1e-6,
    baseline_prompt: str | None = None,
    failures: list[dict[str, Any]] | None = None,
    positive_dataset: Any | None = None,
    replay_report: ReplayReport | None = None,
    sandbox_replay_report: SandboxReplayReport | None = None,
    turn_replay_report: TurnReplayReport | None = None,
    llm_replay_report: LLMReplayReport | None = None,
    min_replay_score: float = 0.48,
    min_sandbox_replay_score: float = 0.50,
    min_turn_replay_score: float = 0.50,
    min_llm_replay_score: float = 0.50,
) -> dict[str, Any]:
    """Materialize the optimizer winner as an auditable proposal."""
    best = result.best_avg
    if best is None:
        return {"ok": False, "skipped": True, "reason": "no winner"}

    candidate_id = str(best.candidate_id)
    avg_score = float(best.avg_score)
    baseline_candidate_id: str | None = None
    baseline_score: float | None = None
    history = list(result.history or [])
    if history and isinstance(history[0], dict):
        baseline_candidate_id = str(history[0].get("candidate_id") or "") or None
        try:
            baseline_score = float(history[0].get("best_avg"))
        except (TypeError, ValueError):
            baseline_score = None
    is_seed_candidate = int(best.born_at_iter or 0) == 0 and (
        baseline_candidate_id is None or candidate_id == baseline_candidate_id
    )
    if require_improvement and (
        is_seed_candidate
        or (
            baseline_score is not None
            and avg_score <= baseline_score + max(0.0, float(min_score_delta))
        )
    ):
        return {
            "ok": False,
            "skipped": True,
            "reason": "no_improving_winner",
            "candidate_id": candidate_id,
            "avg_score": avg_score,
            "baseline_candidate_id": baseline_candidate_id,
            "baseline_score": baseline_score,
        }
    canary_key = _winner_canary_key(
        recipe_id=recipe_id,
        candidate_id=candidate_id,
    )
    prompt = str(best.prompt or "")
    constraint_results = EvolutionConstraintValidator().validate_prompt(
        prompt,
        baseline_prompt=baseline_prompt,
    )
    if not all(r.passed for r in constraint_results):
        return {
            "ok": False,
            "skipped": True,
            "reason": "constraint_violation",
            "candidate_id": candidate_id,
            "avg_score": avg_score,
            "constraint_results": serialize_constraint_results(constraint_results),
        }
    native_score = score_candidate_native(
        best,
        baseline_prompt=baseline_prompt,
        failures=failures,
        positive_dataset=positive_dataset,
    )
    if native_score.verdict == "reject":
        return {
            "ok": False,
            "skipped": True,
            "reason": "native_score_rejected",
            "candidate_id": candidate_id,
            "avg_score": avg_score,
            "native_score": native_score.to_dict(),
        }
    replay_summary = _candidate_replay_summary(
        replay_report,
        candidate_id=candidate_id,
    )
    if (
        replay_summary is not None
        and float(replay_summary.get("total") or 0.0) < max(0.0, min_replay_score)
    ):
        return {
            "ok": False,
            "skipped": True,
            "reason": "native_replay_rejected",
            "candidate_id": candidate_id,
            "avg_score": avg_score,
            "native_score": native_score.to_dict(),
            "native_replay": replay_summary,
        }
    sandbox_replay_summary = _candidate_sandbox_replay_summary(
        sandbox_replay_report,
        candidate_id=candidate_id,
    )
    if (
        sandbox_replay_summary is not None
        and float(sandbox_replay_summary.get("total") or 0.0)
        < max(0.0, min_sandbox_replay_score)
    ):
        return {
            "ok": False,
            "skipped": True,
            "reason": "native_sandbox_replay_rejected",
            "candidate_id": candidate_id,
            "avg_score": avg_score,
            "native_score": native_score.to_dict(),
            "native_replay": replay_summary,
            "native_sandbox_replay": sandbox_replay_summary,
        }
    turn_replay_summary = _candidate_turn_replay_summary(
        turn_replay_report,
        candidate_id=candidate_id,
    )
    if (
        turn_replay_summary is not None
        and float(turn_replay_summary.get("total") or 0.0)
        < max(0.0, min_turn_replay_score)
    ):
        return {
            "ok": False,
            "skipped": True,
            "reason": "native_turn_replay_rejected",
            "candidate_id": candidate_id,
            "avg_score": avg_score,
            "native_score": native_score.to_dict(),
            "native_replay": replay_summary,
            "native_sandbox_replay": sandbox_replay_summary,
            "native_turn_replay": turn_replay_summary,
        }
    llm_replay_summary = _candidate_llm_replay_summary(
        llm_replay_report,
        candidate_id=candidate_id,
    )
    if (
        llm_replay_summary is not None
        and float(llm_replay_summary.get("total") or 0.0)
        < max(0.0, min_llm_replay_score)
    ):
        return {
            "ok": False,
            "skipped": True,
            "reason": "native_llm_replay_rejected",
            "candidate_id": candidate_id,
            "avg_score": avg_score,
            "native_score": native_score.to_dict(),
            "native_replay": replay_summary,
            "native_sandbox_replay": sandbox_replay_summary,
            "native_turn_replay": turn_replay_summary,
            "native_llm_replay": llm_replay_summary,
        }
    metadata = {
        "recipe_id": recipe_id,
        "trigger": trigger,
        "candidate_id": candidate_id,
        "avg_score": avg_score,
        "baseline_candidate_id": baseline_candidate_id,
        "baseline_score": baseline_score,
        "born_at_iter": int(best.born_at_iter or 0),
        "parent_id": best.parent_id,
        "rationale": str(best.rationale or "")[:500],
        "prompt_preview": prompt[:400],
        "prompt_length": len(prompt),
        "constraint_results": serialize_constraint_results(constraint_results),
        "native_score": native_score.to_dict(),
        "native_replay": replay_summary,
        "native_sandbox_replay": sandbox_replay_summary,
        "native_turn_replay": turn_replay_summary,
        "native_llm_replay": llm_replay_summary,
        "iterations_run": int(result.iterations_run or 0),
        "front_size": len(result.final_front or []),
        "run_ts": run_ts,
        "canary_key": canary_key,
    }
    ledger = ProposalLedger(ledger_path)
    for existing in reversed(ledger.query(kind="prompt_optimizer_winner", limit=200)):
        existing_metadata = existing.metadata if isinstance(existing.metadata, dict) else {}
        if (
            existing_metadata.get("recipe_id") == recipe_id
            and existing_metadata.get("candidate_id") == candidate_id
        ):
            state = CanaryManager(canary_config).register(
                canary_key,
                metadata={
                    "proposal_id": existing.proposal_id,
                    "proposal_kind": existing.kind,
                    "recipe_id": recipe_id,
                    "candidate_id": candidate_id,
                    "avg_score": avg_score,
                    "trigger": trigger,
                    "run_ts": run_ts,
                },
            )
            return {
                "ok": True,
                "skipped": True,
                "reason": "duplicate_winner",
                "proposal_id": existing.proposal_id,
                "proposal_kind": existing.kind,
                "proposal_status": existing.status.value,
                "canary_key": canary_key,
                "canary_phase": state.phase.value,
                "candidate_id": candidate_id,
                "avg_score": avg_score,
            }
    scope = recipe_id or "__global__"
    proposal = ledger.propose(
        kind="prompt_optimizer_winner",
        description=(
            f"Prompt optimizer winner {candidate_id} for {scope} "
            f"avg_score={avg_score:.3f}"
        ),
        proposer="gepa_bridge",
        metadata=metadata,
    )
    canary_metadata = {
        "proposal_id": proposal.proposal_id,
        "proposal_kind": proposal.kind,
        "recipe_id": recipe_id,
        "candidate_id": candidate_id,
        "avg_score": avg_score,
        "trigger": trigger,
        "run_ts": run_ts,
    }
    state = CanaryManager(canary_config).register(
        canary_key,
        metadata=canary_metadata,
    )
    return {
        "ok": True,
        "proposal_id": proposal.proposal_id,
        "proposal_kind": proposal.kind,
        "proposal_status": proposal.status.value,
        "canary_key": canary_key,
        "canary_phase": state.phase.value,
        "candidate_id": candidate_id,
        "avg_score": avg_score,
    }


# ═══════════════════════════════════════════════════════════
# Eval · LLM-as-judge over real goals
# ═══════════════════════════════════════════════════════════


_JUDGE_SYSTEM = """\
You are scoring a candidate planner system-prompt against a
batch of real user goals. For each goal, predict whether a
planner using the candidate prompt would produce a good plan.

Score each goal 0.0 to 1.0:
  1.0 = clearly handled, planner picks the right tools cleanly
  0.7 = mostly handled, may need 1 retry
  0.4 = partial · misses a step or picks suboptimal tool
  0.0 = fails outright (wrong tool, infinite loop, refuses)

Output STRICT JSON:
  {"scores": [0.7, 0.4, ...]}   # one float per input goal, in order

No commentary. No markdown fences. Just the JSON."""


def _make_eval_fn(
    sample_goals: list[str],
    *,
    router: Any,
    judge_model: str,
) -> Any:
    """Curry a goal list into an eval_fn the optimizer can call.

    The optimizer calls eval_fn(prompt, n) and gets back a
    list of n scores. We just judge the first n goals in
    sample_goals · keeps the eval set FIXED across iterations
    so candidate scores are comparable.
    """
    from runtime.platform.models.llm import Message, ModelRequest

    def _eval(prompt: str, n: int) -> list[float]:
        goals = sample_goals[:n]
        if not goals:
            return []
        user_msg = (
            "# CANDIDATE PROMPT\n" + prompt + "\n\n"
            "# GOALS TO SCORE\n"
            + json.dumps(goals, ensure_ascii=False, indent=2)
            + "\n\nReturn the scores JSON."
        )
        req = ModelRequest(
            model=judge_model,
            messages=[
                Message(role="system", content=_JUDGE_SYSTEM),
                Message(role="user", content=user_msg),
            ],
            max_tokens=512,
            temperature=0.1,  # judge should be near-deterministic
        )
        try:
            resp = router.call(req)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("gepa eval: judge call failed · %s", exc)
            return [0.0] * len(goals)
        text = (getattr(resp, "text", "") or "").strip()
        # Tolerate fences.
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                lines[1:-1] if lines[-1].startswith("```") else lines[1:],
            )
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            s, e = text.find("{"), text.rfind("}")
            if s < 0 or e <= s:
                return [0.0] * len(goals)
            try:
                obj = json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                return [0.0] * len(goals)
        scores = obj.get("scores") if isinstance(obj, dict) else None
        if not isinstance(scores, list):
            return [0.0] * len(goals)
        # Coerce + pad/truncate to expected length.
        out: list[float] = []
        for s_val in scores[:len(goals)]:
            try:
                out.append(max(0.0, min(1.0, float(s_val))))
            except (TypeError, ValueError):
                out.append(0.0)
        while len(out) < len(goals):
            out.append(0.0)
        return out

    return _eval


def _make_failure_sampler(
    failures: list[dict[str, Any]],
) -> Any:
    """Static failure sampler · returns the same failures list
    on every call (deterministic mutator input). The optimizer
    asks for ``n`` and we return at most ``n``."""
    def _sample(_prompt: str, n: int) -> list[dict[str, Any]]:
        return failures[:n]
    return _sample


# ═══════════════════════════════════════════════════════════
# Public · "run GEPA on this losing recipe"
# ═══════════════════════════════════════════════════════════


def optimize_for_recipe(
    *,
    seed_prompt: str,
    journal: Any,
    router: Any,
    recipe_id: str | None = None,
    judge_model: str = "claude-sonnet-4-6",
    mutator_model: str = "claude-sonnet-4-6",
    n_iter: int = 10,
    eval_tasks: int = 5,
    ledger_path: Any = "data/proposal_ledger.jsonl",
    trigger: str = "manual",
    record_winner: bool = True,
) -> GepaResult:
    """End-to-end · pulls failures, builds eval_fn, runs gepa.

    Caller (RecipeEvaluator wiring or admin endpoint) supplies
    the seed_prompt (typically the planner's CURRENT system
    prompt) · we figure out the rest from the journal. Returns
    a ``GepaResult`` so the operator can inspect candidates
    before deciding to apply.
    """
    journal_failures = collect_failures_from_journal(
        journal, recipe_id=recipe_id, limit=eval_tasks * 2,
    )
    ledger_failures = collect_failures_from_ledger(
        ledger_path=ledger_path,
        recipe_id=recipe_id,
        limit=eval_tasks * 2,
    )
    external_failures = collect_external_session_failures(limit=eval_tasks * 2)
    failures = _merge_failure_samples(
        _merge_failure_samples(
            journal_failures,
            ledger_failures,
            limit=eval_tasks * 3,
        ),
        external_failures,
        limit=eval_tasks * 2,
    )
    dataset_builder = EvolutionDatasetBuilder()
    clustered_failures = dataset_builder.annotate_failure_clusters(failures)
    normalized_dataset = dataset_builder.build_from_failure_samples(
        clustered_failures,
        source_name="merged_failure",
        include_synthetic=False,
    )
    failures = [
        {
            "goal": ex.task_input,
            "step_count": int(ex.metadata.get("step_count") or 0),
            "last_error": str(ex.metadata.get("last_error") or ""),
            "recipe_id": ex.metadata.get("recipe_id"),
            "source": ex.source,
            "failure_source": ex.metadata.get("failure_source"),
            "failure_cluster": ex.metadata.get("failure_cluster"),
            "failure_cluster_count": int(ex.metadata.get("failure_cluster_count") or 1),
            "proposal_id": ex.metadata.get("proposal_id"),
            "turn_id": ex.metadata.get("turn_id"),
            "thread_id": ex.metadata.get("thread_id"),
            "code_change_paths": ex.metadata.get("code_change_paths") or [],
        }
        for ex in normalized_dataset.all_examples
    ]
    if len(failures) < 2:
        # Not enough signal · don't burn LLM budget. Caller can
        # check ``iterations_run == 0`` to detect this case.
        # Surface a clear actionable hint so the operator knows
        # whether to run the system longer (no failures) or fix
        # the goal-recording path (only empty goals).
        result = GepaResult(
            iterations_run=0, final_front=[], best_avg=None,
            history=[{
                "skipped": True,
                "reason": (
                    f"only {len(failures)} usable failures available "
                    "(need ≥2). Either run longer to accumulate real "
                    "failures, or check the trajectory/turn-failure ledger."
                ),
                "journal_failures": len(journal_failures),
                "ledger_failures": len(ledger_failures),
                "external_failures": len(external_failures),
            }],
            elapsed_s=0.0,
        )
        if record_winner:
            result.winner_proposal = {"ok": False, "skipped": True, "reason": "insufficient_failure_signal"}
        return result
    goals = [f["goal"] for f in failures if f.get("goal")]
    eval_fn = _make_eval_fn(goals, router=router, judge_model=judge_model)
    failure_sampler = _make_failure_sampler(failures)
    result = gepa_optimize(
        seed_prompt=seed_prompt,
        eval_fn=eval_fn,
        failure_sampler=failure_sampler,
        router=router,
        model=mutator_model,
        config=GepaConfig(n_iter=n_iter, eval_tasks=eval_tasks),
    )
    positive_dataset = dataset_builder.build_positive_examples(
        journal=journal,
        ledger_path=ledger_path,
        recipe_id=recipe_id,
        limit=eval_tasks * 2,
    )
    positive_dataset = _merge_positive_datasets(
        positive_dataset,
        build_external_session_dataset(limit=eval_tasks * 2),
        limit=eval_tasks * 3,
    )
    native_evaluation = evaluate_front_native(
        list(result.final_front or []),
        baseline_prompt=seed_prompt,
        failures=failures,
        positive_dataset=positive_dataset,
    )
    result.native_evaluation = [score.to_dict() for score in native_evaluation]
    replay_report = replay_candidates(
        list(result.final_front or []),
        baseline_prompt=seed_prompt,
        failures=failures,
        positive_dataset=positive_dataset,
    )
    result.native_replay = replay_report.to_dict()
    sandbox_replay_report = run_sandbox_replay(
        list(result.final_front or []),
        failures=failures,
        positive_dataset=positive_dataset,
        baseline_prompt=seed_prompt,
    )
    result.native_sandbox_replay = sandbox_replay_report.to_dict()
    turn_replay_report = replay_turn_candidates(
        list(result.final_front or []),
        failures=failures,
    )
    result.native_turn_replay = turn_replay_report.to_dict()
    llm_replay_report = None
    if os.environ.get("OCTOPUS_EVOLUTION_LLM_REPLAY", "").strip().lower() in {"1", "true", "yes", "on"}:
        llm_replay_report = replay_llm_candidates(
            list(result.final_front or []),
            router=router,
            model=judge_model,
            failures=failures,
        )
        result.native_llm_replay = llm_replay_report.to_dict()
    if record_winner:
        try:
            lifecycle = record_winner_proposal_and_canary(
                result,
                recipe_id=recipe_id,
                trigger=trigger,
                ledger_path=ledger_path,
                baseline_prompt=seed_prompt,
                failures=failures,
                positive_dataset=positive_dataset,
                replay_report=replay_report,
                sandbox_replay_report=sandbox_replay_report,
                turn_replay_report=turn_replay_report,
                llm_replay_report=llm_replay_report,
            )
        except Exception as exc:  # noqa: BLE001
            lifecycle = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        result.winner_proposal = lifecycle
    return result


# ═══════════════════════════════════════════════════════════
# Persistence · winner becomes a planner prompt section
# ═══════════════════════════════════════════════════════════


def persist_winner(
    result: GepaResult,
    *,
    section_path: Any,  # str | Path
) -> dict[str, Any]:
    """Write the best candidate's prompt to ``section_path`` ·
    LLMPlanner picks it up via ``load_section`` on next instance.

    Returns a small dict with what was written so the admin UI
    can show ``"applied vN, score=0.78"``.
    """
    if not result.best_avg:
        return {"ok": False, "error": "no winner to persist"}
    try:
        from runtime.core.cerebrum.prompt_persistence import dump_section
        section = (
            "## GEPA-optimized addendum\n\n"
            f"<!-- candidate {result.best_avg.candidate_id} · "
            f"avg_score {result.best_avg.avg_score:.3f} · "
            f"iter {result.best_avg.born_at_iter} · "
            f"rationale: {result.best_avg.rationale} -->\n\n"
            + result.best_avg.prompt
        )
        dump_section(section_path, section, label="gepa")
        return {
            "ok": True,
            "candidate_id": result.best_avg.candidate_id,
            "avg_score": result.best_avg.avg_score,
            "iter": result.best_avg.born_at_iter,
            "rationale": result.best_avg.rationale,
        }
    except (OSError, ValueError, TypeError, AttributeError, ImportError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ═══════════════════════════════════════════════════════════
# Auto-propose · run GEPA on every losing recipe in one batch
# ═══════════════════════════════════════════════════════════


def propose_for_losing_recipes(
    *,
    journal: Any,
    router: Any,
    seed_prompt: str,
    judge_model: str = "claude-sonnet-4-6",
    mutator_model: str = "claude-sonnet-4-6",
    n_iter: int = 6,
    eval_tasks: int = 4,
    max_recipes: int = 3,
    ledger_path: Any = "data/proposal_ledger.jsonl",
) -> list[dict[str, Any]]:
    from runtime.safety.recovery.gepa_runs import (
        get_default_store,
        record_from_result,
    )
    from runtime.safety.recovery.recipe_evaluator import (
        RecipeEvaluator,
        RecipeEvaluatorConfig,
    )

    # 1. Find recipes RecipeEvaluator considers losing.
    try:
        evaluator = RecipeEvaluator(journal, RecipeEvaluatorConfig())
        report = evaluator.evaluate()
    except Exception as exc:  # noqa: BLE001
        return [{
            "ok": False,
            "error": f"recipe evaluator failed: {type(exc).__name__}: {exc}",
        }]
    losing = [s for s in report.scores if s.verdict == "losing"]
    if not losing:
        return [{
            "ok": False,
            "skipped": True,
            "reason": (
                f"no losing recipes (scanned {report.recipes_found} "
                f"recipes from {report.trajectories_scanned} trajectories)"
            ),
        }]

    # 2. Run GEPA on each, capped at max_recipes. Sort by worst
    # score first · tackle the most-broken recipe first when budget
    # is tight.
    losing.sort(key=lambda s: s.score)
    out: list[dict[str, Any]] = []
    store = get_default_store()
    for s in losing[:max_recipes]:
        try:
            result = optimize_for_recipe(
                seed_prompt=seed_prompt,
                journal=journal,
                router=router,
                recipe_id=s.recipe_id,
                judge_model=judge_model,
                mutator_model=mutator_model,
                n_iter=n_iter,
                eval_tasks=eval_tasks,
                ledger_path=ledger_path,
                trigger="auto_propose",
            )
            rec = record_from_result(
                result, trigger="auto_propose", recipe_id=s.recipe_id,
            )
            store.add(rec)
            out.append({
                "ok": True,
                "recipe_id": s.recipe_id,
                "ts": rec.ts,
                "iterations_run": rec.iterations_run,
                "best_avg_score": rec.best_avg_score,
                "front_size": rec.front_size,
                "winner_proposal": getattr(result, "winner_proposal", None),
            })
        except Exception as exc:  # noqa: BLE001
            out.append({
                "ok": False,
                "recipe_id": s.recipe_id,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return out


__all__ = [
    "collect_failures_from_ledger",
    "collect_failures_from_journal",
    "optimize_for_recipe",
    "persist_winner",
    "propose_for_losing_recipes",
    "mark_winner_proposal_applied",
    "record_winner_canary_outcome",
    "record_winner_proposal_and_canary",
    "resolve_applied_winner_sidecar",
    "write_applied_winner_sidecar",
]
