"""CLI-team router · ``/api/cli-team/*``.

Backs the work-mode "run a team of my external coding CLIs" panel:
  * ``GET  /api/cli-team/status`` — which drivable CLIs (Claude/Codex/Trae/Qoder) are
    installed here, and is the workspace a git repo (worktree isolation needs it).
  * ``POST /api/cli-team/run``    — run them all on a goal, each in its own
    isolated worktree + shared blackboard, and return every agent's diff for a
    diff-first review (Conductor style — the user picks; nothing is auto-merged).

Diff-first by design: the route returns all candidates rather than auto-judging,
so a human reviews in the UI. (The planner-facing ``cli_team`` skill adds the
vote-judge.) Best-effort — never 500s on a missing CLI / non-git workspace.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from fastapi import APIRouter, Depends, Request
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi

class CliTeamRunRequest(BaseModel):
    goal: str = ""
    repo_root: str | None = None


def create_cli_team_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    """Build + return the router. ``app.include_router(create_cli_team_router())``."""
    require_fastapi(__name__)

    def _auth_dep(request: Request) -> None:
        # The CLI-team panel can spawn external coding CLIs across
        # isolated worktrees. That is operator-only surface area in
        # deployed mode, while local dev keeps the old friction-free
        # behavior when require_auth=False.
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["cli-team"], dependencies=[Depends(_auth_dep)])

    @router.get("/api/cli-team/status")
    def api_cli_team_status() -> dict[str, Any]:
        from runtime.execution.agents.cli_team import detect_installed_partners
        from runtime.execution.subagents.worktree_loop import is_git_repo

        cwd = os.getcwd()
        return {
            "detected": detect_installed_partners(),
            "repo_root": cwd,
            "is_git_repo": is_git_repo(cwd),
        }

    @router.post("/api/cli-team/run")
    def api_cli_team_run(body: CliTeamRunRequest) -> dict[str, Any]:
        from runtime.execution.agents.cli_team import detect_installed_partners, run_cli_team

        goal = (body.goal or "").strip()
        if not goal:
            return {"ok": False, "error": "goal is required", "members": []}
        members = detect_installed_partners()
        if not members:
            return {
                "ok": False,
                "error": (
                    "no installed coding-agent CLI detected "
                    "(install Claude Code, Codex, Trae CLI, or Qoder CLI)"
                ),
                "members": [],
            }
        root = body.repo_root or os.getcwd()
        # Diff-first: run the team and return every candidate; the UI reviews.
        return run_cli_team(goal, members, repo_root=root, turn_id=None)

    return router
