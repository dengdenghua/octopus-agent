from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root


@dataclass(frozen=True)
class ReadinessTopic:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]


REQUIRED_TOPICS: tuple[ReadinessTopic, ...] = (
    ReadinessTopic(
        id="code_mode",
        title="Code mode",
        path="docs/guide/operator-readiness.md",
        required_terms=("code mode", "inspect", "edit", "verify"),
    ),
    ReadinessTopic(
        id="permissions",
        title="Permissions",
        path="docs/guide/operator-readiness.md",
        required_terms=("permission", "approval", "sandbox", "override"),
    ),
    ReadinessTopic(
        id="replay_gates",
        title="Replay gates",
        path="docs/guide/operator-readiness.md",
        required_terms=("replay gate", "promotion", "evidence", "audit"),
    ),
    ReadinessTopic(
        id="plugins",
        title="Plugins",
        path="docs/guide/operator-readiness.md",
        required_terms=("plugin", "smoke", "permission review", "hook"),
    ),
    ReadinessTopic(
        id="plugin_author_migration",
        title="Plugin author migration",
        path="docs/guide/plugin-author-migration.md",
        required_terms=(
            "compatibility",
            "migration",
            "permission review",
            "release checklist",
        ),
    ),
)


def compute_ecosystem_readiness(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    topics = [_topic_status(base, topic) for topic in REQUIRED_TOPICS]
    present = sum(1 for topic in topics if topic["passed"])
    total = len(topics)
    score = round(present / total, 3) if total else 0.0
    return {
        "schema": "octopus.ecosystem_readiness.v1",
        "score": score,
        "passed": present,
        "total": total,
        "ready": present == total,
        "missing_count": total - present,
        "topics": topics,
        "next_actions": _next_actions(topics),
    }


def _topic_status(base: Path, topic: ReadinessTopic) -> dict[str, Any]:
    path = base / topic.path
    text = path.read_text(encoding="utf-8").lower() if path.exists() else ""
    missing_terms = [
        term
        for term in topic.required_terms
        if term.lower() not in text
    ]
    return {
        "id": topic.id,
        "title": topic.title,
        "path": topic.path,
        "exists": path.exists(),
        "passed": path.exists() and not missing_terms,
        "required_terms": list(topic.required_terms),
        "missing_terms": missing_terms,
    }


def _next_actions(topics: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for topic in topics:
        if topic["passed"]:
            continue
        if not topic["exists"]:
            actions.append(f"Create {topic['path']} for {topic['title']}.")
        elif topic["missing_terms"]:
            actions.append(
                f"Update {topic['path']} with {', '.join(topic['missing_terms'])}."
            )
    return actions


__all__ = [
    "REQUIRED_TOPICS",
    "ReadinessTopic",
    "compute_ecosystem_readiness",
]
