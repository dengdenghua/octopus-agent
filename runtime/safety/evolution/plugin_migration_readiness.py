from __future__ import annotations

from pathlib import Path
from typing import Any

_SCHEMA = "octopus.plugin_migration_readiness.v1"
_PLUGIN_SCHEMA = "octopus.plugin_migration_contract.v1"
_CENTRAL_MIGRATION_PATH = Path("docs/guide/plugin-migration-matrix.md")
_CENTRAL_TEST_PATHS = (
    Path("tests/test_codex_plugin_smoke.py"),
    Path("tests/test_app_meta_endpoints.py"),
    Path("tests/test_apps_router.py"),
)


def compute_plugin_migration_readiness(
    *,
    plugins: list[dict[str, Any]],
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = _resolve_root(root=root, plugins=plugins)
    matrix_text = _read_text(base / _CENTRAL_MIGRATION_PATH)
    central_tests = _central_tests_present(base)
    rows = [
        _plugin_row(
            plugin,
            base=base,
            central_migration_text=matrix_text,
            central_tests=central_tests,
        )
        for plugin in plugins
        if isinstance(plugin, dict)
    ]
    total = len(rows)
    ready_count = sum(1 for row in rows if row["ready"])
    blocked_count = sum(1 for row in rows if row["blockers"])
    review_required_count = sum(
        1
        for row in rows
        if row["migration_contract"]["permission_review_status"] == "review_required"
    )
    score = round(ready_count / total, 3) if total else 0.0
    return {
        "schema": _SCHEMA,
        "total": total,
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "review_required_count": review_required_count,
        "score": score,
        "ready": total > 0 and blocked_count == 0,
        "central_contract": {
            "schema": "octopus.plugin_migration_contract_index.v1",
            "path": str(_CENTRAL_MIGRATION_PATH),
            "present": bool(matrix_text),
            "covered_count": sum(
                1
                for row in rows
                if row["migration_contract"]["central_migration_covered"]
            ),
            "central_tests_present": central_tests,
        },
        "plugins": rows,
        "next_actions": _next_actions(rows, total=total),
    }


def _plugin_row(
    plugin: dict[str, Any],
    *,
    base: Path,
    central_migration_text: str,
    central_tests: bool,
) -> dict[str, Any]:
    smoke = plugin.get("smoke") if isinstance(plugin.get("smoke"), dict) else {}
    surfaces = smoke.get("surfaces") if isinstance(smoke.get("surfaces"), dict) else {}
    permission = (
        smoke.get("permission_resolution")
        if isinstance(smoke.get("permission_resolution"), dict)
        else {}
    )
    plugin_path = Path(str(plugin.get("path") or ""))
    plugin_id = str(plugin.get("id") or plugin.get("name") or "")
    plugin_name = str(plugin.get("name") or plugin.get("id") or "")
    migration_notes_present = _has_any_file(
        plugin_path,
        ("MIGRATION.md", "MIGRATIONS.md", "CHANGELOG.md", "RELEASE.md", "README.md"),
    )
    central_migration_covered = _central_migration_covers(
        central_migration_text,
        plugin_id=plugin_id,
        plugin_name=plugin_name,
    )
    regression_tests_present = _has_regression_tests(plugin_path) or central_tests
    blockers: list[str] = []
    if not smoke:
        blockers.append("plugin smoke metadata missing")
    elif smoke.get("ok") is not True:
        blockers.extend(str(issue) for issue in smoke.get("issues") or [])
    if not any(bool(value) for value in surfaces.values()):
        blockers.append("plugin exposes no migration-testable runtime surface")
    if permission and "review_required" not in permission:
        blockers.append("plugin permission review status is not explicit")
    if not migration_notes_present and not central_migration_covered:
        blockers.append("plugin migration notes are missing")
    if not regression_tests_present:
        blockers.append("plugin regression tests are missing")

    warnings: list[str] = []
    if permission.get("review_required") is True:
        warnings.append("permission review remains required before production enablement")

    contract = {
        "schema": _PLUGIN_SCHEMA,
        "plugin_id": plugin_id,
        "plugin_name": plugin_name,
        "plugin_path": str(plugin.get("path") or ""),
        "version": str(plugin.get("version") or ""),
        "runtime_surfaces": {
            key: bool(surfaces.get(key))
            for key in ("capabilities", "skills", "apps", "mcp", "commands")
        },
        "permission_review_status": str(permission.get("status") or "unknown"),
        "permission_review_required": bool(permission.get("review_required")),
        "migration_notes_present": migration_notes_present,
        "central_migration_covered": central_migration_covered,
        "central_migration_path": str(_CENTRAL_MIGRATION_PATH),
        "regression_tests_present": regression_tests_present,
        "central_regression_tests_present": central_tests,
        "release_checklist": [
            "local_smoke_summary",
            "permission_review_visible",
            "runtime_surface_declared",
            "migration_notes",
            "regression_tests",
            "disable_without_state_corruption",
        ],
    }
    return {
        "schema": _PLUGIN_SCHEMA,
        "plugin_id": contract["plugin_id"],
        "plugin_name": contract["plugin_name"],
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "migration_contract": contract,
    }


def _has_any_file(root: Path, names: tuple[str, ...]) -> bool:
    if not root.is_dir():
        return False
    return any((root / name).is_file() for name in names)


def _has_regression_tests(root: Path) -> bool:
    if not root.is_dir():
        return False
    for dirname in ("tests", "test", "e2e"):
        candidate = root / dirname
        if candidate.is_dir() and any(candidate.rglob("*")):
            return True
    return any(root.glob("*.test.*")) or any(root.glob("test_*.py"))


def _resolve_root(*, root: str | Path | None, plugins: list[dict[str, Any]]) -> Path:
    if root is not None:
        return Path(root)
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        path = Path(str(plugin.get("path") or ""))
        for parent in (path, *path.parents):
            if (parent / "runtime").is_dir() and (parent / "tests").is_dir():
                return parent
    return Path.cwd()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        return ""


def _central_migration_covers(
    text: str,
    *,
    plugin_id: str,
    plugin_name: str,
) -> bool:
    if not text:
        return False
    needles = {plugin_id.strip().lower(), plugin_name.strip().lower()}
    needles.discard("")
    return any(f"`{needle}`" in text or f"| {needle} " in text for needle in needles)


def _central_tests_present(base: Path) -> bool:
    for relative in _CENTRAL_TEST_PATHS:
        path = base / relative
        text = _read_text(path)
        if not text:
            return False
        if "plugin" not in text:
            return False
    return True


def _next_actions(rows: list[dict[str, Any]], *, total: int) -> list[str]:
    if total <= 0:
        return ["Install or enable at least one plugin before release migration checks."]
    actions: list[str] = []
    for row in rows:
        plugin_id = str(row.get("plugin_id") or "plugin")
        for blocker in row.get("blockers") or []:
            if blocker in {
                "plugin migration notes are missing",
                "plugin regression tests are missing",
            }:
                continue
            actions.append(f"Fix {plugin_id}: {blocker}.")
        contract = row.get("migration_contract")
        contract = contract if isinstance(contract, dict) else {}
        if contract.get("migration_notes_present") is not True:
            actions.append(f"Add migration notes for {plugin_id}.")
        if contract.get("regression_tests_present") is not True:
            actions.append(f"Add plugin regression tests for {plugin_id}.")
        if len(actions) >= 6:
            break
    return actions


__all__ = [
    "compute_plugin_migration_readiness",
]
