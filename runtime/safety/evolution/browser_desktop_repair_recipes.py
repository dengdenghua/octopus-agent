from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.process.paths import app_paths
from runtime.safety.replay.browser_pixel_assertions import (
    assert_screenshot_pixels,
    compare_screenshot_pixels,
)

SCHEMA = "octopus.browser_desktop_repair_recipes.v1"
RECIPE_SCHEMA = "octopus.browser_desktop_repair_recipe.v1"
QUEUE_SCHEMA = "octopus.browser_desktop_repair_recipe_queue.v1"
VERIFICATION_SCHEMA = "octopus.browser_desktop_repair_recipe_verifications.v1"
EVIDENCE_SCHEMA = "octopus.browser_desktop_repair_recipe_evidence.v1"
STALE_REJECTION_SCHEMA = "octopus.browser_desktop_stale_replay_artifact_rejection.v1"
QUALITY_GATE_SCHEMA = "octopus.browser_desktop_repair_recipe_quality_gate.v1"
FAILURE_TAXONOMY_SCHEMA = "octopus.browser_desktop_failure_taxonomy.v1"
REPAIR_ROUTE_SCHEMA = "octopus.browser_desktop_repair_route.v1"
AUTOMATION_PLAYBOOK_SCHEMA = "octopus.browser_desktop_automation_playbook.v1"


def compute_browser_desktop_repair_recipes(
    *,
    review_queue_path: str | Path | None = None,
    limit: int = 1000,
    min_occurrences: int = 1,
) -> dict[str, Any]:
    queue = ReviewQueue(
        Path(review_queue_path)
        if review_queue_path is not None
        else app_paths().review_queue_path,
    )
    rows = queue.items(
        status="pending",
        target_bucket="browser_desktop_replay",
        limit=max(1, int(limit)),
    )["items"]
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _cluster_key(row)
        clusters.setdefault(key, []).append(row)

    recipes = [
        _recipe_from_cluster(key, items)
        for key, items in clusters.items()
        if len(items) >= max(1, int(min_occurrences))
    ]
    recipes = sorted(
        recipes,
        key=lambda item: (
            _priority_rank(str(item.get("priority") or "P2")),
            -int(item.get("occurrences") or 0),
            str(item.get("cluster_key") or ""),
        ),
    )
    return {
        "schema": SCHEMA,
        "total_pending_cases": len(rows),
        "recipe_count": len(recipes),
        "recipes": recipes,
        "quality_gate": _quality_gate_from_recipes(recipes, pending_count=len(rows)),
        "ready": len(rows) == 0,
        "next_actions": _next_actions(recipes, len(rows)),
    }


def compute_browser_desktop_repair_recipe_quality_gate(
    *,
    review_queue_path: str | Path | None = None,
    limit: int = 1000,
    min_occurrences: int = 1,
) -> dict[str, Any]:
    report = compute_browser_desktop_repair_recipes(
        review_queue_path=review_queue_path,
        limit=limit,
        min_occurrences=min_occurrences,
    )
    recipes = [
        row for row in report.get("recipes") or []
        if isinstance(row, dict)
    ]
    return _quality_gate_from_recipes(
        recipes,
        pending_count=int(report.get("total_pending_cases") or 0),
    )


def queue_browser_desktop_repair_recipes(
    *,
    review_queue_path: str | Path | None = None,
    limit: int = 1000,
    min_occurrences: int = 1,
) -> dict[str, Any]:
    report = compute_browser_desktop_repair_recipes(
        review_queue_path=review_queue_path,
        limit=limit,
        min_occurrences=min_occurrences,
    )
    recipes = [
        row for row in report.get("recipes") or []
        if isinstance(row, dict)
    ]
    queue = ReviewQueue(
        Path(review_queue_path)
        if review_queue_path is not None
        else app_paths().review_queue_path,
    )
    created = 0
    updated = 0
    items: list[dict[str, Any]] = []
    for recipe in recipes:
        result = queue.upsert_item(
            source="browser_desktop_repair_recipe",
            source_kind="browser_desktop_repair_recipe",
            candidate_kind=_candidate_kind(recipe),
            priority=str(recipe.get("priority") or "P1"),
            target_bucket="browser_desktop_repair_recipe",
            title=str(recipe.get("title") or "Browser/Desktop repair recipe"),
            text=_recipe_text(recipe),
            metadata={
                "schema": RECIPE_SCHEMA,
                "recipe": recipe,
                "source_report": {
                    "schema": SCHEMA,
                    "total_pending_cases": report.get("total_pending_cases", 0),
                    "recipe_count": report.get("recipe_count", 0),
                },
            },
            tags=[
                "browser",
                "desktop",
                "repair_recipe",
                "replay_case",
                str(recipe.get("candidate_kind") or "unknown"),
            ],
        )
        created += int(result.get("created") or 0)
        updated += int(result.get("updated") or 0)
        items.extend(result.get("items") or [])
    return {
        "schema": QUEUE_SCHEMA,
        "created": created,
        "updated": updated,
        "recipes": recipes,
        "items": items,
        "summary": {
            "total_pending_cases": report.get("total_pending_cases", 0),
            "recipe_count": len(recipes),
        },
    }


def reject_stale_browser_desktop_replay_artifacts(
    *,
    review_queue_path: str | Path | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    queue = ReviewQueue(
        Path(review_queue_path)
        if review_queue_path is not None
        else app_paths().review_queue_path,
    )
    rows = queue.items(
        status="pending",
        target_bucket="browser_desktop_replay",
        limit=max(1, int(limit)),
    )["items"]
    rejected: list[dict[str, Any]] = []
    archived_recipes: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        kind = str(row.get("candidate_kind") or "")
        metadata = _dict(row.get("metadata"))
        if kind == "browser_pixel_replay_gate_case":
            stale = _stale_source_artifact(metadata)
        elif kind == "computer_activity_replay_case":
            stale = _stale_computer_activity_replay(metadata)
        else:
            stale = ""
        if not stale:
            skipped += 1
            continue
        item_id = str(row.get("id") or "")
        if not item_id:
            skipped += 1
            continue
        result = queue.decide(
            item_id,
            action="rejected",
            reason=(
                "Rejected stale browser/desktop replay case: "
                f"{stale}; regenerate replay evidence."
            ),
        )
        rejected.append(
            {
                "id": item_id,
                "title": row.get("title"),
                "artifact_path": stale,
                "status": _dict(result.get("item")).get("status"),
            }
        )
    replay_status = {
        str(item.get("id") or ""): str(item.get("status") or "")
        for item in queue.items(
            target_bucket="browser_desktop_replay",
            limit=max(1, int(limit)),
        )["items"]
    }
    recipe_items = queue.items(
        status="pending",
        target_bucket="browser_desktop_repair_recipe",
        limit=max(1, int(limit)),
    )["items"]
    for row in recipe_items:
        recipe = _dict(_dict(row.get("metadata")).get("recipe"))
        source_ids = [
            str(item_id)
            for item_id in recipe.get("source_item_ids") or []
            if str(item_id or "")
        ]
        if not source_ids:
            continue
        if not all(
            replay_status.get(item_id) in {"rejected", "archived"}
            for item_id in source_ids
        ):
            continue
        item_id = str(row.get("id") or "")
        if not item_id:
            continue
        result = queue.decide(
            item_id,
            action="archived",
            reason=(
                "Archived stale browser/desktop repair recipe because all source "
                "replay cases were rejected or archived."
            ),
        )
        archived_recipes.append(
            {
                "id": item_id,
                "title": row.get("title"),
                "status": _dict(result.get("item")).get("status"),
            }
        )
    return {
        "schema": STALE_REJECTION_SCHEMA,
        "inspected": len(rows),
        "rejected_count": len(rejected),
        "archived_recipe_count": len(archived_recipes),
        "skipped_count": skipped,
        "rejected": rejected,
        "archived_recipes": archived_recipes,
    }


def compute_browser_desktop_repair_recipe_verifications(
    *,
    review_queue_path: str | Path | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    queue = ReviewQueue(
        Path(review_queue_path)
        if review_queue_path is not None
        else app_paths().review_queue_path,
    )
    recipe_items = queue.items(
        status="pending",
        target_bucket="browser_desktop_repair_recipe",
        limit=max(1, int(limit)),
    )["items"]
    replay_items = queue.items(
        target_bucket="browser_desktop_replay",
        limit=max(1, int(limit)),
    )["items"]
    replay_status = {
        str(item.get("id") or ""): str(item.get("status") or "pending")
        for item in replay_items
    }
    verifications = [
        _verification_from_recipe_item(item, replay_status)
        for item in recipe_items
    ]
    verified = sum(1 for row in verifications if row["status"] == "verified")
    blocked = sum(1 for row in verifications if row["status"] != "verified")
    return {
        "schema": VERIFICATION_SCHEMA,
        "total": len(verifications),
        "verified_count": verified,
        "blocked_count": blocked,
        "ready": blocked == 0,
        "verifications": verifications,
        "next_actions": _verification_next_actions(verifications),
    }


def attach_browser_desktop_repair_recipe_evidence(
    *,
    item_id: str,
    passed: bool,
    provided: list[str] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    notes: str = "",
    actor: str = "operator_panel",
    review_queue_path: str | Path | None = None,
) -> dict[str, Any]:
    queue = ReviewQueue(
        Path(review_queue_path)
        if review_queue_path is not None
        else app_paths().review_queue_path,
    )
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "attached_at": datetime.now(UTC).isoformat(),
        "actor": str(actor or "operator_panel")[:120],
        "passed": bool(passed),
        "provided": _unique_strings(provided or []),
        "artifacts": [
            artifact
            for artifact in artifacts or []
            if isinstance(artifact, dict)
        ][:20],
        "notes": str(notes or "")[:1200],
    }
    result = queue.update_metadata(
        item_id,
        metadata_patch={"verification_evidence": evidence},
        tags=["verification_evidence"],
    )
    verification = compute_browser_desktop_repair_recipe_verifications(
        review_queue_path=review_queue_path,
    )
    current = next(
        (
            row for row in verification.get("verifications") or []
            if isinstance(row, dict) and row.get("item_id") == item_id
        ),
        None,
    )
    return {
        "schema": "octopus.browser_desktop_repair_recipe_evidence_attachment.v1",
        "item": result["item"],
        "evidence": evidence,
        "verification": current,
    }


def rerun_browser_desktop_repair_recipe_evidence(
    *,
    item_id: str,
    review_queue_path: str | Path | None = None,
    api_base_url: str = "http://127.0.0.1:8000",
    promote_source_cases: bool = False,
    actor: str = "auto_rerun",
    api_get: Callable[[str], dict[str, Any]] | None = None,
    api_request: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    queue = ReviewQueue(
        Path(review_queue_path)
        if review_queue_path is not None
        else app_paths().review_queue_path,
    )
    item = _recipe_item(queue, item_id)
    recipe = _dict(_dict(item.get("metadata")).get("recipe"))
    plan = _dict(recipe.get("verification_plan"))
    artifacts: list[dict[str, Any]] = []
    artifacts.extend(
        _produce_fresh_recipe_evidence(
            recipe,
            api_base_url=api_base_url,
            api_get=api_get,
            api_request=api_request,
        )
    )
    api_checks = [
        str(check)
        for check in plan.get("api_checks") or []
        if str(check or "").startswith("/api/")
    ]
    provided: list[str] = []
    for check in api_checks:
        result = _run_api_check(
            check,
            api_base_url=api_base_url,
            api_get=api_get,
        )
        artifacts.append(result)
        if result.get("ok") is True:
            provided.extend(_provided_evidence_from_api_check(check, result))
    for artifact in artifacts:
        provided.extend(_provided_evidence_from_artifact(artifact))
    provided = _unique_strings(provided)
    required = [
        str(item)
        for item in plan.get("evidence_required") or []
        if str(item or "")
    ]
    missing = [
        item for item in required
        if item not in set(provided)
    ]
    passed = not missing and all(
        artifact.get("ok") is True for artifact in artifacts
    )
    promoted_sources = 0
    if passed and promote_source_cases:
        for source_item_id in recipe.get("source_item_ids") or []:
            source_id = str(source_item_id or "")
            if not source_id:
                continue
            try:
                queue.decide(
                    source_id,
                    action="promoted",
                    promoted_to="browser_desktop_replay",
                    reason=(
                        "Auto-promoted source replay case after browser/desktop "
                        "repair recipe rerun evidence passed."
                    ),
                )
                promoted_sources += 1
            except KeyError:
                continue
    attachment = attach_browser_desktop_repair_recipe_evidence(
        item_id=item_id,
        passed=passed,
        provided=provided,
        artifacts=artifacts,
        notes=(
            "Auto rerun evidence passed."
            if passed
            else f"Auto rerun evidence missing: {', '.join(missing) or 'api_check_failed'}."
        ),
        actor=actor,
        review_queue_path=review_queue_path,
    )
    return {
        "schema": "octopus.browser_desktop_repair_recipe_rerun.v1",
        "item_id": item_id,
        "passed": passed,
        "provided": provided,
        "missing": missing,
        "promoted_source_count": promoted_sources,
        "artifacts": artifacts,
        "attachment": attachment,
    }


def rerun_browser_desktop_repair_recipe_batch(
    *,
    review_queue_path: str | Path | None = None,
    api_base_url: str = "http://127.0.0.1:8000",
    promote_source_cases: bool = False,
    actor: str = "auto_rerun",
    limit: int = 20,
    api_get: Callable[[str], dict[str, Any]] | None = None,
    api_request: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = compute_browser_desktop_repair_recipe_verifications(
        review_queue_path=review_queue_path,
        limit=max(1, int(limit)),
    )
    targets = [
        row for row in report.get("verifications") or []
        if isinstance(row, dict) and row.get("status") != "verified"
    ][: max(1, int(limit))]
    results = [
        rerun_browser_desktop_repair_recipe_evidence(
            item_id=str(row.get("item_id") or ""),
            review_queue_path=review_queue_path,
            api_base_url=api_base_url,
            promote_source_cases=promote_source_cases,
            actor=actor,
            api_get=api_get,
            api_request=api_request,
        )
        for row in targets
        if row.get("item_id")
    ]
    return {
        "schema": "octopus.browser_desktop_repair_recipe_rerun_batch.v1",
        "attempted": len(results),
        "passed": sum(1 for row in results if row.get("passed") is True),
        "failed": sum(1 for row in results if row.get("passed") is not True),
        "results": results,
    }


def _cluster_key(row: dict[str, Any]) -> str:
    kind = str(row.get("candidate_kind") or "unknown")
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    if kind == "browser_pixel_replay_gate_case":
        return "|".join(("pixel", _pixel_reason(metadata), _artifact_shape(metadata)))
    if kind == "browser_session_replay_case":
        last_action = _dict(metadata.get("last_action"))
        health = _dict(metadata.get("health"))
        issues = health.get("issues") if isinstance(health.get("issues"), list) else []
        issue_text = ",".join(sorted(str(issue) for issue in issues)) or "healthy"
        return "|".join((
            "browser_session",
            str(last_action.get("status") or "unknown"),
            str(last_action.get("action") or "unknown"),
            issue_text,
        ))
    if kind == "computer_activity_replay_case":
        last_activity = _dict(metadata.get("last_activity"))
        action = _dict(last_activity.get("action"))
        return "|".join((
            "computer_activity",
            str(last_activity.get("event") or "unknown"),
            str(action.get("action") or "unknown"),
            f"pending:{int(metadata.get('pending_count') or 0)}",
        ))
    return "|".join(("unknown", kind))


def _verification_from_recipe_item(
    item: dict[str, Any],
    replay_status: dict[str, str],
) -> dict[str, Any]:
    metadata = _dict(item.get("metadata"))
    recipe = _dict(metadata.get("recipe"))
    evidence = _dict(metadata.get("verification_evidence"))
    source_item_ids = [
        str(item_id)
        for item_id in recipe.get("source_item_ids") or []
        if str(item_id or "")
    ]
    source_status_counts: dict[str, int] = {}
    for item_id in source_item_ids:
        status = replay_status.get(item_id, "missing")
        source_status_counts[status] = source_status_counts.get(status, 0) + 1
    missing_evidence = [
        str(name)
        for name in _dict(recipe.get("verification_plan")).get("evidence_required") or []
        if str(name or "")
    ]
    provided_evidence = evidence.get("provided") if isinstance(evidence.get("provided"), list) else []
    missing_evidence = [
        name for name in missing_evidence
        if name not in {str(item) for item in provided_evidence}
    ]
    blockers: list[str] = []
    if source_status_counts.get("pending", 0):
        blockers.append("source_replay_cases_pending")
    if not evidence:
        blockers.append("missing_verification_evidence")
    if missing_evidence:
        blockers.append("missing_required_evidence")
    if evidence and evidence.get("passed") is not True:
        blockers.append("verification_evidence_failed")
    status = "verified" if not blockers else "needs_rerun_evidence"
    return {
        "schema": "octopus.browser_desktop_repair_recipe_verification.v1",
        "item_id": item.get("id"),
        "recipe_id": recipe.get("recipe_id"),
        "title": item.get("title"),
        "priority": item.get("priority"),
        "status": status,
        "blockers": blockers,
        "source_status_counts": dict(sorted(source_status_counts.items())),
        "missing_evidence": missing_evidence,
        "verification_evidence": evidence,
    }


def _recipe_item(queue: ReviewQueue, item_id: str) -> dict[str, Any]:
    wanted = str(item_id or "")
    for item in queue.items(
        target_bucket="browser_desktop_repair_recipe",
        limit=10000,
    )["items"]:
        if str(item.get("id") or "") == wanted:
            return item
    raise KeyError(wanted)


def _produce_fresh_recipe_evidence(
    recipe: dict[str, Any],
    *,
    api_base_url: str,
    api_get: Callable[[str], dict[str, Any]] | None,
    api_request: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    kind = str(recipe.get("candidate_kind") or "")
    if kind == "browser_session_replay_case":
        return _produce_browser_session_evidence(
            recipe,
            api_base_url=api_base_url,
            api_request=api_request,
        )
    if kind == "browser_pixel_replay_gate_case":
        return _produce_browser_pixel_evidence(
            recipe,
            api_base_url=api_base_url,
            api_get=api_get,
            api_request=api_request,
        )
    return []


def _produce_browser_session_evidence(
    recipe: dict[str, Any],
    *,
    api_base_url: str,
    api_request: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    plan = _dict(recipe.get("verification_plan"))
    session_id = _session_id_from_plan(plan) or "workspace"
    summary = _dict(recipe.get("evidence_summary"))
    last_action = _dict(summary.get("last_action"))
    navigate_url = str(last_action.get("detail") or "").strip()
    out = [
        _run_api_mutation(
            "POST",
            "/api/browser/session/ensure",
            {
                "session_id": session_id,
                "headless": True,
            },
            api_base_url=api_base_url,
            api_request=api_request,
        )
    ]
    if navigate_url.startswith(("http://", "https://")):
        out.append(
            _run_api_mutation(
                "POST",
                "/api/browser/navigate",
                {
                    "session_id": session_id,
                    "url": navigate_url,
                },
                api_base_url=api_base_url,
                api_request=api_request,
            )
        )
    return out


def _produce_browser_pixel_evidence(
    recipe: dict[str, Any],
    *,
    api_base_url: str,
    api_get: Callable[[str], dict[str, Any]] | None,
    api_request: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    session_id = _pixel_session_id(recipe)
    out: list[dict[str, Any]] = []
    source_artifact = _source_artifact_check(recipe)
    if source_artifact:
        out.append(source_artifact)
    out.append(
        _run_api_mutation(
            "POST",
            "/api/browser/session/reset",
            {
                "session_id": session_id,
                "relaunch": False,
            },
            api_base_url=api_base_url,
            api_request=api_request,
        )
    )
    out = [
        *out,
        _run_api_mutation(
            "POST",
            "/api/browser/session/ensure",
            {
                "session_id": session_id,
                "headless": True,
            },
            api_base_url=api_base_url,
            api_request=api_request,
        )
    ]
    navigate_url = _pixel_recipe_url(recipe)
    if navigate_url:
        out.append(
            _run_api_mutation(
                "POST",
                "/api/browser/navigate",
                {
                    "session_id": session_id,
                    "url": navigate_url,
                },
                api_base_url=api_base_url,
                api_request=api_request,
            )
        )
    before = _run_screenshot_check(
        f"/api/browser/screenshot/base64?session_id={session_id}",
        label="before",
        api_base_url=api_base_url,
        api_get=api_get,
    )
    out.append(before)
    out.append(
        _run_api_mutation(
            "POST",
            "/api/browser/action",
            {
                "session_id": session_id,
                "action": "reload",
            },
            api_base_url=api_base_url,
            api_request=api_request,
        )
    )
    after = _run_screenshot_check(
        f"/api/browser/screenshot/base64?session_id={session_id}",
        label="after",
        api_base_url=api_base_url,
        api_get=api_get,
    )
    out.append(after)
    after_bytes = after.get("_screenshot_bytes")
    if isinstance(after_bytes, bytes):
        out.append(_run_pixel_assertion(after_bytes))
    before_bytes = before.get("_screenshot_bytes")
    if isinstance(before_bytes, bytes) and isinstance(after_bytes, bytes):
        out.append(_run_pixel_comparison(before_bytes, after_bytes, recipe))
    out.append(
        _run_api_mutation(
            "POST",
            "/api/browser/session/reset",
            {
                "session_id": session_id,
                "relaunch": False,
            },
            api_base_url=api_base_url,
            api_request=api_request,
        )
    )
    return [_public_artifact(row) for row in out]


def _run_screenshot_check(
    path: str,
    *,
    label: str,
    api_base_url: str,
    api_get: Callable[[str], dict[str, Any]] | None,
) -> dict[str, Any]:
    result = _run_api_check(path, api_base_url=api_base_url, api_get=api_get)
    result["type"] = "screenshot_check"
    result["label"] = label
    if result.get("ok") is not True:
        return result
    try:
        encoded = str(_dict(result.get("response")).get("base64") or "")
        if encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        screenshot = base64.b64decode(encoded, validate=True)
        result["_screenshot_bytes"] = screenshot
        result["bytes"] = len(screenshot)
    except Exception as exc:  # noqa: BLE001 - malformed screenshots are evidence
        result["ok"] = False
        result["error"] = f"invalid screenshot payload: {exc}"
    return result


def _run_pixel_assertion(screenshot: bytes) -> dict[str, Any]:
    try:
        assertion = assert_screenshot_pixels(screenshot)
        return {
            "type": "pixel_assertion",
            "ok": assertion.get("ok") is True,
            "assertion": assertion,
        }
    except Exception as exc:  # noqa: BLE001 - failed pixel parsing is evidence
        return {
            "type": "pixel_assertion",
            "ok": False,
            "error": str(exc),
        }


def _run_pixel_comparison(
    before: bytes,
    after: bytes,
    recipe: dict[str, Any],
) -> dict[str, Any]:
    try:
        comparison = compare_screenshot_pixels(
            before,
            after,
            min_changed_ratio=_pixel_min_changed_ratio(recipe),
        )
        return {
            "type": "pixel_comparison",
            "ok": comparison.get("ok") is True,
            "comparison": comparison,
        }
    except Exception as exc:  # noqa: BLE001 - failed pixel parsing is evidence
        return {
            "type": "pixel_comparison",
            "ok": False,
            "error": str(exc),
        }


def _public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in artifact.items()
        if not str(key).startswith("_")
    }


def _pixel_session_id(recipe: dict[str, Any]) -> str:
    seed = str(recipe.get("recipe_id") or recipe.get("cluster_key") or "pixel")
    digest = hashlib.sha256(seed.encode()).hexdigest()[:10]
    return f"browser-pixel-{digest}"


def _pixel_recipe_url(recipe: dict[str, Any]) -> str:
    summary = _dict(recipe.get("evidence_summary"))
    artifact = _dict(summary.get("artifact"))
    url = str(artifact.get("url") or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def _source_artifact_check(recipe: dict[str, Any]) -> dict[str, Any] | None:
    summary = _dict(recipe.get("evidence_summary"))
    artifact = _dict(summary.get("artifact"))
    local_path = str(artifact.get("local_path") or "").strip()
    if not local_path:
        return None
    path = Path(local_path)
    return {
        "type": "source_artifact",
        "ok": path.is_file(),
        "path": local_path,
        "reason": "available" if path.is_file() else "source artifact is no longer readable",
    }


def _stale_source_artifact(metadata: dict[str, Any]) -> str:
    artifact = metadata.get("artifact") if isinstance(metadata.get("artifact"), dict) else {}
    local_path = str(artifact.get("local_path") or "").strip()
    if not local_path:
        return ""
    path = Path(local_path)
    if not path.is_file():
        return local_path
    if path.suffix.lower() == ".png" and not _valid_png_header(path):
        return f"{local_path} (invalid png evidence)"
    replay = _dict(metadata.get("replay"))
    if replay.get("replayable") is False and _is_pytest_temp_path(path):
        return f"{local_path} (unreplayable pytest artifact)"
    return ""


def _valid_png_header(path: Path) -> bool:
    try:
        data = path.read_bytes()[:33]
    except OSError:
        return False
    if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    return data[12:16] == b"IHDR"


def _is_pytest_temp_path(path: Path) -> bool:
    return any(
        part.startswith("pytest-") or part.startswith("pytest-of-")
        for part in path.parts
    )


def _stale_computer_activity_replay(
    metadata: dict[str, Any],
    *,
    max_age_seconds: int = 300,
) -> str:
    last_activity = _dict(metadata.get("last_activity"))
    created_at = last_activity.get("created_at")
    try:
        age_seconds = time.time() - float(created_at)
    except (TypeError, ValueError):
        return "computer activity replay has no durable created_at timestamp"
    if age_seconds > max_age_seconds:
        return (
            "computer activity replay is ephemeral and "
            f"{int(age_seconds)}s old (ttl {max_age_seconds}s)"
        )
    return ""


def _pixel_min_changed_ratio(recipe: dict[str, Any]) -> float:
    summary = _dict(recipe.get("evidence_summary"))
    thresholds = _dict(_dict(summary.get("failure")).get("thresholds"))
    value = thresholds.get("min_changed_ratio")
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.01
    return max(0.0, min(ratio, 1.0))


def _session_id_from_plan(plan: dict[str, Any]) -> str:
    for check in plan.get("api_checks") or []:
        text = str(check or "")
        if "session_id=" not in text:
            continue
        query = parse_qs(urlparse(text).query)
        session_id = str((query.get("session_id") or [""])[0]).strip()
        if session_id:
            return session_id
    return ""


def _run_api_check(
    path: str,
    *,
    api_base_url: str,
    api_get: Callable[[str], dict[str, Any]] | None,
) -> dict[str, Any]:
    try:
        data = api_get(path) if api_get is not None else _default_api_get(api_base_url, path)
        ok = _api_check_ok(path, data)
        return {
            "type": "api_check",
            "url": path,
            "ok": ok,
            "response": data,
        }
    except Exception as exc:  # noqa: BLE001 - failed checks are evidence too
        return {
            "type": "api_check",
            "url": path,
            "ok": False,
            "error": str(exc),
        }


def _run_api_mutation(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    *,
    api_base_url: str,
    api_request: Callable[[str, str, dict[str, Any] | None], dict[str, Any]] | None,
) -> dict[str, Any]:
    try:
        data = (
            api_request(method, path, body)
            if api_request is not None
            else _default_api_request(api_base_url, method, path, body)
        )
        ok = data.get("ok") is not False and not str(data.get("error") or "")
        return {
            "type": "api_mutation",
            "method": method,
            "url": path,
            "ok": ok,
            "response": data,
        }
    except Exception as exc:  # noqa: BLE001 - failed producers are evidence too
        return {
            "type": "api_mutation",
            "method": method,
            "url": path,
            "ok": False,
            "error": str(exc),
        }


def _default_api_get(api_base_url: str, path: str) -> dict[str, Any]:
    if not path.startswith("/api/"):
        raise ValueError("api check path must start with /api/")
    url = urljoin(api_base_url.rstrip("/") + "/", path.lstrip("/"))
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=8) as response:  # noqa: S310 - localhost API check
        raw = response.read(2_000_000)
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else {"value": data}


def _default_api_request(
    api_base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> dict[str, Any]:
    if not path.startswith("/api/"):
        raise ValueError("api mutation path must start with /api/")
    url = urljoin(api_base_url.rstrip("/") + "/", path.lstrip("/"))
    data = json.dumps(body or {}).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=12) as response:  # noqa: S310 - localhost API producer
        raw = response.read(2_000_000)
    parsed = json.loads(raw.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {"value": parsed}



def _api_check_ok(path: str, data: dict[str, Any]) -> bool:
    if data.get("ok") is False:
        return False
    if "/api/browser/session/replay-case" in path:
        return bool(data.get("replay_ready"))
    if "/api/browser/session/health" in path:
        return bool(data.get("healthy"))
    if "/api/computer/activity/replay-case" in path:
        return bool(data.get("replay_ready"))
    return True


def _provided_evidence_from_api_check(
    path: str,
    artifact: dict[str, Any],
) -> list[str]:
    if artifact.get("ok") is not True:
        return []
    if "/api/browser/session/replay-case" in path:
        return ["browser_session_replay_case"]
    if "/api/browser/session/health" in path:
        return ["session_health"]
    if "/api/computer/activity/replay-case" in path:
        return ["computer_activity_replay_case"]
    return []


def _provided_evidence_from_artifact(artifact: dict[str, Any]) -> list[str]:
    if artifact.get("ok") is not True:
        return []
    if artifact.get("type") == "pixel_assertion":
        return ["fresh_screenshot"]
    if artifact.get("type") == "pixel_comparison":
        return ["pixel_comparison"]
    return []


def _recipe_from_cluster(key: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    kind = str(first.get("candidate_kind") or "unknown")
    metadata = _dict(first.get("metadata"))
    case_ids = _unique_strings(
        _case_id(_dict(row.get("metadata")))
        for row in rows
    )
    fingerprints = _unique_strings(
        str(_dict(row.get("metadata")).get("fingerprint") or "")
        for row in rows
    )
    priority = "P0" if any(str(row.get("priority") or "") == "P0" for row in rows) else "P1"
    if len(rows) >= 3:
        priority = "P0"
    recipe_id = "browser-desktop-recipe:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    return {
        "schema": RECIPE_SCHEMA,
        "recipe_id": recipe_id,
        "cluster_key": key,
        "candidate_kind": kind,
        "title": _title(kind, metadata, len(rows)),
        "priority": priority,
        "occurrences": len(rows),
        "source_item_ids": _unique_strings(str(row.get("id") or "") for row in rows),
        "case_ids": case_ids,
        "fingerprints": fingerprints,
        "evidence_summary": _evidence_summary(kind, metadata, len(rows)),
        "failure_taxonomy": _failure_taxonomy(kind, metadata),
        "repair_route": _repair_route(kind, metadata),
        "automation_playbook": _automation_playbook(kind, metadata),
        "recommended_steps": _recommended_steps(kind, metadata),
        "verification_plan": _verification_plan(kind, metadata),
        "quality_signals": _recipe_quality_signals(kind, metadata, rows),
        "promotion_gate": {
            "schema": "octopus.browser_desktop_repair_recipe_gate.v1",
            "requires_operator_review": True,
            "requires_replay_rerun": True,
            "requires_fresh_visual_or_activity_evidence": True,
            "blocks_auto_promotion": True,
        },
    }


def _recipe_quality_signals(
    kind: str,
    metadata: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    verification_plan = _verification_plan(kind, metadata)
    taxonomy = _failure_taxonomy(kind, metadata)
    repair_route = _repair_route(kind, metadata)
    playbook = _automation_playbook(kind, metadata)
    evidence_required = [
        str(item)
        for item in verification_plan.get("evidence_required") or []
        if str(item or "")
    ]
    api_checks = [
        str(item)
        for item in verification_plan.get("api_checks") or []
        if str(item or "")
    ]
    return {
        "schema": "octopus.browser_desktop_repair_recipe_quality_signals.v1",
        "deterministic_cluster": len(rows) >= 1 and kind in {
            "browser_pixel_replay_gate_case",
            "browser_session_replay_case",
            "computer_activity_replay_case",
        },
        "source_item_count": len(rows),
        "has_case_identity": bool(
            _unique_strings(_case_id(_dict(row.get("metadata"))) for row in rows)
        ),
        "has_fingerprint": bool(
            _unique_strings(
                str(_dict(row.get("metadata")).get("fingerprint") or "")
                for row in rows
            )
        ),
        "has_api_checks": bool(api_checks),
        "has_required_evidence": bool(evidence_required),
        "has_failure_taxonomy": (
            taxonomy.get("schema") == FAILURE_TAXONOMY_SCHEMA
            and bool(taxonomy.get("failure_class"))
            and bool(taxonomy.get("signals"))
        ),
        "has_repair_route": (
            repair_route.get("schema") == REPAIR_ROUTE_SCHEMA
            and bool(repair_route.get("route_id"))
            and bool(repair_route.get("strategy"))
            and bool(repair_route.get("verification_evidence"))
        ),
        "has_automation_playbook": (
            playbook.get("schema") == AUTOMATION_PLAYBOOK_SCHEMA
            and bool(playbook.get("steps"))
            and bool(playbook.get("rollback"))
        ),
        "requires_replay_rerun": True,
        "blocks_auto_promotion": True,
    }


def _quality_gate_from_recipes(
    recipes: list[dict[str, Any]],
    *,
    pending_count: int,
) -> dict[str, Any]:
    blockers: list[str] = []
    if pending_count > 0 and not recipes:
        blockers.append("pending_replay_without_recipe")
    required_signal_names = (
        "deterministic_cluster",
        "has_failure_taxonomy",
        "has_repair_route",
        "has_automation_playbook",
        "has_api_checks",
        "has_required_evidence",
        "requires_replay_rerun",
        "blocks_auto_promotion",
    )
    checked = 0
    passed = 0
    for recipe in recipes:
        signals = _dict(recipe.get("quality_signals"))
        missing = [
            name for name in required_signal_names
            if signals.get(name) is not True
        ]
        checked += len(required_signal_names)
        passed += len(required_signal_names) - len(missing)
        if missing:
            blockers.append(
                f"{recipe.get('recipe_id') or 'recipe'} missing {', '.join(missing)}"
            )
        gate = _dict(recipe.get("promotion_gate"))
        if gate.get("requires_replay_rerun") is not True:
            blockers.append(
                f"{recipe.get('recipe_id') or 'recipe'} does not require replay rerun"
            )
        if gate.get("blocks_auto_promotion") is not True:
            blockers.append(
                f"{recipe.get('recipe_id') or 'recipe'} does not block auto promotion"
            )
    score = round(passed / checked, 3) if checked else (1.0 if pending_count == 0 else 0.0)
    ready = not blockers and score >= 1.0
    return {
        "schema": QUALITY_GATE_SCHEMA,
        "score": score,
        "ready": ready,
        "recipe_count": len(recipes),
        "pending_count": pending_count,
        "blockers": blockers,
        "signals": {
            "checked": checked,
            "passed": passed,
            "required": list(required_signal_names),
            "requires_replay_rerun": True,
            "blocks_auto_promotion": True,
        },
    }


def _title(kind: str, metadata: dict[str, Any], occurrences: int) -> str:
    if kind == "browser_pixel_replay_gate_case":
        return f"Stabilize browser pixel replay gate ({occurrences} case(s))"
    if kind == "browser_session_replay_case":
        action = str(_dict(metadata.get("last_action")).get("action") or "session")
        return f"Stabilize browser session replay: {action}"
    if kind == "computer_activity_replay_case":
        action = str(_dict(_dict(metadata.get("last_activity")).get("action")).get("action") or "activity")
        return f"Stabilize desktop activity replay: {action}"
    return f"Stabilize browser/desktop replay cluster ({occurrences} case(s))"


def _evidence_summary(kind: str, metadata: dict[str, Any], occurrences: int) -> dict[str, Any]:
    if kind == "browser_pixel_replay_gate_case":
        replay_case = _dict(metadata.get("replay_gate_case"))
        failures = replay_case.get("failures") if isinstance(replay_case.get("failures"), list) else []
        return {
            "occurrences": occurrences,
            "failure_reason": _pixel_reason(metadata),
            "failure_count": len(failures) or int(metadata.get("failure_count") or 0),
            "artifact": metadata.get("artifact") if isinstance(metadata.get("artifact"), dict) else {},
        }
    if kind == "browser_session_replay_case":
        return {
            "occurrences": occurrences,
            "health": _dict(metadata.get("health")),
            "last_action": _dict(metadata.get("last_action")),
            "action_count": metadata.get("action_count"),
        }
    if kind == "computer_activity_replay_case":
        return {
            "occurrences": occurrences,
            "last_activity": _dict(metadata.get("last_activity")),
            "activity_count": metadata.get("activity_count"),
            "pending_count": metadata.get("pending_count"),
        }
    return {"occurrences": occurrences}


def _failure_taxonomy(kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if kind == "browser_pixel_replay_gate_case":
        reason = _pixel_reason(metadata)
        artifact = _dict(metadata.get("artifact"))
        failure_class = "visual_noop_or_blank_frame"
        if "changed pixels" in reason.lower():
            failure_class = "visual_delta_below_threshold"
        elif "blank" in reason.lower():
            failure_class = "blank_or_unrendered_screenshot"
        elif "invalid" in reason.lower():
            failure_class = "invalid_visual_artifact"
        return {
            "schema": FAILURE_TAXONOMY_SCHEMA,
            "surface": "browser",
            "failure_class": failure_class,
            "severity": "P0",
            "signals": _unique_strings([
                reason,
                _artifact_shape(metadata),
                str(artifact.get("local_path") or artifact.get("filename") or ""),
            ]),
            "probable_root_causes": [
                "stale screenshot evidence",
                "action did not mutate the visible page",
                "viewport or render timing drifted from the recorded case",
            ],
        }
    if kind == "browser_session_replay_case":
        health = _dict(metadata.get("health"))
        last_action = _dict(metadata.get("last_action"))
        issues = [
            str(item)
            for item in health.get("issues") or []
            if str(item or "")
        ]
        action_status = str(last_action.get("status") or "")
        failure_class = "browser_session_unhealthy"
        if "crash" in " ".join(issues).lower():
            failure_class = "browser_page_crash"
        elif action_status == "failed":
            failure_class = "browser_action_failed"
        elif not health.get("healthy", True):
            failure_class = "browser_health_check_failed"
        return {
            "schema": FAILURE_TAXONOMY_SCHEMA,
            "surface": "browser",
            "failure_class": failure_class,
            "severity": "P1",
            "signals": _unique_strings([
                *issues,
                action_status,
                str(last_action.get("action") or ""),
                str(last_action.get("detail") or ""),
            ]),
            "probable_root_causes": [
                "stale or crashed browser session",
                "navigation or action failed before replay evidence was captured",
                "session health was not checked after recovery",
            ],
        }
    if kind == "computer_activity_replay_case":
        last_activity = _dict(metadata.get("last_activity"))
        action = _dict(last_activity.get("action"))
        detail = _dict(last_activity.get("detail"))
        policy = _dict(detail.get("policy_decision"))
        error = str(last_activity.get("error") or "")
        failure_class = "desktop_activity_needs_replay"
        if policy.get("decision") == "denied" or "policy denied" in error.lower():
            failure_class = "desktop_policy_denied"
        elif action.get("source") == "uia" and not action.get("matched_control"):
            failure_class = "desktop_uia_grounding_missing"
        elif last_activity.get("ok") is False:
            failure_class = "desktop_action_failed"
        return {
            "schema": FAILURE_TAXONOMY_SCHEMA,
            "surface": "desktop",
            "failure_class": failure_class,
            "severity": "P0" if failure_class == "desktop_policy_denied" else "P1",
            "signals": _unique_strings([
                str(last_activity.get("event") or ""),
                str(action.get("action") or ""),
                error,
                str(policy.get("reason") or ""),
            ]),
            "probable_root_causes": [
                "desktop preview or execute evidence was not replayed",
                "active app policy or lease state changed during automation",
                "UIA grounding may not match the current desktop tree",
            ],
        }
    return {
        "schema": FAILURE_TAXONOMY_SCHEMA,
        "surface": "unknown",
        "failure_class": "unknown_browser_desktop_replay_failure",
        "severity": "P2",
        "signals": ["unknown replay case"],
        "probable_root_causes": ["unclassified browser/desktop replay case"],
    }


def _repair_route(kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
    taxonomy = _failure_taxonomy(kind, metadata)
    failure_class = str(taxonomy.get("failure_class") or "unknown")
    verification = _verification_plan(kind, metadata)
    if kind == "browser_pixel_replay_gate_case":
        route_id = "browser_pixel_replay_refresh"
        strategy = "recapture_before_after_and_compare_pixels"
        actions = [
            "reset_isolated_browser_session",
            "navigate_to_recorded_url_when_available",
            "capture_before_screenshot",
            "replay_action_or_reload",
            "capture_after_screenshot",
            "run_pixel_assertion_and_delta_check",
        ]
    elif kind == "browser_session_replay_case":
        route_id = "browser_session_health_recovery"
        strategy = "restart_session_rerun_last_action_and_verify_health"
        actions = [
            "ensure_browser_session",
            "rerun_last_browser_action",
            "capture_session_replay_case",
            "check_session_health",
        ]
    elif kind == "computer_activity_replay_case":
        route_id = (
            "desktop_policy_review"
            if failure_class == "desktop_policy_denied"
            else "desktop_preview_execute_replay"
        )
        strategy = (
            "surface_policy_decision_before_retry"
            if failure_class == "desktop_policy_denied"
            else "replay_preview_execute_under_same_lease"
        )
        actions = [
            "inspect_desktop_policy_decision",
            "recreate_preview_token",
            "verify_low_or_reviewed_risk",
            "rerun_activity_replay_case",
            "attach_uia_or_activity_evidence",
        ]
    else:
        route_id = "browser_desktop_manual_replay_review"
        strategy = "classify_and_rerun_replay_case"
        actions = ["classify_failure", "rerun_replay_case", "attach_evidence"]
    return {
        "schema": REPAIR_ROUTE_SCHEMA,
        "route_id": route_id,
        "failure_class": failure_class,
        "strategy": strategy,
        "actions": actions,
        "verification_evidence": [
            str(item)
            for item in verification.get("evidence_required") or []
            if str(item or "")
        ],
        "api_checks": [
            str(item)
            for item in verification.get("api_checks") or []
            if str(item or "")
        ],
        "promotion_policy": {
            "requires_operator_review": True,
            "requires_fresh_evidence": True,
            "blocks_auto_promotion_until_verified": True,
        },
    }


def _automation_playbook(kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
    route = _repair_route(kind, metadata)
    if kind == "browser_pixel_replay_gate_case":
        steps = [
            {"type": "browser_session_reset", "session_id": "derived_from_recipe"},
            {"type": "browser_session_ensure", "headless": True},
            {"type": "browser_screenshot", "label": "before"},
            {"type": "browser_action", "action": "reload"},
            {"type": "browser_screenshot", "label": "after"},
            {"type": "pixel_compare", "threshold_source": "recorded_failure"},
        ]
        rollback = ["reset_derived_browser_session"]
    elif kind == "browser_session_replay_case":
        session_id = str(metadata.get("session_id") or "workspace")
        steps = [
            {"type": "browser_session_ensure", "session_id": session_id},
            {"type": "browser_replay_case", "session_id": session_id},
            {"type": "browser_session_health", "session_id": session_id},
        ]
        rollback = ["reset_session_if_health_fails"]
    elif kind == "computer_activity_replay_case":
        steps = [
            {"type": "computer_policy_check"},
            {"type": "computer_preview", "lease": "same_owner"},
            {"type": "computer_activity_replay_case"},
            {"type": "uia_assertion_when_available"},
        ]
        rollback = ["release_computer_lease", "expire_preview_token"]
    else:
        steps = [{"type": "manual_replay_review"}]
        rollback = ["leave_source_case_pending"]
    return {
        "schema": AUTOMATION_PLAYBOOK_SCHEMA,
        "route_id": route.get("route_id"),
        "steps": steps,
        "rollback": rollback,
        "idempotency_key": _playbook_idempotency_key(kind, metadata),
        "evidence_contract": route.get("verification_evidence") or [],
    }


def _recommended_steps(kind: str, metadata: dict[str, Any]) -> list[str]:
    if kind == "browser_pixel_replay_gate_case":
        return [
            "Replay the browser action that produced the failing screenshot.",
            "Capture a fresh before/after screenshot pair for the same viewport.",
            "Compare pixel metrics against the recorded threshold before promotion.",
        ]
    if kind == "browser_session_replay_case":
        last_action = _dict(metadata.get("last_action"))
        action = str(last_action.get("action") or "the last browser action")
        return [
            f"Re-run the browser session replay through `{action}`.",
            "Verify `/api/browser/session/health` reports a healthy session.",
            "Attach the replay case and session health evidence before promotion.",
        ]
    if kind == "computer_activity_replay_case":
        return [
            "Re-run the desktop preview/execute sequence under the same lease owner.",
            "Verify the computer activity replay case is replay_ready.",
            "Attach UIA grounding or activity replay evidence before promotion.",
        ]
    return ["Re-run the replay cluster and attach fresh evidence before promotion."]


def _verification_plan(kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if kind == "browser_pixel_replay_gate_case":
        return {
            "schema": "octopus.browser_desktop_recipe_verification.v1",
            "commands": [],
            "api_checks": [
                "/api/evolution/browser-desktop-quality",
                "/api/evolution/browser-desktop-repair-recipes",
            ],
            "evidence_required": ["fresh_screenshot", "pixel_comparison"],
        }
    if kind == "browser_session_replay_case":
        session_id = str(metadata.get("session_id") or "workspace")
        return {
            "schema": "octopus.browser_desktop_recipe_verification.v1",
            "commands": [],
            "api_checks": [
                f"/api/browser/session/replay-case?session_id={session_id}",
                f"/api/browser/session/health?session_id={session_id}",
            ],
            "evidence_required": ["browser_session_replay_case", "session_health"],
        }
    return {
        "schema": "octopus.browser_desktop_recipe_verification.v1",
        "commands": [],
        "api_checks": ["/api/computer/activity/replay-case"],
        "evidence_required": ["computer_activity_replay_case"],
    }


def _pixel_reason(metadata: dict[str, Any]) -> str:
    replay_case = _dict(metadata.get("replay_gate_case"))
    failures = replay_case.get("failures") if isinstance(replay_case.get("failures"), list) else []
    reasons = [
        str(item.get("reason") or "")
        for item in failures
        if isinstance(item, dict) and item.get("reason")
    ]
    return "; ".join(reasons) or str(_dict(metadata.get("replay_gate")).get("reason") or "browser_pixel_evidence_failed")


def _artifact_shape(metadata: dict[str, Any]) -> str:
    artifact = _dict(metadata.get("artifact"))
    return f"{artifact.get('width') or 'w'}x{artifact.get('height') or 'h'}"


def _case_id(metadata: dict[str, Any]) -> str:
    replay = metadata.get("replay") if isinstance(metadata.get("replay"), dict) else {}
    return str(metadata.get("case_id") or replay.get("case_id") or "")


def _playbook_idempotency_key(kind: str, metadata: dict[str, Any]) -> str:
    seed = "|".join((
        kind,
        _case_id(metadata),
        str(metadata.get("fingerprint") or ""),
        _pixel_reason(metadata) if kind == "browser_pixel_replay_gate_case" else "",
        str(_dict(metadata.get("last_action")).get("action") or ""),
        str(_dict(_dict(metadata.get("last_activity")).get("action")).get("action") or ""),
    ))
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def _recipe_text(recipe: dict[str, Any]) -> str:
    steps = recipe.get("recommended_steps")
    step_text = "\n".join(
        f"- {step}" for step in steps if isinstance(step, str)
    ) if isinstance(steps, list) else ""
    cases = ", ".join(str(case_id) for case_id in recipe.get("case_ids") or [])
    return (
        f"{recipe.get('title')}\n"
        f"Occurrences: {recipe.get('occurrences')}; cases: {cases or 'none'}.\n"
        "Recommended steps:\n"
        f"{step_text}"
    ).strip()


def _candidate_kind(recipe: dict[str, Any]) -> str:
    digest = hashlib.sha256(str(recipe.get("cluster_key") or "").encode()).hexdigest()[:10]
    return f"browser_desktop_repair_recipe:{digest}"


def _next_actions(recipes: list[dict[str, Any]], pending_count: int) -> list[str]:
    if recipes:
        return [
            f"Queue {len(recipes)} deterministic browser/desktop repair recipe(s) for operator review.",
        ]
    if pending_count:
        return ["Inspect pending replay cases; no deterministic recipe cluster was found yet."]
    return ["No pending browser/desktop replay cases need repair recipes."]


def _verification_next_actions(verifications: list[dict[str, Any]]) -> list[str]:
    blocked = [row for row in verifications if row.get("status") != "verified"]
    if blocked:
        return [
            f"Attach rerun evidence for {len(blocked)} browser/desktop repair recipe(s).",
        ]
    if verifications:
        return ["All browser/desktop repair recipes have rerun evidence."]
    return ["Queue browser/desktop repair recipes before verification."]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unique_strings(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 3)


__all__ = [
    "QUEUE_SCHEMA",
    "RECIPE_SCHEMA",
    "SCHEMA",
    "VERIFICATION_SCHEMA",
    "QUALITY_GATE_SCHEMA",
    "attach_browser_desktop_repair_recipe_evidence",
    "compute_browser_desktop_repair_recipe_quality_gate",
    "compute_browser_desktop_repair_recipes",
    "compute_browser_desktop_repair_recipe_verifications",
    "queue_browser_desktop_repair_recipes",
    "reject_stale_browser_desktop_replay_artifacts",
    "rerun_browser_desktop_repair_recipe_batch",
    "rerun_browser_desktop_repair_recipe_evidence",
]
