"""Plugin lifecycle audit for permission-aware local extension loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.platform.plugins.codex_discovery import discover_codex_plugins

_SCHEMA = "octopus.plugin_lifecycle_audit.v1"


def audit_plugin_lifecycle(
    plugins: list[dict[str, Any]] | None = None,
    *,
    plugin_roots: list[Path] | None = None,
) -> dict[str, Any]:
    rows = [
        _plugin_row(plugin)
        for plugin in (plugins if plugins is not None else discover_codex_plugins(plugin_roots))
        if isinstance(plugin, dict)
    ]
    total = len(rows)
    pass_count = sum(1 for row in rows if row["verdict"] == "pass")
    review_count = sum(1 for row in rows if row["verdict"] == "review")
    fail_count = sum(1 for row in rows if row["verdict"] == "fail")
    score = _score(rows)
    return {
        "schema": _SCHEMA,
        "score": score,
        "verdict": _verdict(score, fail_count, review_count, total),
        "ready": total > 0 and fail_count == 0 and score >= 0.85,
        "total": total,
        "pass_count": pass_count,
        "review_count": review_count,
        "fail_count": fail_count,
        "rows": rows,
        "requirements": _requirements(rows),
        "next_actions": _next_actions(rows, total=total),
    }


def _plugin_row(plugin: dict[str, Any]) -> dict[str, Any]:
    smoke = plugin.get("smoke") if isinstance(plugin.get("smoke"), dict) else {}
    surfaces = smoke.get("surfaces") if isinstance(smoke.get("surfaces"), dict) else {}
    trust = smoke.get("trust") if isinstance(smoke.get("trust"), dict) else {}
    permission_resolution = (
        smoke.get("permission_resolution")
        if isinstance(smoke.get("permission_resolution"), dict)
        else {}
    )
    surface_count = sum(1 for value in surfaces.values() if value)
    lifecycle_hooks = _lifecycle_hooks(plugin)
    findings: list[dict[str, Any]] = []
    if not smoke.get("ok"):
        findings.append(_finding("error", "smoke_failed", "Plugin smoke check failed."))
    if surface_count <= 0:
        findings.append(_finding("error", "no_surface", "Plugin exposes no usable surface."))
    if permission_resolution.get("review_required"):
        findings.append(_finding(
            "warning",
            "permission_review_required",
            "Plugin permissions are inferred and need operator review.",
        ))
    if surfaces.get("mcp") and not permission_resolution.get("permissions"):
        findings.append(_finding(
            "warning",
            "mcp_without_permission",
            "MCP-capable plugin has no explicit permission record.",
        ))
    if surfaces.get("commands") and "on_execute" not in lifecycle_hooks:
        findings.append(_finding(
            "warning",
            "command_without_execute_hook",
            "Command-capable plugin should declare an execute lifecycle hook.",
        ))
    if trust.get("signed") is not True:
        findings.append(_finding(
            "info",
            "unsigned_local_plugin",
            "Local plugin is not signed; keep it in local review mode.",
        ))
    if trust.get("signed") is True and not isinstance(trust.get("provenance"), dict):
        findings.append(_finding(
            "warning",
            "signed_without_provenance",
            "Signed plugin is missing a materialized provenance record.",
        ))
    score = _row_score(findings, surface_count=surface_count)
    return {
        "plugin_id": plugin.get("id"),
        "plugin_name": plugin.get("name"),
        "score": score,
        "verdict": _row_verdict(findings, score),
        "surface_count": surface_count,
        "surfaces": surfaces,
        "trust": trust,
        "provenance": trust.get("provenance") if isinstance(trust.get("provenance"), dict) else {},
        "permission_resolution": permission_resolution,
        "lifecycle_hooks": lifecycle_hooks,
        "finding_codes": [finding["code"] for finding in findings],
        "findings": findings,
    }


def _lifecycle_hooks(plugin: dict[str, Any]) -> list[str]:
    raw = plugin.get("lifecycle_hooks")
    if isinstance(raw, list):
        return sorted(str(item) for item in raw if str(item or "").strip())
    # Codex-format plugins do not all expose lifecycle metadata yet. Derive a
    # conservative local-review hook profile from the discovered surfaces.
    smoke = plugin.get("smoke") if isinstance(plugin.get("smoke"), dict) else {}
    surfaces = smoke.get("surfaces") if isinstance(smoke.get("surfaces"), dict) else {}
    hooks = ["on_load", "on_unload"]
    if any(surfaces.get(key) for key in ("mcp", "commands", "apps")):
        hooks.append("on_execute")
    if surfaces.get("skills"):
        hooks.append("on_skill_register")
    return hooks


def _row_score(findings: list[dict[str, Any]], *, surface_count: int) -> float:
    if surface_count <= 0:
        return 0.0
    penalty = 0.0
    for finding in findings:
        severity = finding["severity"]
        if severity == "error":
            penalty += 0.45
        elif severity == "warning":
            penalty += 0.18
        else:
            penalty += 0.04
    return round(max(0.0, 1.0 - penalty), 3)


def _row_verdict(findings: list[dict[str, Any]], score: float) -> str:
    if any(finding["severity"] == "error" for finding in findings):
        return "fail"
    if score >= 0.9 and not any(finding["severity"] == "warning" for finding in findings):
        return "pass"
    return "review"


def _score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return round(sum(float(row.get("score") or 0.0) for row in rows) / len(rows), 3)


def _verdict(score: float, fail_count: int, review_count: int, total: int) -> str:
    if total <= 0 or fail_count > 0:
        return "fail"
    if review_count > 0 or score < 0.9:
        return "review"
    return "pass"


def _requirements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": "plugins_discovered",
            "passed": bool(rows),
            "detail": f"{len(rows)} plugin(s) discovered",
        },
        {
            "id": "no_failed_lifecycle_audits",
            "passed": all(row["verdict"] != "fail" for row in rows) if rows else False,
            "detail": f"{sum(1 for row in rows if row['verdict'] == 'fail')} failed plugin audit(s)",
        },
        {
            "id": "permission_review_visible",
            "passed": all(
                isinstance(row.get("permission_resolution"), dict)
                and row["permission_resolution"].get("schema")
                == "octopus.codex_plugin_permission_resolution.v1"
                for row in rows
            ) if rows else False,
            "detail": "permission review state is materialized for each plugin",
        },
        {
            "id": "lifecycle_hooks_visible",
            "passed": all(row.get("lifecycle_hooks") for row in rows) if rows else False,
            "detail": "lifecycle hooks are visible for each plugin",
        },
        {
            "id": "provenance_visible",
            "passed": all(
                isinstance(row.get("trust"), dict)
                and (
                    row["trust"].get("signed") is not True
                    or isinstance(row["trust"].get("provenance"), dict)
                )
                for row in rows
            ) if rows else False,
            "detail": "signed plugin provenance is materialized for every signed plugin",
        },
    ]


def _next_actions(rows: list[dict[str, Any]], *, total: int) -> list[str]:
    if total <= 0:
        return ["Install or enable at least one local Codex-compatible plugin."]
    actions: list[str] = []
    for row in rows:
        if row["verdict"] == "pass":
            continue
        plugin_id = row.get("plugin_id") or "plugin"
        for code in row.get("finding_codes") or []:
            actions.append(f"Resolve {code} for plugin {plugin_id}.")
            if len(actions) >= 6:
                return actions
    return actions


def _finding(severity: str, code: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message}


__all__ = ["audit_plugin_lifecycle"]
