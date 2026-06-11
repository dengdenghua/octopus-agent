"""Reflex, gene-locks, and forge admin routes for the UI app."""
from __future__ import annotations

import contextlib
import json
import os
import time
from datetime import UTC
from typing import Any

from fastapi.responses import HTMLResponse, PlainTextResponse


def mount_reflex_admin_routes(
    app: Any,
    *,
    stack: Any,
    reflex_router: Any,
    panel_html: str,
    editor_html: str,
) -> None:
    """Mount optional Reflex admin routes when a reflex router exists."""
    if reflex_router is None:
        return
    _reflex_router = reflex_router
    _REFLEX_PANEL_HTML = panel_html  # noqa: N806
    _REFLEX_EDITOR_HTML = editor_html  # noqa: N806

    from fastapi import APIRouter as _AR  # noqa: N814

    _reflex_admin = _AR(tags=["reflex-admin"])

    @_reflex_admin.get("/api/reflex/stats")
    def _reflex_stats(stale_hours: float = 24.0) -> dict:
        return {
            "try_count": _reflex_router.try_count,
            "hit_count": _reflex_router.hit_count,
            "hit_rate": _reflex_router.hit_rate,
            "by_rule": _reflex_router.stats_by_rule(),
            # Coverage callout · which rules look unused so the
            # operator can prune them. Threshold is configurable
            "coverage": _reflex_router.coverage_summary(
                stale_hours=stale_hours,
            ),
        }

    @_reflex_admin.get("/api/reflex/rules")
    def _reflex_rules() -> dict:
        return {"rules": _reflex_router.list_rules()}

    @_reflex_admin.get("/api/reflex/timeseries")
    def _reflex_timeseries(
        window_minutes: int = 60,
        bucket_seconds: int = 60,
    ) -> dict:
        """Bucketed reflex_hit counts over the last ``window_minutes``.

        Reads ``stack.journal`` (in-process · works for both
        InMemoryJournal and JSONLJournal). Counts ALL reflex_hit
        events including the synthetic action-result ones · the
        UI can split them by ``rule_id`` (real rule) vs
        ``rule_id/kind`` shape (action result) when needed.

        Returns ``{buckets: [{ts, count, by_rule}], ...}`` ·
        empty buckets are included so the sparkline doesn't
        visually compress gaps.
        """
        from datetime import datetime, timedelta
        try:
            window = timedelta(minutes=max(1, int(window_minutes)))
            bucket = max(1, int(bucket_seconds))
            now = datetime.now(UTC)
            since = now - window
            events = stack.journal.read_by_type("reflex_hit")
            # Filter to window
            evs = [
                e for e in events
                if getattr(e, "ts", None) and e.ts >= since
            ]
            # Bucket by floor(ts) → bucket-aligned epoch second
            num_buckets = max(1, int(window.total_seconds() / bucket))
            start_epoch = int(since.timestamp())
            buckets: list[dict] = []
            for i in range(num_buckets):
                buckets.append({
                    "ts": start_epoch + i * bucket,
                    "count": 0,
                    "by_rule": {},
                })
            for e in evs:
                epoch = int(e.ts.timestamp())
                idx = (epoch - start_epoch) // bucket
                if 0 <= idx < num_buckets:
                    b = buckets[idx]
                    b["count"] += 1
                    rid = getattr(e, "rule_id", "?")
                    b["by_rule"][rid] = b["by_rule"].get(rid, 0) + 1
            # Per-rule totals over the window · easy hit-leader chart
            totals: dict[str, int] = {}
            for b in buckets:
                for rid, n in b["by_rule"].items():
                    totals[rid] = totals.get(rid, 0) + n
            return {
                "window_minutes": int(window.total_seconds() / 60),
                "bucket_seconds": bucket,
                "buckets": buckets,
                "totals_by_rule": totals,
                "total_events": sum(b["count"] for b in buckets),
            }
        except (OSError, ValueError, TypeError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @_reflex_admin.get("/api/reflex/suggestions")
    def _reflex_suggestions(
        min_count: int = 3,
        limit: int = 20,
        cluster: bool = False,
        similarity: float = 0.6,
        draft_replies: bool = False,
        draft_model: str | None = None,
    ) -> dict:
        from runtime.core.nerves.reflex.suggestions import get_default_tracker
        t = get_default_tracker()
        sugs = t.suggestions(
            min_count=min_count, limit=limit,
            cluster=cluster, similarity=similarity,
        )
        drafts: dict[str, str] = {}
        if draft_replies and sugs:
            try:
                from runtime.core.nerves.reflex.reply_drafter import (
                    apply_drafts_to_yaml,
                )
                from runtime.core.nerves.reflex.reply_drafter import (
                    draft_replies as _draft,
                )
                router = getattr(stack.planner, "router", None)
                drafts = _draft(sugs, router=router, model=draft_model)
                # Stamp drafted replies into each suggestion's
                # ``suggested_yaml`` so the panel / curl user
                # sees the filled-in version directly.
                for s in sugs:
                    d = drafts.get(s.get("prompt", ""))
                    if d:
                        s["drafted_reply"] = d
                        s["suggested_yaml"] = apply_drafts_to_yaml(
                            s["suggested_yaml"], d,
                        )
            except (OSError, ImportError, TypeError) as exc:
                drafts = {"_error": f"{type(exc).__name__}: {exc}"}
        return {
            "tracker": t.stats(),
            "min_count": min_count,
            "cluster": cluster,
            "similarity": similarity if cluster else None,
            "drafts_attempted": draft_replies,
            "drafts_count": len([
                k for k in drafts if not k.startswith("_")
            ]),
            "suggestions": sugs,
        }

    @_reflex_admin.post("/api/reflex/suggestions/reset")
    def _reflex_suggestions_reset() -> dict:
        """Drop all tracked unmatched prompts · use after applying
        a batch of suggestions so the next round starts fresh."""
        from runtime.core.nerves.reflex.suggestions import get_default_tracker
        return {"dropped": get_default_tracker().reset()}

    @_reflex_admin.post("/api/reflex/auto-pr")
    def _reflex_auto_pr(
        min_count: int = 3,
        limit: int = 20,
        cluster: bool = True,
        similarity: float = 0.6,
        push: bool = False,
        open_pr: bool = False,
        base_branch: str = "main",
    ) -> dict:
        """Materialize current suggestions into a real git
        branch + commit (and optionally push + open a PR via
        ``gh``). The reply text is left as TODO · operator
        still owns picking the right answer.

        Defaults are conservative: ``push=false open_pr=false``
        means "stage everything locally so I can review on the
        box before pushing". Set both true to do the round trip
        in one call (CI / scripted use).
        """
        from runtime.core.nerves.reflex.auto_pr import generate_pr
        from runtime.core.nerves.reflex.rules_loader import find_default_rules_file
        from runtime.core.nerves.reflex.suggestions import get_default_tracker

        path = find_default_rules_file()
        if path is None:
            return {"ok": False, "error": "no rules file found"}
        sugs = get_default_tracker().suggestions(
            min_count=min_count, limit=limit,
            cluster=cluster, similarity=similarity,
        )
        if not sugs:
            return {
                "ok": False,
                "error": f"no suggestions with count >= {min_count}",
            }
        return generate_pr(
            file_path=path,
            suggestions=sugs,
            push=push,
            open_pr=open_pr,
            base_branch=base_branch,
        )

    # Module-scope mutable holding the most recent reload diff.
    # Survives across requests · cleared on process restart. The
    # admin panel reads this to render "last reload added X
    # removed Y modified Z" so operators can verify their yaml
    # edit landed correctly.
    _last_reload_state: dict = {
        "ts": None,
        "added": [],
        "removed": [],
        "modified": [],
        "unchanged_count": 0,
    }

    def _snapshot_rules(rules: list) -> dict[str, dict]:
        """Capture the comparable shape of each rule · we only
        include fields that, if changed, make the rule semantically
        different (pattern, priority, intent_type, ttl, action
        presence, variant count). Hit counts deliberately excluded
        so a "no real change" reload doesn't show as a modify."""
        snap: dict[str, dict] = {}
        for r in rules:
            pat = getattr(r, "_regex", None)
            spec = getattr(r, "_action_spec", None)
            vars_ = getattr(r, "_variants", None)
            snap[r.rule_id] = {
                "kind": r.kind,
                "priority": r.priority,
                "pattern": pat.pattern if pat is not None else None,
                "intent_type": getattr(r, "_intent_type", None),
                "ttl_seconds": getattr(r, "_ttl_seconds", None),
                "actions": sorted(
                    k for k in ("webhook", "mqtt", "exec")
                    if spec is not None and getattr(spec, k, None) is not None
                ) if spec else [],
                "variant_count": len(vars_) if vars_ else 0,
            }
        return snap

    @_reflex_admin.post("/api/reflex/reload")
    def _reflex_reload(
        reset_stats: bool = False,
        commit: bool = False,
    ) -> dict:
        """Re-read ``data/reflex_rules.yaml`` and swap matcher
        list in-place. Returns the new rule count + a diff vs
        the rules that were active before this call (added /
        removed / modified) so operators can confirm their edit
        had the intended effect.

        Query param ``reset_stats=true`` clears the hit-rate
        counters · default keeps them so before/after compares
        stay meaningful.
        """
        import time as _t

        from runtime.cli import _build_reflex_router
        try:
            # Snapshot the current rules BEFORE swapping.
            before = _snapshot_rules(_reflex_router._reflexes)
            fresh = _build_reflex_router()
            count = _reflex_router.replace_reflexes(
                fresh._reflexes,
                reset_stats=reset_stats,
            )
            after = _snapshot_rules(_reflex_router._reflexes)

            # Compute diff · added/removed by id, modified by
            # comparing the snapshot dicts.
            added = sorted(set(after) - set(before))
            removed = sorted(set(before) - set(after))
            modified = sorted(
                rid for rid in (set(after) & set(before))
                if before[rid] != after[rid]
            )
            unchanged = len((set(after) & set(before)) - set(modified))
            _last_reload_state.update({
                "ts": _t.time(),
                "added": added,
                "removed": removed,
                "modified": [
                    {
                        "rule_id": rid,
                        "before": before[rid],
                        "after": after[rid],
                    } for rid in modified
                ],
                "unchanged_count": unchanged,
                "rules_loaded": count,
            })
            # Optional git auto-commit · only when the operator
            # the YAML file enables it via top-level
            # ``git_tracking: true`` · TODO future). The reload
            # itself succeeds regardless of git's outcome.
            git_result: dict = {}
            if commit:
                try:
                    from runtime.core.nerves.reflex.git_track import (
                        auto_commit,
                        format_diff_summary,
                    )
                    from runtime.core.nerves.reflex.rules_loader import (
                        find_default_rules_file,
                    )
                    path = find_default_rules_file()
                    if path is not None:
                        git_result = auto_commit(
                            path,
                            diff_summary=format_diff_summary({
                                "added": added,
                                "removed": removed,
                                "modified": modified,
                            }),
                        )
                    else:
                        git_result = {"ok": False, "error": "no rules file"}
                except ImportError as ie:
                    git_result = {"ok": False, "error": str(ie)}
                except (OSError, ValueError) as exc:
                    git_result = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }

            return {
                "ok": True,
                "rules_loaded": count,
                "stats_reset": reset_stats,
                "diff": {
                    "added": added,
                    "removed": removed,
                    "modified": modified,
                    "unchanged_count": unchanged,
                },
                "git": git_result if commit else None,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @_reflex_admin.get("/api/reflex/test")
    def _reflex_test() -> dict:
        """Run every ``expects:`` test case from the YAML and
        return a CI-style summary. Lets the operator (or a
        pre-deploy hook) catch reflex regressions before they
        ship · "this rule used to match 'X' but doesn't anymore"
        is exactly the kind of bug a static test suite catches.

        Doesn't mutate state · safe to call repeatedly.
        """
        from runtime.core.nerves.reflex.test_runner import run_tests
        return run_tests(_reflex_router)

    @_reflex_admin.get("/api/reflex/git/history")
    def _reflex_git_history(limit: int = 20) -> dict:
        """Return the most recent git commits touching the rules
        file · empty list when git isn't initialized in the
        repo. Lets ops see "who changed what when" without
        shelling in."""
        from runtime.core.nerves.reflex.git_track import file_history
        from runtime.core.nerves.reflex.rules_loader import find_default_rules_file
        path = find_default_rules_file()
        if path is None:
            return {"history": [], "error": "no rules file"}
        return {"history": file_history(path, limit=limit)}

    @_reflex_admin.get("/api/reflex/last-reload")
    def _reflex_last_reload() -> dict:
        """Return the most recent reload's diff details · empty
        until /api/reflex/reload has been called at least once."""
        return dict(_last_reload_state)

    @_reflex_admin.get("/api/reflex/broadcast")
    def _reflex_broadcast_config() -> dict:
        """Show the active outbound broadcast config · sanitized
        (no credentials returned). Lets ops verify the yaml's
        ``broadcast.mqtt`` block was picked up correctly."""
        from runtime.core.nerves.reflex.broadcast import get_default_broadcaster
        return get_default_broadcaster().describe()

    @_reflex_admin.get("/api/reflex/tiers")
    def _reflex_tiers() -> dict:
        """Expose response-tier stats · how many requests each
        tier (fuzzy_cache / slm / ...) absorbed, what fraction
        never reached the planner. The reflex layer itself is
        tier 0 · its stats live in /api/reflex/stats already.
        """
        from runtime.core.nerves.reflex.tiers import (
            get_default_fuzzy_cache,
            get_default_slm,
        )
        return {
            "tiers": [
                get_default_fuzzy_cache().describe(),
                get_default_slm().describe(),
            ],
        }

    @_reflex_admin.post("/api/evolution/gepa/run")
    def _gepa_run(
        n_iter: int = 8,
        eval_tasks: int = 4,
        recipe_id: str | None = None,
        judge_model: str = "claude-sonnet-4-6",
        mutator_model: str = "claude-sonnet-4-6",
        optimizer_backend: str | None = None,
    ) -> dict:
        """Trigger one GEPA optimization run · pulls failed
        trajectories from the journal, mutates the planner's
        current system prompt, scores candidates with
        LLM-as-judge, returns the Pareto front + best.

        Does NOT auto-apply · operator inspects the result and
        POSTs /api/evolution/gepa/apply to persist the winner
        as a planner prompt addendum. Default budget (8 iter
        × 4 task judges × ~2 LLM calls) is ~64 LLM calls per
        run · tune ``n_iter``/``eval_tasks`` to taste.
        """
        try:
            from runtime.safety.recovery.optimizer_backends import (
                OptimizerRunConfig,
                optimize_with_backend,
            )
            planner = stack.planner
            # Seed = the planner's current base prompt. We'd
            # ideally include learned_rules + memories sections
            # too, but keeping the seed scope to the base lets
            # GEPA produce a clean delta we can review.
            seed = (
                getattr(planner, "_PLANNER_SYSTEM_PROMPT", "")
                or getattr(planner, "base_prompt", "")
                or ""
            )
            if not seed:
                # Fall back to module-level constant · loaded once
                # at import. Re-trigger the loader in case the
                # prompts file changed since boot.
                try:
                    from runtime.core.cerebrum.llm_planner import (
                        _load_planner_prompt,
                    )
                    seed = _load_planner_prompt()
                except (ImportError, OSError, TypeError, AttributeError):  # noqa: BLE001
                    seed = "You are a planner. Build a TaskGraph for the user goal."
            router = getattr(planner, "router", None)
            if router is None:
                return {"ok": False, "error": "planner.router missing"}
            result = optimize_with_backend(
                seed_prompt=seed,
                journal=stack.journal,
                router=router,
                config=OptimizerRunConfig(
                    backend=optimizer_backend or os.environ.get("OCTOPUS_OPTIMIZER_BACKEND") or "native_gepa",
                    recipe_id=recipe_id,
                    judge_model=judge_model,
                    mutator_model=mutator_model,
                    n_iter=n_iter,
                    eval_tasks=eval_tasks,
                    trigger="manual",
                ),
            )
            # Persist to the run store so /api/evolution/gepa/runs
            # can show "last N runs". Always store · even
            # zero-iter (no-data) runs are useful for the
            # operator to see "I tried it, here's why it didn't
            # produce anything".
            try:
                from runtime.safety.recovery.gepa_runs import (
                    get_default_store,
                    record_from_result,
                )
                store = get_default_store()
                rec = record_from_result(
                    result, trigger="manual", recipe_id=recipe_id,
                )
                store.add(rec)
                _run_ts = rec.ts
            except (OSError, ImportError, TypeError, ValueError) as _exc:  # noqa: BLE001
                    _run_ts = None
            return {
                "ok": True,
                "optimizer_backend": getattr(result, "optimizer_backend", None) or "native_gepa",
                "iterations_run": result.iterations_run,
                "elapsed_s": result.elapsed_s,
                "front_size": len(result.final_front),
                "ts": _run_ts,
                # Echo the recipe_id back so the panel can offer
                # "Apply to <recipe>" when the run was scoped.
                # None / missing means the run wasn't scoped to
                # a specific recipe · panel offers "Apply
                # globally" only.
                "recipe_id": recipe_id,
                "best": (
                    {
                        "candidate_id": result.best_avg.candidate_id,
                        "avg_score": result.best_avg.avg_score,
                        "task_scores": result.best_avg.task_scores,
                        "rationale": result.best_avg.rationale,
                        "prompt_preview": result.best_avg.prompt[:400],
                    } if result.best_avg else None
                ),
                "winner_proposal": getattr(result, "winner_proposal", None),
                "native_evaluation": getattr(result, "native_evaluation", []),
                "native_replay": getattr(result, "native_replay", {}),
                "native_sandbox_replay": getattr(result, "native_sandbox_replay", {}),
                "native_turn_replay": getattr(result, "native_turn_replay", {}),
                "native_llm_replay": getattr(result, "native_llm_replay", {}),
                "history": result.history,
                "source": "gepa",
            }
        except (
            OSError,
            ImportError,
            ValueError,
            TypeError,
            RuntimeError,
            NotImplementedError,
        ) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "source": "gepa"}

    # ─── Gene-lock admin endpoints ──────────────────────────
    # Operator inspects current maturity level, triggers panic,
    # clears panic. Levels are 0..4 · see docs/gene-locks.md.
    # Panic engages immediately; maturity changes are MONOTONIC-
    # aware (up requires signature in prod mode).
    #
    # Header alias is imported here because the endpoint
    # functions below use it as a default parameter value ·
    # Python evaluates defaults at def-time, so the import must
    # happen before any of these ``def`` statements.
    from fastapi import Header as _Header

    @_reflex_admin.get("/api/gene-locks/status")
    def _gene_locks_status() -> dict:
        from runtime.safety.gene_locks import get_state
        return get_state()

    @_reflex_admin.post("/api/gene-locks/maturity")
    def _gene_locks_set_maturity(
        body: dict,
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Change maturity level · body: ``{"level": 0..4}``."""
        from runtime.safety.gene_locks import LockViolation, set_maturity
        try:
            lvl = int(body.get("level", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "level must be 0..4"}
        try:
            return set_maturity(
                lvl, human_signed=bool(x_human_approver),
            )
        except LockViolation as lv:
            return lv.as_dict()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    @_reflex_admin.post("/api/gene-locks/panic")
    def _gene_locks_panic_trigger(body: dict) -> dict:
        """Engage panic state · freezes every mutation. Body:
        ``{"reason": "..."}``. Auto-degrades maturity to
        Level 1 per CC-G5 invariant."""
        from runtime.safety.gene_locks import trigger_panic
        reason = str(body.get("reason") or "operator-triggered")
        return trigger_panic(reason)

    @_reflex_admin.post("/api/gene-locks/mode")
    def _gene_locks_set_mode(
        body: dict,
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Flip dev↔production mode at runtime · relaxing
        (prod→dev) requires a human-approver header. Useful
        for smoke-testing the hard-block paths without a
        server restart."""
        from runtime.safety.gene_locks import LockViolation, set_mode
        try:
            return set_mode(
                str(body.get("mode", "")),
                human_signed=bool(x_human_approver),
            )
        except LockViolation as lv:
            return lv.as_dict()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    @_reflex_admin.post("/api/gene-locks/integrity/reset")
    def _gene_locks_integrity_reset(
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Clear a latched IMMUTABLE-integrity alarm · operator
        acknowledges they've inspected the mismatch. Prod mode
        requires the approver header. Doesn't patch IMMUTABLE
        values · a re-``_load`` will re-trigger the alarm if
        the persisted state still disagrees with compiled
        constants (so the real fix is a code release OR
        deleting the state file to re-bootstrap)."""
        from runtime.safety.gene_locks import (
            LockViolation,
            reset_integrity_alarm,
        )
        try:
            return reset_integrity_alarm(
                human_signed=bool(x_human_approver),
            )
        except LockViolation as lv:
            return lv.as_dict()

    @_reflex_admin.post("/api/gene-locks/debug/reload-cache")
    def _gene_locks_reload_cache() -> dict:
        """Force-invalidate the in-memory state cache · next
        ``_load()`` re-reads ``data/gene_locks.json`` from disk,
        re-runs the IMMUTABLE integrity check, and re-evaluates
        ``_INTEGRITY_FAILED``.

        Purpose: testing. Without this, a tamper test that
        modifies the state file can't see the check fire
        because the server's cached ``LockState`` survives
        the edit (held in RAM, not re-read). Exposing it as
        an admin endpoint lets integration tests simulate a
        restart without actually restarting the process.

        Side-effect only · returns the fresh status snapshot
        so the caller can assert on ``integrity_ok`` without
        a second round-trip."""
        from runtime.safety.gene_locks import simple_gate
        with simple_gate._STATE_LOCK:
            simple_gate._CACHED = None
            simple_gate._INTEGRITY_FAILED = None
        # Trigger a re-load so the response already reflects
        # the new on-disk state.
        from runtime.safety.gene_locks import get_state
        return {"ok": True, "reloaded": True, "state": get_state()}

    @_reflex_admin.get("/api/gene-locks/approvals")
    def _gene_locks_approvals(limit: int = 50) -> dict:
        """Recent approver signatures · feeds the audit view.
        Entries beyond the window are still returned so the
        operator can see stale signatures ('Alice signed 3
        days ago') · the gate itself only counts in-window."""
        from runtime.safety.gene_locks import get_ledger
        return {
            "window_s": get_ledger().window_s,
            "recent": get_ledger().recent(limit=limit),
        }

    @_reflex_admin.post("/api/gene-locks/panic/clear")
    def _gene_locks_panic_clear(
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Clear panic · production deploys require a human
        approver header. Maturity stays at whatever the panic
        degraded it to · operator must re-raise explicitly."""
        from runtime.safety.gene_locks import LockViolation, clear_panic
        try:
            return clear_panic(human_signed=bool(x_human_approver))
        except LockViolation as lv:
            return lv.as_dict()

    # ─── Gene-lock gate helper · extracts the approver header
    # from FastAPI Request state so endpoints don't have to
    # reach into internals. Lives here so it can close over
    # ``_reflex_admin`` / the stack. ``_Header`` was imported
    # higher up, alongside the gene-lock admin endpoints.
    def _gate_forge_mutation(
        kind: str, target: str, *, approver: str | None,
        bypass_cooldown: bool = False,
    ) -> dict:
        """Thin wrapper around gene_locks.gate_mutation that
        turns ``LockViolation`` into a consistent dict the
        endpoint returns verbatim (HTTP 200 with
        ``ok=False + gene_lock_violation=True``). Easier for
        the frontend than parsing a 403."""
        from runtime.safety.gene_locks import LockViolation, gate_mutation
        try:
            return gate_mutation(
                kind=kind, target=target,
                autonomous=approver is None,
                approver=approver,
                bypass_cooldown=bypass_cooldown,
            )
        except LockViolation as lv:
            return lv.as_dict()

    @_reflex_admin.post("/api/evolution/gepa/apply")
    def _gepa_apply(
        body: dict,
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Persist a candidate's prompt as a GEPA addendum.

        Body shape::

            {
              "prompt": <text>,            # required
              "candidate_id": ...,         # for the metadata header
              "avg_score": ...,            # for the metadata header
              "rationale": ...,            # for the metadata header
              "run_ts": <float>,           # mark history applied
              "target_recipe_id": <str>    # NEW · routes to per-recipe
                                           # file at
                                           # ``data/gepa_addendums/<id>.md``
                                           # · when omitted, falls back
                                           # to the legacy global file
                                           # for back-compat
            }

        The next planner instance loads the matching addendum on
        its first plan() call · no restart needed. Per-recipe
        scope means the prompt only affects turns that match the
        target recipe_id, leaving winning recipes untouched.
        """
        from runtime.core.cerebrum.prompt_persistence import dump_section
        text = body.get("prompt")
        if not isinstance(text, str) or not text.strip():
            return {"ok": False, "error": "missing prompt"}
        target_recipe_id = body.get("target_recipe_id")

        # Gene-lock gate · blocks per LEVEL / TEMPORAL / PANIC.
        # Target key for TEMPORAL cooldown = the recipe_id when
        # per-recipe, "global" for legacy path. Variant apply
        # shares the same cooldown bucket as non-variant apply
        # for the same recipe (all 3 paths are "changing this
        # recipe's prompt").
        from runtime.safety.gene_locks import MutationKind, record_mutation
        _gate = _gate_forge_mutation(
            MutationKind.APPLY_ADDENDUM,
            target=target_recipe_id or "__global__",
            approver=x_human_approver,
        )
        if not _gate.get("ok"):
            return _gate
        section = (
            "## GEPA-optimized addendum\n\n"
            f"<!-- candidate {body.get('candidate_id', '?')} · "
            f"avg_score {body.get('avg_score', 0)} · "
            f"recipe {target_recipe_id or 'global'} · "
            f"rationale: {body.get('rationale', '')} -->\n\n"
            + text
        )
        try:
            # NEW · variant routing. When ``variant_id`` is set
            # alongside ``target_recipe_id``, route into the
            # per-recipe variant manifest instead of the single
            # per-recipe file. Lets the operator A/B-split
            # multiple GEPA candidates against the same recipe.
            variant_id = body.get("variant_id")
            variant_weight = body.get("variant_weight", 1)
            if (
                isinstance(target_recipe_id, str) and target_recipe_id.strip()
                and isinstance(variant_id, str) and variant_id.strip()
            ):
                from runtime.safety.recovery.gepa_variants import (
                    add_variant,
                )
                add_variant(
                    target_recipe_id, variant_id,
                    content=section,
                    weight=int(variant_weight) if isinstance(variant_weight, (int, float)) else 1,
                    candidate_id=str(body.get("candidate_id", "")),
                    rationale=str(body.get("rationale", "")),
                    avg_score=(
                        float(body["avg_score"])
                        if isinstance(body.get("avg_score"), (int, float))
                        else None
                    ),
                )
                # Let the variants module compute the canonical
                # on-disk path so the rebrand doesn't leak
                # through hardcoded directory names.
                from runtime.safety.recovery.gepa_variants import (
                    variant_path as _variant_path,
                )
                target = _variant_path(target_recipe_id, variant_id)
                scope = "variant"
            elif isinstance(target_recipe_id, str) and target_recipe_id.strip():
                # Per-recipe path · isolates the addendum to
                # turns whose planner recipe_hash matches.
                from runtime.safety.recovery.gepa_addendum_store import (
                    save_for_recipe,
                )
                target = save_for_recipe(target_recipe_id, section)
                scope = "per_recipe"
            else:
                # Global scope · route through the addendum
                # store helper so the path name tracks the
                # current branding (and auto-migrates from
                # any pre-rebrand filename).
                from runtime.safety.recovery.gepa_addendum_store import (
                    legacy_global_path,
                )
                target = legacy_global_path()
                dump_section(target, section, label="forge")
                scope = "global"
            # Mark the originating run as applied · best-effort.
            run_ts_raw = body.get("run_ts")
            applied_flag = False
            if isinstance(run_ts_raw, (int, float)):
                try:
                    from runtime.safety.recovery.gepa_runs import (
                        get_default_store,
                    )
                    applied_flag = get_default_store().mark_applied(
                        ts=float(run_ts_raw),
                    )
                except (OSError, ImportError, TypeError, ValueError) as _exc:  # noqa: BLE001
                    pass
            # Gene-lock bookkeeping · stamp the cooldown AFTER the
            # write succeeds so a failed write doesn't start a
            # cooldown for nothing.
            winner_payload = body.get("winner_proposal")
            if not isinstance(winner_payload, dict):
                winner_payload = {}
            winner_applied = {"ok": False, "skipped": True, "reason": "no_winner_payload"}
            with contextlib.suppress(ImportError, OSError, TypeError, ValueError):
                from runtime.safety.recovery.gepa_bridge import (
                    mark_winner_proposal_applied,
                )

                winner_applied = mark_winner_proposal_applied(
                    recipe_id=target_recipe_id if isinstance(target_recipe_id, str) and target_recipe_id.strip() else None,
                    variant_id=variant_id if scope == "variant" else None,
                    candidate_id=str(winner_payload.get("candidate_id") or body.get("candidate_id") or "") or None,
                    proposal_id=str(winner_payload.get("proposal_id") or body.get("proposal_id") or "") or None,
                    canary_key=str(winner_payload.get("canary_key") or body.get("canary_key") or "") or None,
                    ledger_path="data/proposal_ledger.jsonl",
                )
            with contextlib.suppress(ImportError, OSError, TypeError, ValueError):
                record_mutation(
                    MutationKind.APPLY_ADDENDUM,
                    target_recipe_id or "__global__",
                )
            return {
                "ok": True,
                "scope": scope,
                "target_recipe_id": target_recipe_id,
                "variant_id": variant_id if scope == "variant" else None,
                "path": str(target),
                "size": len(section),
                "run_marked_applied": applied_flag,
                "winner_applied": winner_applied,
                "gene_lock": {
                    "level": _gate.get("level"),
                    "warnings": _gate.get("warnings", []),
                },
                "source": "gepa",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "source": "gepa"}

    @_reflex_admin.get("/api/evolution/gepa/runs.csv")
    def _gepa_runs_csv() -> Any:
        """Export GEPA run history as CSV · operators paste into
        Sheets / load into Pandas for cross-run analysis. The
        React panel exposes this through a download button so
        "share this with the team" is one click instead of
        "curl, jq, manually shape".

        Header row matches the GepaRunRecord shape · history
        details are skipped here (they're too nested for CSV;
        the JSON endpoint stays the source of truth for that).
        """
        import csv
        import io

        from runtime.safety.recovery.gepa_runs import get_default_store
        store = get_default_store()
        runs = store.list_recent(limit=200)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "ts", "iso_ts", "trigger", "recipe_id",
            "iterations_run", "elapsed_s", "front_size",
            "best_candidate_id", "best_avg_score",
            "applied", "applied_at",
            "winner_lifecycle_state", "winner_proposal_id",
            "winner_canary_phase", "winner_rollback_reason",
            "best_rationale",
        ])
        from datetime import datetime

        from runtime.safety.recovery.gepa_runs import enrich_run_records
        for r in enrich_run_records(runs):
            w.writerow([
                f"{r['ts']:.3f}",
                datetime.fromtimestamp(r["ts"], tz=UTC).isoformat(),
                r["trigger"],
                r["recipe_id"] or "",
                r["iterations_run"],
                f"{r['elapsed_s']:.3f}",
                r["front_size"],
                r["best_candidate_id"] or "",
                f"{r['best_avg_score']:.4f}" if r["best_avg_score"] is not None else "",
                "1" if r["applied"] else "0",
                f"{r['applied_at']:.3f}" if r["applied_at"] else "",
                r["winner_lifecycle_state"] or "",
                r["winner_proposal_id"] or "",
                r["winner_canary_phase"] or "",
                r["winner_rollback_reason"] or "",
                # Quote-safe via csv writer · rationale can have
                # commas/quotes/newlines · the writer escapes them.
                r["best_rationale"] or "",
            ])
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                    f"attachment; filename=gepa_runs_{int(time.time())}.csv",
            },
        )

    @_reflex_admin.get("/api/evolution/gepa/addendums.csv")
    def _gepa_addendums_csv() -> Any:
        """Export the active addendum map as CSV · one row per
        scope. Lets ops snapshot the production state for
        change-management or off-system inventory."""
        import csv
        import io
        from datetime import datetime

        from runtime.safety.recovery.gepa_addendum_store import list_all
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "scope", "recipe_id", "path", "size_bytes",
            "mtime", "iso_mtime", "preview",
        ])
        for a in list_all():
            w.writerow([
                a["scope"],
                a["recipe_id"] or "",
                a["path"],
                a["size"],
                f"{a['mtime']:.3f}",
                datetime.fromtimestamp(
                    a["mtime"], tz=UTC,
                ).isoformat(),
                a["preview"],
            ])
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                    f"attachment; filename=gepa_addendums_{int(time.time())}.csv",
            },
        )

    @_reflex_admin.get("/api/evolution/gepa/addendums")
    def _gepa_addendums() -> dict:
        """List every active GEPA addendum · global + per-recipe.

        Lets the operator see at a glance: which recipes have a
        custom prompt addendum, when each was applied, what its
        content preview is. Backs the panel's "Addendums by
        recipe" sub-card.
        """
        from runtime.safety.recovery.gepa_addendum_store import list_all
        return {"addendums": list_all(), "source": "gepa"}

    @_reflex_admin.get("/api/evolution/gepa/recipes")
    def _gepa_recipes_with_manifests() -> dict:
        """List every recipe that has an active variant manifest ·
        powers the "all A/B experiments" view. One row per
        recipe; the operator drills into a specific recipe to
        see per-variant stats via /variants/<id>/stats.
        """
        from runtime.safety.recovery.gepa_variants import (
            list_all_manifests,
        )
        return {"recipes": list_all_manifests(), "source": "gepa"}

    @_reflex_admin.get("/api/evolution/gepa/variants/{recipe_id:path}/stats")
    def _gepa_variants_stats(recipe_id: str) -> dict:
        from dataclasses import asdict

        from runtime.safety.recovery.variant_evaluator import (
            collect_variant_stats,
        )
        comps = collect_variant_stats(
            stack.journal, base_recipe_id=recipe_id,
        )
        if not comps:
            return {"recipe_id": recipe_id, "variants": [],
                    "total_uses": 0, "source": "gepa"}
        cmp_ = comps[0]
        return {
            "recipe_id": cmp_.base_recipe_id,
            "total_uses": cmp_.total_uses,
            "variants": [
                {
                    **asdict(v),
                    "success_rate": v.success_rate,
                    "wilson_lower": v.wilson_lower,
                }
                for v in cmp_.variants
            ],
            "source": "gepa",
        }

    @_reflex_admin.post("/api/evolution/gepa/variants/{recipe_id:path}/auto-promote")
    def _gepa_variants_auto_promote(
        recipe_id: str,
        min_uses: int = 10,
        min_lead: float = 0.10,
        apply: bool = False,
    ) -> dict:
        """Compute a promote proposal · winner gets 10× weight,
        losers stay at 1 (kept alive at low traffic for
        continued evidence). With ``apply=true`` the proposal
        is auto-committed via ``set_weights`` · with
        ``apply=false`` (default) it's returned for the
        operator to review and apply manually."""
        from runtime.safety.recovery.gepa_variants import (
            list_variants,
            set_weights,
        )
        from runtime.safety.recovery.variant_evaluator import (
            collect_variant_stats,
            propose_weights,
        )
        comps = collect_variant_stats(
            stack.journal, base_recipe_id=recipe_id,
        )
        if not comps:
            # Treat "no data" as skipped (not an error) so the
            # panel renders it in the gentle gray-info style
            # rather than the red-error style.
            return {
                "ok": False,
                "skipped": True,
                "reason": (
                    f"no trajectories tagged with recipe {recipe_id} "
                    "yet · accumulate traffic first"
                ),
                "current_stats": [],
                "source": "gepa",
            }
        proposal = propose_weights(
            comps[0], min_uses=min_uses, min_lead=min_lead,
        )
        if proposal is None:
            return {
                "ok": False,
                "skipped": True,
                "reason": (
                    f"no winner yet (need ≥{min_uses} uses per variant "
                    f"and ≥{min_lead*100:.0f}pp Wilson-lower lead)"
                ),
                "current_stats": [
                    {
                        "variant_id": v.variant_id,
                        "uses": v.uses,
                        "success_rate": v.success_rate,
                        "wilson_lower": v.wilson_lower,
                    }
                    for v in comps[0].variants
                ],
                "source": "gepa",
            }
        result: dict = {
            "ok": True,
            "proposal": {
                "base_recipe_id": proposal.base_recipe_id,
                "winner_variant_id": proposal.winner_variant_id,
                "winner_lower_bound": proposal.winner_lower_bound,
                "runner_up_lower_bound": proposal.runner_up_lower_bound,
                "weights": proposal.weights,
                "rationale": proposal.rationale,
            },
            "applied": False,
            "source": "gepa",
        }
        if apply:
            m = set_weights(recipe_id, weights=proposal.weights)
            if m is not None:
                result["applied"] = True
                result["new_manifest"] = list_variants(recipe_id)
            else:
                result["apply_error"] = (
                    f"no manifest for {recipe_id} · cannot apply"
                )
        return result

    @_reflex_admin.get("/api/evolution/gepa/variants/{recipe_id:path}")
    def _gepa_variants_list(recipe_id: str) -> dict:
        """List all variants for a recipe + their weights +
        content previews. Returns ``manifest_present: false``
        when the recipe is in single-file mode (no manifest)."""
        from runtime.safety.recovery.gepa_variants import list_variants
        return {**list_variants(recipe_id), "source": "gepa"}

    @_reflex_admin.post("/api/evolution/gepa/variants/{recipe_id:path}/weights")
    def _gepa_variants_weights(
        recipe_id: str, body: dict,
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Bulk-update variant weights · operator's "shift more
        traffic to the winner" knob. Body shape::

            {
              "weights": {"vA": 10, "vB": 1},
              "default_weight": 0
            }

        ``weights`` may include only a subset of variants ·
        unlisted ones keep their current weight. Pass
        ``default_weight`` to also tune the control-group share.
        Returns the updated manifest summary."""
        from runtime.safety.gene_locks import MutationKind, record_mutation
        from runtime.safety.recovery.gepa_variants import (
            list_variants,
            set_weights,
        )
        # Gene-lock gate · weight changes are high-risk (live
        # traffic impact) so they go through the QUORUM soft-
        # advisory path + TEMPORAL (6h per recipe).
        _gate = _gate_forge_mutation(
            MutationKind.SET_VARIANT_WEIGHTS, target=recipe_id,
            approver=x_human_approver,
        )
        if not _gate.get("ok"):
            return _gate
        try:
            weights = body.get("weights") or {}
            if not isinstance(weights, dict):
                return {"ok": False, "error": "weights must be a dict", "source": "gepa"}
            # Normalise · drop non-int values defensively.
            norm = {
                str(k): max(0, int(v))
                for k, v in weights.items()
                if isinstance(v, (int, float))
            }
            dw_raw = body.get("default_weight")
            dw = (
                max(0, int(dw_raw))
                if isinstance(dw_raw, (int, float)) else None
            )
            m = set_weights(
                recipe_id, weights=norm, default_weight=dw,
            )
            if m is None:
                return {"ok": False,
                        "error": f"no manifest for recipe {recipe_id}",
                        "source": "gepa"}
            record_mutation(
                MutationKind.SET_VARIANT_WEIGHTS, recipe_id,
            )
            return {
                "ok": True, **list_variants(recipe_id),
                "gene_lock": {
                    "level": _gate.get("level"),
                    "warnings": _gate.get("warnings", []),
                },
                "source": "gepa",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "source": "gepa"}

    @_reflex_admin.delete(
        "/api/evolution/gepa/variants/{recipe_id:path}/{variant_id}",
    )
    def _gepa_variants_delete(
        recipe_id: str, variant_id: str,
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Drop a variant · removes its file + manifest entry.
        When the last variant of a recipe is removed AND
        default_weight is 0, the entire manifest file is
        dropped too · planner falls back to single-file mode."""
        from runtime.safety.gene_locks import MutationKind, record_mutation
        from runtime.safety.recovery.gepa_variants import remove_variant
        _gate = _gate_forge_mutation(
            MutationKind.DELETE_ADDENDUM, target=recipe_id,
            approver=x_human_approver,
        )
        if not _gate.get("ok"):
            return _gate
        removed = remove_variant(recipe_id, variant_id)
        record_mutation(MutationKind.DELETE_ADDENDUM, recipe_id)
        return {"ok": True, "removed": removed,
                "recipe_id": recipe_id, "variant_id": variant_id,
                "gene_lock": {"warnings": _gate.get("warnings", [])},
                "source": "gepa"}

    @_reflex_admin.delete("/api/evolution/gepa/addendums/{recipe_id}")
    def _gepa_addendum_delete(
        recipe_id: str,
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Drop a per-recipe addendum · operator's "rollback" knob.

        ``recipe_id="__global__"`` removes the legacy global file
        instead. Returns ok=True even when the file didn't exist
        so the panel's delete button is idempotent.
        """
        from runtime.safety.gene_locks import MutationKind, record_mutation
        _gate = _gate_forge_mutation(
            MutationKind.DELETE_ADDENDUM, target=recipe_id,
            approver=x_human_approver,
        )
        if not _gate.get("ok"):
            return _gate
        try:
            from runtime.safety.recovery.gepa_addendum_store import (
                delete_for_recipe,
                legacy_global_path,
            )
            if recipe_id == "__global__":
                p = legacy_global_path()
                if p.is_file():
                    p.unlink()
                    record_mutation(MutationKind.DELETE_ADDENDUM, recipe_id)
                    return {"ok": True, "deleted": True, "scope": "global", "source": "gepa"}
                return {"ok": True, "deleted": False, "scope": "global", "source": "gepa"}
            deleted = delete_for_recipe(recipe_id)
            record_mutation(MutationKind.DELETE_ADDENDUM, recipe_id)
            return {"ok": True, "deleted": deleted,
                    "scope": "per_recipe", "recipe_id": recipe_id,
                    "gene_lock": {"warnings": _gate.get("warnings", [])},
                    "source": "gepa"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "source": "gepa"}

    @_reflex_admin.get("/api/evolution/gepa/runs")
    def _gepa_runs(limit: int = 20) -> dict:
        """List recent GEPA runs (manual + auto), newest first.
        Each entry includes the trigger, the best candidate's
        id+score+rationale, and whether it's been applied."""
        from runtime.safety.recovery.gepa_runs import (
            enrich_run_records,
            get_default_store,
        )
        store = get_default_store()
        runs = store.list_recent(limit=limit)
        return {
            "runs": enrich_run_records(runs),
            "source": "gepa",
        }

    # ─── RecipeForge auto-promote scheduler ───────────────
    # The daemon side of auto-promote · runs on an interval
    # and reshuffles variant weights based on accumulated
    # trajectory data, with no human in the loop. Off by
    # default; opt in via the enable endpoint or the panel
    # toggle. See forge_auto_tick.py for safety rules.
    try:
        from runtime.safety.recovery import forge_auto_tick
        forge_auto_tick.bind_stack(stack)
        # Boot-time opt-in · the OCTOPUS_FORGE_AUTO_PROMOTE_
        # INTERVAL_HOURS env var is the "I want this running
        # from every uvicorn restart" switch. Unset → scheduler
        # stays off, operator can still toggle at runtime.
        import os as _os
        _boot_iv = _os.environ.get("OCTOPUS_FORGE_AUTO_PROMOTE_INTERVAL_HOURS")
        if _boot_iv:
            with contextlib.suppress(TypeError, ValueError):
                forge_auto_tick.enable(interval_hours=float(_boot_iv))
    except (ImportError, OSError, TypeError, AttributeError):  # noqa: BLE001
        pass

    @_reflex_admin.get("/api/evolution/gepa/auto-tick/status")
    def _gepa_auto_tick_status() -> dict:
        from runtime.safety.recovery import forge_auto_tick
        return {**forge_auto_tick.get_status(), "source": "gepa"}

    @_reflex_admin.post("/api/evolution/gepa/auto-tick/enable")
    def _gepa_auto_tick_enable(
        interval_hours: float = 24.0,
        min_uses: int = 20,
        min_lead: float = 0.15,
        x_human_approver: str | None = _Header(None, alias="X-Human-Approver"),
    ) -> dict:
        """Start the scheduler · idempotent (call again to tune
        the interval without a restart).

        MONOTONIC enforcement · safety thresholds can only be
        autonomously tightened (min_uses up, min_lead up,
        interval_hours up = less frequent = safer). Loosening
        any of them requires an ``X-Human-Approver`` header
        (prod mode) or emits a warning (dev mode).
        """
        from runtime.safety.gene_locks import LockViolation, check_monotonic
        from runtime.safety.recovery import forge_auto_tick
        # Read current thresholds to compute direction.
        status = forge_auto_tick.get_status()
        current_interval = status.get("interval_hours", 24.0)
        current_min_uses = status.get("min_uses", 20)
        current_min_lead = status.get("min_lead", 0.15)
        mono_warnings: list[str] = []
        try:
            for path, old, new in [
                ("auto_tick.interval_hours", current_interval, interval_hours),
                ("auto_tick.min_uses", current_min_uses, min_uses),
                ("auto_tick.min_lead", current_min_lead, min_lead),
            ]:
                r = check_monotonic(
                    field_path=path, old_value=old, new_value=new,
                    approver=x_human_approver,
                )
                mono_warnings.extend(r.get("warnings", []))
        except LockViolation as lv:
            return lv.as_dict()
        result = forge_auto_tick.enable(
            interval_hours=interval_hours,
            min_uses=min_uses,
            min_lead=min_lead,
        )
        if mono_warnings:
            result["gene_lock_warnings"] = mono_warnings
        result["source"] = "gepa"
        return result

    @_reflex_admin.post("/api/evolution/gepa/auto-tick/disable")
    def _gepa_auto_tick_disable() -> dict:
        """Signal the scheduler to stop. Returns immediately ·
        thread exits on its next stop-event check (≤ 5 s)."""
        from runtime.safety.recovery import forge_auto_tick
        return {**forge_auto_tick.disable(), "source": "gepa"}

    @_reflex_admin.post("/api/evolution/gepa/auto-tick/run-now")
    def _gepa_auto_tick_now(
        apply: bool = True,
        min_uses: int = 20,
        min_lead: float = 0.15,
    ) -> dict:
        """Force one tick right now · for testing / on-demand
        "apply every pending proposal" from the panel. Runs
        synchronously so the endpoint returns the result
        directly · careful, this could be slow on a deployment
        with many recipes."""
        from dataclasses import asdict

        from runtime.safety.recovery import forge_auto_tick
        tr = forge_auto_tick.run_tick(
            apply=apply, min_uses=min_uses, min_lead=min_lead,
        )
        return {**asdict(tr), "apply": apply, "source": "gepa"}

    @_reflex_admin.post("/api/evolution/gepa/auto-propose")
    def _gepa_auto_propose(
        n_iter: int = 6,
        eval_tasks: int = 4,
        max_recipes: int = 3,
        judge_model: str = "claude-sonnet-4-6",
        mutator_model: str = "claude-sonnet-4-6",
    ) -> dict:
        """One-click "look for losing recipes, propose GEPA fixes
        for each". Result records land in the run store · the
        operator opens /workspace/reflex and reviews the
        suggestions in the GEPA panel's history section.

        Doesn't auto-apply any winner · same conservative
        policy as the manual run endpoint.
        """
        try:
            from runtime.core.cerebrum.llm_planner import (
                _load_planner_prompt,
            )
            from runtime.safety.recovery.gepa_bridge import (
                propose_for_losing_recipes,
            )
            seed = _load_planner_prompt()
            router = getattr(stack.planner, "router", None)
            if router is None:
                return {"ok": False, "error": "planner.router missing"}
            results = propose_for_losing_recipes(
                journal=stack.journal,
                router=router,
                seed_prompt=seed,
                judge_model=judge_model,
                mutator_model=mutator_model,
                n_iter=n_iter,
                eval_tasks=eval_tasks,
                max_recipes=max_recipes,
            )
            ok_count = sum(1 for r in results if r.get("ok"))
            return {
                "ok": True,
                "proposals_generated": ok_count,
                "results": results,
                "source": "gepa",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "source": "gepa"}

    @_reflex_admin.get("/api/evolution/gepa/applied")
    def _gepa_applied() -> dict:
        """Read back the currently-applied GEPA addendum (if any)
        so the operator can see what's live without grepping
        the data dir."""
        from runtime.safety.recovery.gepa_addendum_store import (
            legacy_global_path,
        )

        target = legacy_global_path()
        if not target.is_file():
            return {
                "applied": False,
                "path": str(target),
                "size": 0,
                "mtime": None,
                "content_preview": "",
                "source": "gepa",
            }
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return {"applied": False, "error": str(exc), "source": "gepa"}
        return {
            "applied": True,
            "path": str(target),
            "size": len(content),
            "mtime": target.stat().st_mtime,
            "content_preview": content[:600],
            "source": "gepa",
        }

    @_reflex_admin.post("/api/reflex/tiers/fuzzy-cache/clear")
    def _reflex_tiers_fuzzy_clear() -> dict:
        """Drop all entries from the fuzzy cache · use after
        changing rules to make sure the cache doesn't keep
        serving the now-superseded LLM reply."""
        from runtime.core.nerves.reflex.tiers import get_default_fuzzy_cache
        fc = get_default_fuzzy_cache()
        n = len(fc._store)  # noqa: SLF001 (deliberate access)
        fc._store.clear()  # noqa: SLF001
        fc.hits = 0
        fc.misses = 0
        return {"ok": True, "dropped": n}

    @_reflex_admin.get("/admin/reflex", response_class=HTMLResponse)
    def _reflex_panel() -> str:
        """Self-contained HTML monitoring panel · no React, no
        build step. Polls /api/reflex/stats and /api/reflex/rules
        every 2 s. Useful for ops who want to watch hit rates
        during a rule iteration session without setting up the
        full frontend dev environment."""
        return _REFLEX_PANEL_HTML

    @_reflex_admin.get("/api/reflex/rules-yaml")
    def _reflex_rules_yaml_get() -> dict:
        """Return the raw YAML rules file as a string · feeds
        the in-browser editor at /admin/reflex/edit. Returns
        the file mtime too so the editor can warn the operator
        if someone else edited the file in between."""
        from runtime.core.nerves.reflex.rules_loader import find_default_rules_file
        path = find_default_rules_file()
        if path is None or not path.is_file():
            return {"ok": False, "error": "no rules file"}
        try:
            content = path.read_text(encoding="utf-8")
            return {
                "ok": True,
                "path": str(path),
                "content": content,
                "mtime": path.stat().st_mtime,
                "size": len(content),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @_reflex_admin.post("/api/reflex/rules-yaml")
    def _reflex_rules_yaml_put(body: dict) -> dict:
        """Persist new YAML content · validates by attempting to
        parse with the loader BEFORE writing to disk · invalid
        YAML returns the parse error, file untouched.

        Body shape: ``{"content": "<full file>", "expected_mtime":
        <float>, "reload": true}``. ``expected_mtime`` is checked
        against the on-disk mtime to prevent lost-update races
        between two browser tabs · pass 0 to bypass.

        ``reload=true`` (default) hot-reloads after save so the
        change is live immediately.
        """
        from runtime.core.nerves.reflex.rules_loader import (
            find_default_rules_file,
            load_rules_from_file,
        )
        content = body.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "missing content"}
        path = find_default_rules_file()
        if path is None:
            return {"ok": False, "error": "no rules file"}
        # Optimistic concurrency · refuse to overwrite a file
        # that's been edited under us.
        expected = body.get("expected_mtime") or 0
        try:
            actual = path.stat().st_mtime
            if expected and abs(actual - float(expected)) > 0.5:
                return {
                    "ok": False,
                    "error": "file was modified externally · reload first",
                    "actual_mtime": actual,
                    "expected_mtime": expected,
                }
        except OSError:  # noqa: BLE001 — temp file cleanup; best-effort
            pass
        # Pre-validate · the loader is permissive (returns [] on
        # parse error so the running router can survive a bad
        # file), but for an interactive editor we want STRICT
        # validation: any YAML parse error rejects the save so
        # the file on disk stays valid. We call the YAML parser
        # directly instead of going through the loader.
        try:
            if path.suffix.lower() in (".yaml", ".yml"):
                import yaml as _yaml  # type: ignore[import]
                parsed = _yaml.safe_load(content)
            else:
                parsed = json.loads(content)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"YAML parse failed: {exc}",
            }
        # Soft schema check · rules must be a list under "rules"
        # OR the whole document is a list. Anything else is
        # almost certainly an editor mistake.
        rules_list = parsed.get("rules") if isinstance(parsed, dict) else parsed
        if not isinstance(rules_list, list):
            return {
                "ok": False,
                "error": "expected a 'rules:' list at top level "
                         "(or a top-level list)",
            }
        # Now parse via the loader to get the rule count for
        # the response. Failures here surface as 0 rules in
        # the file; the caller can still see what landed.
        tmp = path.with_name(path.stem + ".reflex_pending" + path.suffix)
        try:
            tmp.write_text(content, encoding="utf-8")
            try:
                rules = load_rules_from_file(tmp)
            except Exception as exc:  # noqa: BLE001
                tmp.unlink(missing_ok=True)
                return {
                    "ok": False,
                    "error": f"loader rejected: {exc}",
                }
            tmp.replace(path)
        except Exception as exc:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            return {"ok": False, "error": f"write failed: {exc}"}

        result = {
            "ok": True,
            "rules_in_file": len(rules),
            "new_mtime": path.stat().st_mtime,
        }
        # Live-reload by default · the editor is for active
        # iteration so "save" should mean "apply".
        if body.get("reload", True):
            try:
                from runtime.cli import _build_reflex_router
                fresh = _build_reflex_router()
                count = _reflex_router.replace_reflexes(fresh._reflexes)
                result["reloaded"] = True
                result["rules_loaded"] = count
            except Exception as exc:  # noqa: BLE001
                result["reloaded"] = False
                result["reload_error"] = f"{type(exc).__name__}: {exc}"
        return result

    # ─── Card-mode endpoints ─────────────────────────────────
    # The YAML editor is the power-user surface · for the 90%
    # case (greeting / canned-Q&A / smart-home one-liner) we
    # expose a simplified card shape that hides regex anchors,
    # numeric priorities, and unused fields. Rules that contain
    # advanced features (`variants`, `per_actor`, `enabled_when`,
    # `action`, custom matcher types) are returned with
    # ``advanced: true`` and the card UI must surface them as
    # read-only · the YAML mode is the escape hatch for those.
    @_reflex_admin.get("/api/reflex/rules-cards")
    def _reflex_rules_cards_get() -> dict:
        from runtime.core.nerves.reflex.rules_loader import find_default_rules_file
        path = find_default_rules_file()
        if path is None or not path.is_file():
            return {"ok": False, "error": "no rules file"}
        try:
            from ruamel.yaml import YAML  # type: ignore[import]
            yaml = YAML(typ="rt")
            yaml.preserve_quotes = True
            with path.open("r", encoding="utf-8") as fh:
                doc = yaml.load(fh)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"YAML parse failed: {exc}"}

        raw_rules = doc.get("rules") if isinstance(doc, dict) else doc
        if not isinstance(raw_rules, list):
            return {"ok": False, "error": "missing 'rules:' list"}

        cards = []
        for r in raw_rules:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("id") or "")
            rtype = str(r.get("type") or "regex")
            pattern = r.get("pattern") or ""
            reply = r.get("reply") or ""
            reply_on_failure = r.get("reply_on_action_failure") or ""
            delegate = r.get("delegate_to_workflow") or ""
            prio = int(r.get("priority") or 20)
            # Card-incompatible features · these route-block from
            # the simplified UI and force YAML mode.
            non_action_advanced = {
                "variants", "per_actor", "enabled_when",
            }
            has_advanced = bool(non_action_advanced & set(r.keys())) or rtype != "regex"
            # Action handling · expose webhook XOR mqtt in the card.
            # exec or multi-action (webhook+mqtt together) is too
            # power-user for cards · stays advanced.
            action_card: dict = {"mode": "none"}
            action_block = r.get("action") if isinstance(r.get("action"), dict) else None
            if action_block:
                has_wh = isinstance(action_block.get("webhook"), dict)
                has_mq = isinstance(action_block.get("mqtt"), dict)
                has_ex = isinstance(action_block.get("exec"), dict)
                if has_ex or (has_wh and has_mq):
                    has_advanced = True
                elif has_wh:
                    wh = action_block["webhook"]
                    action_card = {
                        "mode": "webhook",
                        "webhook": {
                            "url": str(wh.get("url") or ""),
                            "method": str(wh.get("method") or "POST").upper(),
                            "headers": dict(wh.get("headers") or {}),
                            "body": wh.get("body") if wh.get("body") is not None else None,
                            "timeout_ms": int(wh.get("timeout_ms") or 1000),
                        },
                    }
                elif has_mq:
                    mq = action_block["mqtt"]
                    action_card = {
                        "mode": "mqtt",
                        "mqtt": {
                            "broker": str(mq.get("broker") or ""),
                            "port": int(mq.get("port") or 1883),
                            "topic": str(mq.get("topic") or ""),
                            "payload": str(mq.get("payload") or ""),
                            "qos": int(mq.get("qos") or 0),
                            "retain": bool(mq.get("retain")),
                        },
                    }
            # Trigger inference: ^literal$ without regex meta → exact;
            # bare literal without anchors and no meta → contains.
            trigger_mode = "regex"
            trigger_text = str(pattern)
            meta_chars = set(r"\.^$*+?()[]{}|")
            if isinstance(pattern, str) and not has_advanced:
                body_pat = pattern
                is_anchored = body_pat.startswith("^") and body_pat.endswith("$")
                inner = body_pat[1:-1] if is_anchored else body_pat
                has_meta = any(c in meta_chars for c in inner)
                if is_anchored and not has_meta:
                    trigger_mode = "exact"
                    trigger_text = inner
                elif not is_anchored and not has_meta and "\n" not in inner:
                    trigger_mode = "contains"
                    trigger_text = inner
            # Priority bucket · low=10, medium=20, high=30+
            if prio < 15:
                prio_band = "low"
            elif prio < 25:
                prio_band = "medium"
            else:
                prio_band = "high"
            cards.append({
                "id": rid,
                "trigger_mode": trigger_mode,
                "trigger_text": trigger_text,
                "reply": str(reply),
                "reply_on_failure": str(reply_on_failure),
                "reply_source": "workflow" if str(delegate).strip() else "text",
                "delegate_to_workflow": str(delegate),
                "priority": prio_band,
                "priority_raw": prio,
                "action": action_card,
                "advanced": has_advanced,
            })
        return {
            "ok": True,
            "path": str(path),
            "mtime": path.stat().st_mtime,
            "cards": cards,
        }

    @_reflex_admin.post("/api/reflex/rules-cards")
    def _reflex_rules_cards_put(body: dict) -> dict:
        """Patch the YAML file using ruamel · only the basic fields
        (pattern / reply / priority) of non-advanced rules are
        updated · new cards append · advanced rules are
        untouchable through this endpoint by design.

        Body shape::

            {
              "expected_mtime": <float>,
              "reload": true,
              "upserts": [{id, trigger_mode, trigger_text, reply, priority}],
              "deletes": ["id1", "id2"]
            }
        """
        from runtime.core.nerves.reflex.rules_loader import (
            find_default_rules_file,
            load_rules_from_file,
        )
        path = find_default_rules_file()
        if path is None:
            return {"ok": False, "error": "no rules file"}
        expected = body.get("expected_mtime") or 0
        try:
            actual = path.stat().st_mtime
            if expected and abs(actual - float(expected)) > 0.5:
                return {
                    "ok": False,
                    "error": "file was modified externally · reload first",
                    "actual_mtime": actual,
                    "expected_mtime": expected,
                }
        except OSError:  # noqa: BLE001 — temp file cleanup; best-effort
            pass

        try:
            from ruamel.yaml import YAML  # type: ignore[import]
            from ruamel.yaml.comments import CommentedMap, CommentedSeq  # type: ignore[import]
            yaml = YAML(typ="rt")
            yaml.preserve_quotes = True
            yaml.width = 120
            yaml.indent(mapping=2, sequence=4, offset=2)
            with path.open("r", encoding="utf-8") as fh:
                doc = yaml.load(fh)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"YAML load failed: {exc}"}

        if not isinstance(doc, dict):
            doc = CommentedMap()
        rules_seq = doc.get("rules")
        if not isinstance(rules_seq, list):
            rules_seq = CommentedSeq()
            doc["rules"] = rules_seq

        prio_map = {"low": 10, "medium": 20, "high": 30}

        def _to_pattern(mode: str, text: str) -> str:
            import re as _re
            t = text or ""
            if mode == "exact":
                return f"^{_re.escape(t)}$"
            if mode == "contains":
                return _re.escape(t)
            return t

        upserts = body.get("upserts") or []
        deletes = set(body.get("deletes") or [])

        # Apply deletes — only on non-advanced rules.
        non_action_advanced = {"variants", "per_actor", "enabled_when"}

        def _is_advanced(rule: dict) -> bool:
            if rule.get("type") not in (None, "regex"):
                return True
            if non_action_advanced & set(rule.keys()):
                return True
            act = rule.get("action") if isinstance(rule.get("action"), dict) else None
            if act:
                has_wh = isinstance(act.get("webhook"), dict)
                has_mq = isinstance(act.get("mqtt"), dict)
                has_ex = isinstance(act.get("exec"), dict)
                if has_ex or (has_wh and has_mq):
                    return True
            return False

        kept: list = []
        for r in rules_seq:
            rid = r.get("id") if isinstance(r, dict) else None
            if rid in deletes and isinstance(r, dict) and not _is_advanced(r):
                continue
            kept.append(r)
        rules_seq[:] = kept

        # Apply upserts.
        existing_by_id = {
            r.get("id"): i for i, r in enumerate(rules_seq) if isinstance(r, dict)
        }

        def _build_action_block(action_in: dict | None) -> CommentedMap | None:
            if not isinstance(action_in, dict):
                return None
            mode = str(action_in.get("mode") or "none")
            if mode == "webhook":
                wh = action_in.get("webhook") or {}
                if not str(wh.get("url") or "").strip():
                    return None
                block = CommentedMap()
                sub = CommentedMap()
                sub["url"] = str(wh.get("url") or "")
                sub["method"] = str(wh.get("method") or "POST").upper()
                headers = wh.get("headers") or {}
                if isinstance(headers, dict) and headers:
                    sub["headers"] = CommentedMap(
                        (str(k), str(v)) for k, v in headers.items()
                    )
                body_val = wh.get("body")
                if body_val not in (None, "", {}):
                    sub["body"] = body_val
                timeout = int(wh.get("timeout_ms") or 0)
                if timeout > 0:
                    sub["timeout_ms"] = timeout
                block["webhook"] = sub
                return block
            if mode == "mqtt":
                mq = action_in.get("mqtt") or {}
                if not str(mq.get("broker") or "").strip() or not str(mq.get("topic") or "").strip():
                    return None
                block = CommentedMap()
                sub = CommentedMap()
                sub["broker"] = str(mq.get("broker") or "")
                sub["port"] = int(mq.get("port") or 1883)
                sub["topic"] = str(mq.get("topic") or "")
                sub["payload"] = str(mq.get("payload") or "")
                sub["qos"] = int(mq.get("qos") or 0)
                if mq.get("retain"):
                    sub["retain"] = True
                block["mqtt"] = sub
                return block
            return None

        for u in upserts:
            if not isinstance(u, dict):
                continue
            uid = str(u.get("id") or "").strip()
            if not uid:
                continue
            mode = str(u.get("trigger_mode") or "regex")
            text = str(u.get("trigger_text") or "")
            reply_text = str(u.get("reply") or "")
            reply_on_failure = str(u.get("reply_on_failure") or "").strip()
            reply_source = str(u.get("reply_source") or "text")
            delegate_wf = str(u.get("delegate_to_workflow") or "").strip()
            prio = prio_map.get(str(u.get("priority") or "medium"), 20)
            pattern = _to_pattern(mode, text)
            action_block = _build_action_block(u.get("action"))
            use_workflow = reply_source == "workflow" and bool(delegate_wf)
            if uid in existing_by_id:
                rule = rules_seq[existing_by_id[uid]]
                if isinstance(rule, dict) and not _is_advanced(rule):
                    rule["pattern"] = pattern
                    rule["reply"] = reply_text
                    rule["priority"] = prio
                    if reply_on_failure:
                        rule["reply_on_action_failure"] = reply_on_failure
                    else:
                        rule.pop("reply_on_action_failure", None)
                    if use_workflow:
                        rule["delegate_to_workflow"] = delegate_wf
                    else:
                        rule.pop("delegate_to_workflow", None)
                    if action_block is not None:
                        rule["action"] = action_block
                    else:
                        rule.pop("action", None)
            else:
                new_rule = CommentedMap()
                new_rule["id"] = uid
                new_rule["type"] = "regex"
                new_rule["pattern"] = pattern
                new_rule["reply"] = reply_text
                new_rule["priority"] = prio
                if reply_on_failure:
                    new_rule["reply_on_action_failure"] = reply_on_failure
                if use_workflow:
                    new_rule["delegate_to_workflow"] = delegate_wf
                if action_block is not None:
                    new_rule["action"] = action_block
                rules_seq.append(new_rule)

        # Serialize and re-validate before overwriting on disk.
        import io as _io
        buf = _io.StringIO()
        try:
            yaml.dump(doc, buf)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"YAML dump failed: {exc}"}
        new_content = buf.getvalue()

        tmp = path.with_name(path.stem + ".reflex_pending" + path.suffix)
        try:
            tmp.write_text(new_content, encoding="utf-8")
            try:
                rules_loaded = load_rules_from_file(tmp)
            except Exception as exc:  # noqa: BLE001
                tmp.unlink(missing_ok=True)
                return {"ok": False, "error": f"loader rejected: {exc}"}
            tmp.replace(path)
        except Exception as exc:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            return {"ok": False, "error": f"write failed: {exc}"}

        result = {
            "ok": True,
            "rules_in_file": len(rules_loaded),
            "new_mtime": path.stat().st_mtime,
        }
        if body.get("reload", True):
            try:
                from runtime.cli import _build_reflex_router
                fresh = _build_reflex_router()
                count = _reflex_router.replace_reflexes(fresh._reflexes)
                result["reloaded"] = True
                result["rules_loaded"] = count
            except Exception as exc:  # noqa: BLE001
                result["reloaded"] = False
                result["reload_error"] = f"{type(exc).__name__}: {exc}"
        return result

    @_reflex_admin.get("/admin/reflex/edit", response_class=HTMLResponse)
    def _reflex_editor() -> str:
        """Self-contained YAML editor · loads via /api/reflex/rules-yaml,
        saves back through the same endpoint with optimistic-lock
        mtime checks, runs /api/reflex/test pre-save."""
        return _REFLEX_EDITOR_HTML

    # ─── RecipeForge route aliases ────────────────────────────
    # The in-house prompt-evolution subsystem is branded
    # ``RecipeForge`` (parallels the existing ``SkillForge``
    # reflection path in the biomimetic naming scheme). The
    # original ``/api/evolution/gepa/...`` paths are kept as
    # aliases so existing clients / docs / scripts don't break.
    #
    # For reference: the algorithm family is Pareto-front
    # prompt evolution with LLM-driven reflective mutation ·
    # conceptually similar to the approaches discussed in
    # arxiv 2507.19457 · the implementation is in-house and
    # extended with multi-variant routing, sticky-per-conv
    # selection, and Wilson-lower-bound auto-promote which
    # are not part of the upstream research.
    _forge_aliases = [
        ("GET",  "/api/evolution/gepa/recipes",
         "/api/evolution/forge/recipes", _gepa_recipes_with_manifests),
        ("GET",  "/api/evolution/gepa/auto-tick/status",
         "/api/evolution/forge/auto-tick/status",
         _gepa_auto_tick_status),
        ("POST", "/api/evolution/gepa/auto-tick/enable",
         "/api/evolution/forge/auto-tick/enable",
         _gepa_auto_tick_enable),
        ("POST", "/api/evolution/gepa/auto-tick/disable",
         "/api/evolution/forge/auto-tick/disable",
         _gepa_auto_tick_disable),
        ("POST", "/api/evolution/gepa/auto-tick/run-now",
         "/api/evolution/forge/auto-tick/run-now",
         _gepa_auto_tick_now),
        ("POST", "/api/evolution/gepa/run",
         "/api/evolution/forge/run", _gepa_run),
        ("POST", "/api/evolution/gepa/apply",
         "/api/evolution/forge/apply", _gepa_apply),
        ("GET",  "/api/evolution/gepa/runs",
         "/api/evolution/forge/runs", _gepa_runs),
        ("GET",  "/api/evolution/gepa/runs.csv",
         "/api/evolution/forge/runs.csv", _gepa_runs_csv),
        ("GET",  "/api/evolution/gepa/addendums",
         "/api/evolution/forge/addendums", _gepa_addendums),
        ("GET",  "/api/evolution/gepa/addendums.csv",
         "/api/evolution/forge/addendums.csv", _gepa_addendums_csv),
        ("GET",  "/api/evolution/gepa/applied",
         "/api/evolution/forge/applied", _gepa_applied),
        ("POST", "/api/evolution/gepa/auto-propose",
         "/api/evolution/forge/auto-propose", _gepa_auto_propose),
        ("GET",  "/api/evolution/gepa/variants/{recipe_id:path}/stats",
         "/api/evolution/forge/variants/{recipe_id:path}/stats",
         _gepa_variants_stats),
        ("POST", "/api/evolution/gepa/variants/{recipe_id:path}/auto-promote",
         "/api/evolution/forge/variants/{recipe_id:path}/auto-promote",
         _gepa_variants_auto_promote),
        ("GET",  "/api/evolution/gepa/variants/{recipe_id:path}",
         "/api/evolution/forge/variants/{recipe_id:path}",
         _gepa_variants_list),
        ("POST", "/api/evolution/gepa/variants/{recipe_id:path}/weights",
         "/api/evolution/forge/variants/{recipe_id:path}/weights",
         _gepa_variants_weights),
        ("DELETE", "/api/evolution/gepa/variants/{recipe_id:path}/{variant_id}",
         "/api/evolution/forge/variants/{recipe_id:path}/{variant_id}",
         _gepa_variants_delete),
        ("DELETE", "/api/evolution/gepa/addendums/{recipe_id}",
         "/api/evolution/forge/addendums/{recipe_id}",
         _gepa_addendum_delete),
    ]
    for _method, _old, _new, _fn in _forge_aliases:
        _reflex_admin.add_api_route(
            _new, _fn, methods=[_method],
            include_in_schema=True,
        )
        # Hide the legacy ``gepa`` paths from the OpenAPI spec
        # so public docs / SDKs see only the product name.
        # Still resolvable by any existing client that
        # hardcoded them. Iterate over the router's routes
        # and flip include_in_schema on the matching path.
        for _r in _reflex_admin.routes:
            if (
                getattr(_r, "path", None) == _old
                and _method in getattr(_r, "methods", set())
            ):
                _r.include_in_schema = False
                break

    app.include_router(_reflex_admin)

