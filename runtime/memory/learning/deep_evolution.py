"""
deep_evolution · LLM-judged self-evaluation (B2) + self-evolution (B3).

Two tiers built on top of the zero-cost ``turn_scoring`` heuristic:

    B1 (free, already in turn_scoring.py)
        Heuristic per-turn scoring + simple before/after delta on
        SOUL hash change. Catches "lesson clearly hurt latency" or
        "lesson clearly broke tool use" but can't say WHY.

    B2 · deep_reflect (cheap, ~2-3¢ per call)
        Cheap-LLM judge reads the last N scored turns + their
        trajectories + current SOUL, scores each turn 0-100,
        names dominant failure mode, suggests ONE concrete
        action: "add lesson X" / "revert last update" / "no
        action needed". Returns structured JSON. Single LLM
        round, no autonomous loop.

    B3 · deep_evolve (expensive, ~10-30¢ per run, manual trigger)
        MiniMax-style autonomous loop:
            1. analyze recent failure trajectories
            2. LLM proposes K candidate SOUL changes
            3. LLM-as-judge scores each candidate's predicted
               impact against held-out trajectories
            4. pick winner (and dry-run preview OR commit)
            5. iterate up to ``max_rounds``

        Gated by ``dry_run`` (default True): the agent / user sees
        the full proposed plan + reasoning WITHOUT mutation. Set
        ``dry_run=False`` to actually apply via update_soul. Always
        snapshots SOUL.md beforehand so revert_soul can roll back
        any commit.

Why these live here (not in suckers/)
-------------------------------------

These functions are LLM-coupled (they need a router) and not safe
to register at module import time without a router being wired up.
The wiring happens in ``app.py`` like the ephemeral runner — see
``set_evolve_router`` below. The skills layer (``memory_skills``)
exposes them as ``deep_reflect`` / ``deep_evolve`` skills with a
clean error if the router isn't wired.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from runtime.platform.llm_infra.llm_caller import LLMCaller
from runtime.platform.process.service_provider import get_provider

_LOG = logging.getLogger("octopus.deep_evolution")

_EVOLVE_CALLER = LLMCaller("evolve_router", "evolve_default_model")


def set_evolve_router(router: Any, *, default_model: str | None = None) -> None:
    """Bootstrap hook · install the router used for deep_reflect /
    deep_evolve. Pass ``None`` to disable."""
    provider = get_provider()
    provider.register_instance("evolve_router", router)
    provider.register_instance("evolve_default_model", default_model)


def _llm_call_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Backwards-compatible JSON-envelope call used by adjacent modules.

    Delegates to ``_EVOLVE_CALLER.call_json``. Kept at module scope so
    callers (and tests) can monkey-patch this symbol to stub out the
    LLM round-trip without touching the caller instance.
    """
    return _EVOLVE_CALLER.call_json(
        system=system,
        user=user,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _build_holdout_runner(*, model: str | None = None):
    """Return a ``(soul_text, prompt) -> reply`` callable backed by
    the evolve router. Used by the pre-flight holdout gate.

    Tests patch this symbol to inject a fake runner without touching
    any LLM. The returned callable uses ``LLMCaller.call`` (text mode,
    not JSON) and feeds the SOUL as a system prompt envelope.
    """
    def _runner(soul_text: str, prompt: str) -> str:
        system = (
            "<your-soul>\n" + (soul_text or "") + "\n</your-soul>"
        )
        text, _meta = _EVOLVE_CALLER.call(
            system=system,
            user=prompt,
            model=model,
            max_tokens=512,
            temperature=0.2,
        )
        return text or ""
    return _runner


# ═══════════════════════════════════════════════════════════
# B2 · deep_reflect
# ═══════════════════════════════════════════════════════════

_REFLECT_SYSTEM = """You are a meta-evaluator for an AI agent. You read its
recent turns and judge quality. Be terse and concrete. Output ONLY a
JSON envelope, no prose outside the fenced block.

Schema:
```json
{
  "overall_score": 0-100,
  "trend": "improving" | "stable" | "regressing",
  "dominant_failure_mode": "<short tag>" | null,
  "lesson_quality": "helpful" | "neutral" | "harmful" | "no_recent_lesson",
  "action": "add_lesson" | "revert_last" | "no_action",
  "action_detail": "<one-line concrete instruction>",
  "rationale": "<2-3 sentences why>"
}
```
"""


def deep_reflect(
    *, agent_id: str, window: int = 20,
    model: str | None = None,
) -> dict[str, Any]:
    """LLM-judged review of recent turns. Cheap (single LLM call).

    Reads:
        - last ``window`` per-turn scores from ``.scores.jsonl``
        - current SOUL.md content
        - the heuristic ``analyze_soul_impact`` verdict for context

    Returns a structured envelope (same shape as REFLECT schema)
    plus a ``meta`` dict with cost info + raw model output for
    audit. On router-not-wired returns ``{ok: False, error}``.
    """
    if get_provider().get("evolve_router") is None:
        return {
            "ok": False,
            "error": "deep_reflect router not configured · "
                     "call set_evolve_router(router) at boot",
        }
    from pathlib import Path

    from runtime.memory.learning.turn_scoring import (
        analyze_soul_impact as _analyze,
    )
    from runtime.memory.learning.turn_scoring import (
        read_recent_scores,
    )
    scores = read_recent_scores(agent_id, limit=window)
    if not scores:
        return {
            "ok": True,
            "verdict": {
                "overall_score": None,
                "trend": "stable",
                "dominant_failure_mode": None,
                "lesson_quality": "no_recent_lesson",
                "action": "no_action",
                "action_detail": "no scored turns yet · run a few "
                                 "first then re-evaluate",
                "rationale": "insufficient data",
            },
            "scores_count": 0,
            "meta": {"input_tokens": 0, "output_tokens": 0, "model": None},
        }

    # Read SOUL.md (best-effort)
    project_root = Path(__file__).resolve().parents[2]
    soul_path = project_root / "agents" / agent_id / "agent-core" / "SOUL.md"
    soul_content = soul_path.read_text(encoding="utf-8") if soul_path.exists() else "(no SOUL.md)"

    heuristic = _analyze(agent_id, window=window)

    # Compose the user message · concise table of recent scores +
    # current SOUL + heuristic snapshot.
    score_rows = "\n".join(
        f"  - {s.ts} · score={s.score} · reason={s.reason} · "
        f"rounds={s.rounds} · soul_hash={s.soul_hash}"
        for s in scores
    )
    user_msg = (
        f"AGENT: {agent_id}\n"
        f"WINDOW: last {len(scores)} scored turns\n\n"
        f"### Recent scores (newest first)\n{score_rows}\n\n"
        f"### Heuristic verdict (free pre-analysis)\n"
        f"{json.dumps(heuristic, ensure_ascii=False, indent=2)}\n\n"
        f"### Current SOUL.md ({len(soul_content)} chars)\n"
        f"```markdown\n{soul_content[:3000]}\n```\n\n"
        f"Now produce your JSON envelope."
    )

    parsed, meta = _EVOLVE_CALLER.call_json(
        system=_REFLECT_SYSTEM,
        user=user_msg,
        model=model,
        max_tokens=800,
        temperature=0.2,
    )
    if parsed is None:
        return {
            "ok": False,
            "error": meta.get("error") or meta.get("parse_error") or "LLM call failed",
            "meta": meta,
        }
    return {
        "ok": True,
        "verdict": parsed,
        "scores_count": len(scores),
        "heuristic": heuristic,
        "meta": meta,
    }


# ═══════════════════════════════════════════════════════════
# B3 · deep_evolve
# ═══════════════════════════════════════════════════════════

_PROPOSE_SYSTEM = """You are a self-improvement proposer for an AI agent.
You read recent turns + current SOUL and propose K candidate
changes that might improve future performance. Output ONLY a JSON
envelope, no prose outside the fenced block.

Schema:
```json
{
  "candidates": [
    {
      "id": "c1",
      "kind": "add_lesson" | "revert",
      "lesson": "<imperative one-liner>" | null,
      "tag": "<short category>" | null,
      "revert_steps": <int> | null,
      "predicted_impact": "<one sentence>",
      "risk": "low" | "medium" | "high"
    }
  ]
}
```
Only ``kind == 'add_lesson'`` uses ``lesson`` + ``tag``;
only ``kind == 'revert'`` uses ``revert_steps``. Generate exactly K
candidates. Prefer LOW risk · favor concrete tool/workflow lessons
over vague personality changes."""

_JUDGE_SYSTEM = """You are an impact judge. You read recent agent turns
and a candidate self-improvement, then predict the impact on those
SAME turns if the candidate had been active. Output ONLY a JSON envelope.

Schema:
```json
{
  "candidate_id": "<id>",
  "predicted_avg_score_delta": -1.0 .. +1.0,
  "predicted_failure_mode_change": "<short>" | "none",
  "would_help_count": <int>,
  "would_hurt_count": <int>,
  "confidence": "low" | "medium" | "high",
  "verdict": "apply" | "skip" | "needs_more_data"
}
```
Be conservative · "needs_more_data" is fine when uncertain."""


def deep_evolve(
    *, agent_id: str,
    window: int = 20,
    candidates_per_round: int = 3,
    max_rounds: int = 1,
    dry_run: bool = True,
    model: str | None = None,
) -> dict[str, Any]:
    """MiniMax-style autonomous self-improvement loop. EXPENSIVE.

    Each round:
        1. Read recent scores + SOUL + heuristic context.
        2. Propose K=``candidates_per_round`` candidate changes.
        3. Judge each candidate against the same recent turns.
        4. Pick the highest-confidence ``apply`` verdict.
        5. If ``dry_run=False``, actually mutate SOUL.md (via the
           same `update_soul` / `revert_soul` handlers, which
           snapshot for safety).

    Returns full audit trail · including all proposals, judgments,
    and applied actions. On router-not-wired returns clean error.

    Token cost (rough): ``window * 50 + candidates_per_round *
    1500`` per round, so ``max_rounds=1`` ~ 5K tokens, ``max_rounds=5``
    ~25K tokens. Default 1 round to keep cost bounded.
    """
    if get_provider().get("evolve_router") is None:
        return {
            "ok": False,
            "error": "deep_evolve router not configured",
        }
    from pathlib import Path

    from runtime.memory.learning.turn_scoring import (
        analyze_soul_impact as _analyze,
    )
    from runtime.memory.learning.turn_scoring import (
        read_recent_scores,
    )

    project_root = Path(__file__).resolve().parents[2]
    soul_path = project_root / "agents" / agent_id / "agent-core" / "SOUL.md"
    audit: list[dict[str, Any]] = []
    total_in = 0
    total_out = 0
    applied: list[dict[str, Any]] = []

    for round_i in range(max(1, int(max_rounds))):
        scores = read_recent_scores(agent_id, limit=window)
        if not scores:
            audit.append({
                "round": round_i + 1,
                "skipped": "no scored turns yet",
            })
            break
        soul_content = (
            soul_path.read_text(encoding="utf-8")
            if soul_path.exists() else "(no SOUL.md)"
        )
        heuristic = _analyze(agent_id, window=window)

        score_rows = "\n".join(
            f"  - {s.ts} · score={s.score} · reason={s.reason} · "
            f"rounds={s.rounds} · soul_hash={s.soul_hash}"
            for s in scores
        )
        propose_user = (
            f"AGENT: {agent_id}\n"
            f"ROUND: {round_i + 1}/{max_rounds}\n"
            f"K = {candidates_per_round}\n\n"
            f"### Recent scores\n{score_rows}\n\n"
            f"### Heuristic verdict\n"
            f"{json.dumps(heuristic, ensure_ascii=False)}\n\n"
            f"### Current SOUL\n```markdown\n{soul_content[:2500]}\n```\n\n"
            f"Propose {candidates_per_round} candidate changes."
        )
        proposal, p_meta = _EVOLVE_CALLER.call_json(
            system=_PROPOSE_SYSTEM,
            user=propose_user,
            model=model,
            max_tokens=1500,
            temperature=0.5,
        )
        total_in += int(p_meta.get("input_tokens", 0) or 0)
        total_out += int(p_meta.get("output_tokens", 0) or 0)
        if proposal is None:
            audit.append({
                "round": round_i + 1,
                "stage": "propose",
                "error": p_meta.get("error") or p_meta.get("parse_error"),
            })
            break
        candidates = proposal.get("candidates", [])
        if not candidates:
            audit.append({
                "round": round_i + 1,
                "stage": "propose",
                "result": "no candidates produced",
            })
            break

        # Judge each candidate.
        judgments: list[dict[str, Any]] = []
        for cand in candidates:
            judge_user = (
                f"AGENT: {agent_id}\n\n"
                f"### Recent turns\n{score_rows}\n\n"
                f"### Candidate\n"
                f"{json.dumps(cand, ensure_ascii=False, indent=2)}\n\n"
                f"Predict impact + verdict."
            )
            judgment, j_meta = _EVOLVE_CALLER.call_json(
                system=_JUDGE_SYSTEM,
                user=judge_user,
                model=model,
                max_tokens=400,
                temperature=0.1,
            )
            total_in += int(j_meta.get("input_tokens", 0) or 0)
            total_out += int(j_meta.get("output_tokens", 0) or 0)
            judgments.append({
                "candidate": cand,
                "judgment": judgment or {"verdict": "judge_failed"},
            })

        # Pick the best apply-verdict, prefer high confidence.
        winner = None
        for entry in judgments:
            v = (entry["judgment"] or {}).get("verdict")
            if v == "apply":
                conf = (entry["judgment"] or {}).get("confidence", "low")
                # Prefer higher-confidence applies; first-found at
                # 'high' wins, else any 'medium', else first 'apply'.
                if winner is None:
                    winner = entry
                else:
                    cur = (winner["judgment"] or {}).get("confidence", "low")
                    rank = {"high": 3, "medium": 2, "low": 1}
                    if rank.get(conf, 0) > rank.get(cur, 0):
                        winner = entry

        round_record: dict[str, Any] = {
            "round": round_i + 1,
            "candidates": candidates,
            "judgments": judgments,
            "winner": winner,
            "dry_run": dry_run,
        }

        if winner and not dry_run:
            cand = winner["candidate"]
            kind = cand.get("kind")
            # ── Pre-flight holdout gate ─────────────────────────
            # Only meaningful for ``add_lesson`` (which mutates the
            # SOUL by appending a line). ``revert`` walks the journal
            # back, so a holdout check on the proposed text would be
            # meaningless — let the post-apply canary watch it.
            if kind == "add_lesson":
                try:
                    from runtime.memory.learning.soul_holdout import (
                        GatePolicy,
                        evaluate_against_holdout,
                        load_holdout,
                    )
                    from runtime.memory.learning.soul_holdout import (
                        gate as _holdout_gate,
                    )
                    entries = load_holdout(agent_id)
                    if entries:
                        lesson_line = str(cand.get("lesson") or "").strip()
                        proposed_soul = (
                            soul_content.rstrip() + "\n- " + lesson_line + "\n"
                        ) if lesson_line else soul_content
                        runner = _build_holdout_runner(model=model)
                        old_result = evaluate_against_holdout(
                            agent_id, soul_content, runner, entries,
                        )
                        new_result = evaluate_against_holdout(
                            agent_id, proposed_soul, runner, entries,
                        )
                        allowed, reason = _holdout_gate(
                            new_result, old_result, GatePolicy(),
                        )
                        if not allowed:
                            round_record["applied"] = {
                                "ok": False,
                                "applied": False,
                                "error": "holdout_regression",
                                "reason": reason,
                                "old_pass_rate": old_result.pass_rate,
                                "new_pass_rate": new_result.pass_rate,
                                "regressions": [
                                    d for d in new_result.detail
                                    if d["score"] == 0
                                ],
                            }
                            audit.append(round_record)
                            continue
                except (ImportError, OSError) as _exc:
                    _LOG.debug("holdout gate skipped: %s", _exc)
            try:
                from runtime.execution.suckers.memory_skills import (
                    _revert_soul,
                    _update_soul,
                )
                if kind == "add_lesson":
                    res = _update_soul(
                        lesson=str(cand.get("lesson") or ""),
                        tag=f"deep-evolve · {cand.get('tag') or ''}",
                    )
                    round_record["applied"] = {"kind": "add_lesson", "result": res}
                    applied.append(round_record["applied"])
                    try:
                        from runtime.safety.evolution.proposal_ledger import ProposalLedger
                        _ledger = ProposalLedger()
                        _ledger.propose(
                            kind="deep_evolve_add_lesson",
                            description=str(cand.get("lesson") or ""),
                            proposer="deep_evolve",
                            fitness_before=None,
                        )
                    except Exception as _exc:
                        _LOG.debug("evolution ledger record failed: %s", _exc)
                elif kind == "revert":
                    res = _revert_soul(
                        steps_back=int(cand.get("revert_steps", 1) or 1),
                        reason=f"deep-evolve · {cand.get('predicted_impact', '')}"[:60],
                    )
                    round_record["applied"] = {"kind": "revert", "result": res}
                    applied.append(round_record["applied"])
            except (ImportError, TypeError, ValueError) as exc:
                round_record["applied"] = {
                    "error": f"apply failed: {type(exc).__name__}: {exc}",
                }

        audit.append(round_record)

    return {
        "ok": True,
        "rounds_run": len(audit),
        "audit": audit,
        "applied": applied,
        "dry_run": dry_run,
        "cost": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "approx_usd": round(
                (total_in / 1e6) * 0.80 + (total_out / 1e6) * 4.0,  # haiku rates
                4,
            ),
        },
    }


__all__ = [
    "set_evolve_router",
    "deep_reflect",
    "deep_evolve",
]
