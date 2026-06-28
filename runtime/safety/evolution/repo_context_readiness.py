from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.memory.hemolymph.repo_context import retrieve_repo_context
from runtime.platform.process.paths import project_root as default_project_root

_SCHEMA = "octopus.repo_context_readiness.v1"
_PROBE_SCHEMA = "octopus.repo_context_probe.v1"
_DIRTY_PROBE_SCHEMA = "octopus.repo_dirty_worktree_probe.v1"


@dataclass(frozen=True)
class RepoContextCapability:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


CAPABILITIES: tuple[RepoContextCapability, ...] = (
    RepoContextCapability(
        id="hybrid_wiki_retrieval",
        title="Hybrid project-wiki retrieval",
        path="runtime/memory/hemolymph/repo_context.py",
        required_terms=("retrieve_repo_context", "_rrf", "RELEVANT CODEBASE DOCS"),
        weight=3,
    ),
    RepoContextCapability(
        id="shared_codebase_grounding",
        title="Shared planner and chat codebase grounding",
        path="runtime/memory/hemolymph/repo_context.py",
        required_terms=(
            "build_codebase_context",
            "render_codebase_context",
            "collect_codebase_sources",
        ),
        weight=2,
    ),
    RepoContextCapability(
        id="react_loop_grounding",
        title="Interactive code-mode grounding",
        path="runtime/core/cerebrum/react_loop.py",
        required_terms=(
            "build_codebase_context",
            "_grounding_sources",
            "Codebase grounding",
        ),
        weight=2,
    ),
    RepoContextCapability(
        id="planner_grounding",
        title="Planner codebase grounding",
        path="runtime/core/cerebrum/llm_planner.py",
        required_terms=("render_codebase_context", "_render_codebase_section"),
        weight=2,
    ),
    RepoContextCapability(
        id="working_set_resume",
        title="Trace-backed working-set resume",
        path="runtime/memory/diagnostics/trace_store.py",
        required_terms=("working_set", "resume", "Rehydrate"),
        weight=2,
    ),
    RepoContextCapability(
        id="memory_quality_recall",
        title="Learning-memory quality recall",
        path="runtime/memory/learning/experience_ledger.py",
        required_terms=(
            "octopus.experience_memory_quality_summary.v1",
            "memory_quality",
            "reliability",
        ),
        weight=2,
    ),
)


def compute_repo_context_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    capabilities = [_capability_status(base, capability) for capability in CAPABILITIES]
    probe = run_repo_context_probe() if include_probe else _skipped_probe()
    capabilities.extend(_probe_capabilities(probe))
    total_weight = sum(int(item["weight"]) for item in capabilities)
    passed_weight = sum(int(item["weight"]) for item in capabilities if item["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [item for item in capabilities if not item["passed"]]
    return {
        "schema": _SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing,
        "verdict": "pass" if score >= 1.0 and not missing else "review",
        "passed": len(capabilities) - len(missing),
        "total": len(capabilities),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "capabilities": capabilities,
        "missing_count": len(missing),
        "probe": probe,
        "next_actions": _next_actions(missing),
        "calibration": {
            "schema": "octopus.repo_context_calibration.v1",
            "compares_to": {
                "claude_code": (
                    "strong project-local context, file tracking, and tool-aware "
                    "continuity"
                ),
                "cursor": (
                    "fast IDE-native repository navigation and broad codebase "
                    "awareness"
                ),
            },
            "octopus_edge": (
                "shared wiki+source grounding across planner and chat, trace-backed "
                "working-set resume, and replay-linked learning memory quality"
            ),
        },
    }


def run_repo_context_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="octo-repo-context-") as tmp:
        wiki_dir = _make_probe_wiki(Path(tmp))
        english_sink: list[dict[str, str]] = []
        chinese_sink: list[dict[str, str]] = []
        english = retrieve_repo_context(
            "how does ToolEngine execute shell commands",
            wiki_dir=wiki_dir,
            _sink=english_sink,
        )
        chinese = retrieve_repo_context(
            "帮我改简历关键词",
            wiki_dir=wiki_dir,
            _sink=chinese_sink,
        )
        dirty_probe = _run_dirty_worktree_probe(Path(tmp) / "dirty-worktree")
    english_ok = bool(
        english
        and "Tool engine execution" in english
        and any(item.get("path") == "tool-engine.md" for item in english_sink)
    )
    chinese_ok = bool(
        chinese
        and "Resume keyword optimizer" in chinese
        and any(item.get("path") == "resume-cn.md" for item in chinese_sink)
    )
    sink_ok = bool(english_sink and chinese_sink)
    return {
        "schema": _PROBE_SCHEMA,
        "ok": english_ok and chinese_ok and sink_ok,
        "english_identifier_retrieval": english_ok,
        "cjk_bigram_retrieval": chinese_ok,
        "source_sink_fidelity": sink_ok,
        "dirty_worktree_awareness": dirty_probe.get("ok") is True,
        "english_sources": english_sink,
        "chinese_sources": chinese_sink,
        "dirty_worktree_probe": dirty_probe,
    }


def _make_probe_wiki(base: Path) -> Path:
    wiki = base / "docs" / "auto"
    wiki.mkdir(parents=True, exist_ok=True)
    pages = [
        (
            "Tool engine execution",
            "tool-engine.md",
            (
                "ToolEngine executes shell commands through scoped tool runners, "
                "records approvals, and captures working set evidence."
            ),
        ),
        (
            "Resume keyword optimizer",
            "resume-cn.md",
            "简历关键词优化流程会抽取岗位词、改写项目经历，并保留证据。",
        ),
        (
            "Browser operations",
            "browser.md",
            "Playwright browser operations inspect pages and screenshots.",
        ),
    ]
    tree: list[dict[str, str]] = []
    for title, rel, body in pages:
        (wiki / rel).write_text(body, encoding="utf-8")
        tree.append({"type": "doc", "title": title, "path": rel})
    (wiki / "index.json").write_text(
        json.dumps({"version": 2, "tree": tree}, ensure_ascii=False),
        encoding="utf-8",
    )
    return wiki


def _probe_capabilities(probe: dict[str, Any]) -> list[dict[str, Any]]:
    if probe.get("skipped"):
        return [
            _dynamic_capability(
                "repo_context_probe",
                "Offline repo-context probe",
                False,
                "probe skipped",
                weight=5,
            )
        ]
    return [
        _dynamic_capability(
            "english_identifier_probe",
            "English identifier retrieval probe",
            bool(probe.get("english_identifier_retrieval")),
            "ToolEngine-style identifier query retrieves the right wiki page",
            weight=2,
        ),
        _dynamic_capability(
            "cjk_bigram_probe",
            "CJK bigram retrieval probe",
            bool(probe.get("cjk_bigram_retrieval")),
            "Chinese partial-overlap query retrieves the right wiki page",
            weight=2,
        ),
        _dynamic_capability(
            "source_sink_probe",
            "Grounding source sink probe",
            bool(probe.get("source_sink_fidelity")),
            "retrieved prompt section exposes the exact source paths used",
            weight=1,
        ),
        _dynamic_capability(
            "dirty_worktree_probe",
            "Dirty worktree awareness probe",
            bool(probe.get("dirty_worktree_awareness")),
            "staged, unstaged, and untracked changes are detected without overwriting them",
            weight=2,
        ),
    ]


def _dynamic_capability(
    capability_id: str,
    title: str,
    passed: bool,
    detail: str,
    *,
    weight: int,
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "title": title,
        "path": None,
        "weight": weight,
        "exists": True,
        "passed": passed,
        "required_terms": [],
        "missing_terms": [] if passed else [detail],
        "detail": detail,
    }


def _capability_status(base: Path, capability: RepoContextCapability) -> dict[str, Any]:
    path = base / capability.path
    text = _read_text(path).lower() if path.exists() else ""
    missing_terms = [
        term for term in capability.required_terms
        if term.lower() not in text
    ]
    return {
        "id": capability.id,
        "title": capability.title,
        "path": capability.path,
        "weight": capability.weight,
        "exists": path.exists(),
        "passed": path.exists() and not missing_terms,
        "required_terms": list(capability.required_terms),
        "missing_terms": missing_terms,
    }


def _next_actions(missing: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in missing:
        path = item.get("path")
        if path and not item["exists"]:
            actions.append(f"Add {path} for {item['title']}.")
        elif item["missing_terms"]:
            actions.append(
                f"Update {path or item['id']} with "
                f"{', '.join(item['missing_terms'])}."
            )
    return actions


def _skipped_probe() -> dict[str, Any]:
    return {
        "schema": _PROBE_SCHEMA,
        "ok": False,
        "skipped": True,
        "reason": "include_probe=False",
    }


def _run_dirty_worktree_probe(base: Path) -> dict[str, Any]:
    try:
        base.mkdir(parents=True, exist_ok=True)
        _git(base, "init")
        _git(base, "config", "user.email", "octopus-probe@example.invalid")
        _git(base, "config", "user.name", "Octopus Probe")
        (base / "tracked.txt").write_text("base\n", encoding="utf-8")
        (base / "staged.txt").write_text("base\n", encoding="utf-8")
        _git(base, "add", "tracked.txt", "staged.txt")
        _git(base, "commit", "-m", "base")
        (base / "staged.txt").write_text("base\nstaged change\n", encoding="utf-8")
        _git(base, "add", "staged.txt")
        (base / "tracked.txt").write_text("base\nunstaged change\n", encoding="utf-8")
        (base / "untracked.txt").write_text("new file\n", encoding="utf-8")
        raw = _git(base, "status", "--porcelain=v1", "--branch").stdout
        parsed = _parse_porcelain_status(raw)
        staged_count = parsed["staged_count"]
        unstaged_count = parsed["unstaged_count"]
        untracked_count = parsed["untracked_count"]
        ok = staged_count >= 1 and unstaged_count >= 1 and untracked_count >= 1
        return {
            "schema": _DIRTY_PROBE_SCHEMA,
            "ok": ok,
            "protected_user_changes": ok,
            "staged_count": staged_count,
            "unstaged_count": unstaged_count,
            "untracked_count": untracked_count,
            "paths_by_status": parsed["paths_by_status"],
            "dirty_summary": (
                f"{staged_count} staged, {unstaged_count} unstaged, "
                f"{untracked_count} untracked"
            ),
            "raw": raw,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": _DIRTY_PROBE_SCHEMA,
            "ok": False,
            "protected_user_changes": False,
            "error": str(exc),
            "staged_count": 0,
            "unstaged_count": 0,
            "untracked_count": 0,
            "paths_by_status": {},
        }


def _git(base: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=base,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _parse_porcelain_status(raw: str) -> dict[str, Any]:
    paths_by_status: dict[str, list[str]] = {
        "staged": [],
        "unstaged": [],
        "untracked": [],
    }
    for line in str(raw or "").splitlines():
        if not line or line.startswith("##"):
            continue
        status = line[:2]
        path = line[3:].strip()
        if not path:
            continue
        if status == "??":
            paths_by_status["untracked"].append(path)
            continue
        if status[0] != " ":
            paths_by_status["staged"].append(path)
        if len(status) > 1 and status[1] != " ":
            paths_by_status["unstaged"].append(path)
    return {
        "staged_count": len(paths_by_status["staged"]),
        "unstaged_count": len(paths_by_status["unstaged"]),
        "untracked_count": len(paths_by_status["untracked"]),
        "paths_by_status": paths_by_status,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "CAPABILITIES",
    "RepoContextCapability",
    "compute_repo_context_readiness",
    "run_repo_context_probe",
]
