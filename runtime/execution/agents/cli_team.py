"""Run a team of external CLI agents in parallel, each in its own git worktree.

The Conductor / orca pattern, built on octopus's own pieces: each black-box CLI
agent (Claude Code / Codex / Trae / Qoder) runs ISOLATED in its own worktree off HEAD (no
clobbering), briefed FROM and harvesting TO the shared blackboard (stigmergy at
the I/O boundary — never touching the agent's internal context). Every agent's
diff + output is captured for review; this NEVER auto-merges — reconciling
parallel edits is a human / judge call (see the ``tournament`` skill).

Composes ``worktree_scope`` (isolation) + ``run_local_partner`` (the CLI bridge)
+ the blackboard envelope. The partner runner is injectable so the orchestration
is unit-testable against a real git repo without any CLI installed.
"""

from __future__ import annotations

import concurrent.futures as _cf
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from runtime.execution.agents.local_partner_bridge import (
    LocalPartnerResult,
    blackboard_brief,
    harvest_to_blackboard,
    run_local_partner,
)
from runtime.execution.subagents.worktree_loop import is_git_repo, worktree_scope

_MAX_MEMBERS = 6
_DIFF_PREVIEW_CHARS = 1200

# Matches run_local_partner's keyword call shape; injectable for tests.
PartnerRunner = Callable[..., LocalPartnerResult]


# Drivable CLI agents → the commands that launch them (mirrors build_partner_argv).
_KNOWN_PARTNERS: dict[str, list[str]] = {
    "claude-code": ["claude", "claude.cmd", "claude.exe"],
    "codex-cli": ["codex", "codex.cmd", "codex.exe"],
    "trae-cli": ["trae-cli", "traecli", "trae-agent", "ta", "trae", "trae.cmd", "trae.exe"],
    "qoder-cli": ["qodercli", "qoder", "qoder-cli", "qodercli.cmd", "qodercli.exe"],
    "codebuddy-cli": ["codebuddy", "codebuddy-code", "cbc", "codebuddy.cmd", "codebuddy.exe"],
}


def detect_installed_partners() -> list[dict[str, str]]:
    """Discover the drivable coding-agent CLIs actually on this machine (via
    ``shutil.which``) as team members — ``[]`` if none. Self-contained: no agent
    registry / gateway needed, so a skill can auto-assemble the team."""
    members: list[dict[str, str]] = []
    for partner_id, commands in _KNOWN_PARTNERS.items():
        for cmd in commands:
            path = shutil.which(cmd)
            if path:
                members.append(
                    {
                        "agent_id": f"local_{partner_id.replace('-', '_')}",
                        "partner_id": partner_id,
                        "command": path,
                    }
                )
                break
    return members


def select_cli_members(
    assignee_refs: list[str] | None,
    *,
    detected: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Of the coding-agent CLIs installed on this machine, return those whose
    ``agent_id`` is in ``assignee_refs`` — i.e. the team task's ``local_*``
    members that are actually runnable here. Empty when none match, so callers
    fall back to the normal (non-CLI) team path.

    Used by the team-task dispatcher: a task assigned to ``local_codex_cli``
    routes through :func:`run_cli_team` instead of the role topology.
    """
    wanted = {str(r).strip() for r in (assignee_refs or []) if str(r).strip()}
    if not wanted:
        return []
    pool = detect_installed_partners() if detected is None else detected
    return [m for m in pool if str(m.get("agent_id") or "") in wanted]


def _slug(text: str, fallback: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(text))[:32].strip("-")
    return cleaned or fallback


def _capture_diff(worktree: str) -> tuple[str, list[str]]:
    def _g(*args: str) -> str:
        return subprocess.run(  # noqa: S603,S607 — fixed git argv, no shell
            ["git", "-C", worktree, *args],
            capture_output=True,
            text=True,
            check=False,
        ).stdout

    _g("add", "-A")
    diff = _g("diff", "--cached")
    names = _g("diff", "--cached", "--name-only")
    return diff, [line for line in names.split("\n") if line.strip()]


def _member_label(member: dict[str, Any]) -> str:
    agent_id = str(member.get("agent_id") or "")
    partner_id = str(member.get("partner_id") or "")
    return agent_id or partner_id or "member"


def _summarize_cli_team(goal: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    succeeded = sum(1 for r in results if r.get("ok"))
    failed = count - succeeded
    changed_files = sorted(
        {
            str(path)
            for r in results
            for path in (r.get("files") or [])
            if str(path).strip()
        }
    )
    successful_members = [_member_label(r) for r in results if r.get("ok")]
    failed_members = [
        {
            "agent_id": str(r.get("agent_id") or ""),
            "partner_id": str(r.get("partner_id") or ""),
            "failure_kind": str(r.get("failure_kind") or "unknown"),
            "failure_title": str(r.get("failure_title") or ""),
            "fix_hint": str(r.get("fix_hint") or ""),
            "error": str(r.get("raw_error") or r.get("error") or ""),
        }
        for r in results
        if not r.get("ok")
    ]
    if succeeded and failed:
        next_action = "review_successes_retry_failed"
    elif succeeded and changed_files:
        next_action = "review_diffs_choose_winner"
    elif succeeded:
        next_action = "review_outputs"
    elif failed_members and any(
        m["failure_kind"] in {"auth", "model", "missing_binary", "network", "permission"}
        for m in failed_members
    ):
        next_action = "fix_cli_setup_and_retry"
    else:
        next_action = "open_native_cli_or_retry"

    lines = [f"CLI team finished: {succeeded}/{count} member(s) succeeded."]
    if changed_files:
        shown = ", ".join(changed_files[:6])
        if len(changed_files) > 6:
            shown += f", +{len(changed_files) - 6} more"
        lines.append(f"Changed files: {shown}.")
    if successful_members:
        lines.append(f"Succeeded: {', '.join(successful_members)}.")
    if failed_members:
        failure_bits = []
        for m in failed_members[:4]:
            label = m["agent_id"] or m["partner_id"] or "member"
            title = m["failure_title"] or m["failure_kind"]
            failure_bits.append(f"{label} → {title}")
        extra = "" if len(failed_members) <= 4 else f", +{len(failed_members) - 4} more"
        lines.append(f"Needs attention: {', '.join(failure_bits)}{extra}.")
    lines.append("Diffs are isolated worktree candidates; nothing was auto-merged.")
    return {
        "summary": " ".join(lines),
        "summary_lines": lines,
        "next_action": next_action,
        "changed_files": changed_files,
        "successful_members": successful_members,
        "failed_members": failed_members,
        "failed": failed,
        "goal": goal[:240],
    }


def run_cli_team(
    goal: str,
    members: list[dict[str, str]],
    *,
    repo_root: str,
    turn_id: str | None = None,
    timeout: float = 240.0,
    max_workers: int = 4,
    partner_runner: PartnerRunner | None = None,
) -> dict[str, Any]:
    """Run each member — a local-partner agent ``{agent_id, partner_id, command}``
    — in its own worktree with the blackboard envelope. Returns per-member
    ``{agent_id, partner_id, ok, output, diff, files, error}``. Never merges."""
    goal = (goal or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required", "members": [], "count": 0}
    if not is_git_repo(repo_root):
        return {"ok": False, "error": f"not a git repo: {repo_root}", "members": [], "count": 0}
    clean = [
        m
        for m in (members or [])
        if isinstance(m, dict) and m.get("partner_id") and m.get("command")
    ][:_MAX_MEMBERS]
    if not clean:
        return {"ok": False, "error": "no runnable members", "members": [], "count": 0}

    run = partner_runner or run_local_partner

    def _run_one(index: int, m: dict[str, str]) -> dict[str, Any]:
        agent_id = str(m.get("agent_id") or m.get("partner_id") or f"agent{index}")
        partner_id = str(m["partner_id"])
        command = str(m["command"])
        rec: dict[str, Any] = {
            "agent_id": agent_id,
            "partner_id": partner_id,
            "ok": False,
            "output": "",
            "diff": "",
            "diff_preview": "",
            "files": [],
            "error": None,
            "raw_error": None,
            "failure_kind": None,
            "failure_title": "",
            "fix_hint": "",
        }
        try:
            with worktree_scope(repo_root, f"{index}-{_slug(agent_id, f'a{index}')}") as (path, _b):
                brief = blackboard_brief(turn_id)
                prompt = goal if not brief else f"{brief}\n\n---\n\n{goal}"
                env = (
                    {"OCTOPUS_TURN_ID": str(turn_id), "OCTOPUS_AGENT_ID": agent_id}
                    if turn_id
                    else None
                )
                res = run(
                    partner_id=partner_id,
                    command=command,
                    prompt=prompt,
                    cwd=path,
                    timeout=timeout,
                    env=env,
                )
                rec["ok"] = bool(res.ok)
                rec["output"] = res.output
                rec["error"] = res.error or None
                rec["raw_error"] = res.raw_error or None
                rec["failure_kind"] = res.failure_kind
                rec["failure_title"] = res.failure_title
                rec["fix_hint"] = res.fix_hint
                rec["diff"], rec["files"] = _capture_diff(path)
                if rec["diff"]:
                    rec["diff_preview"] = str(rec["diff"])[:_DIFF_PREVIEW_CHARS]
                if res.ok:
                    harvest_to_blackboard(turn_id, agent_id, res.output)
        except Exception as exc:  # noqa: BLE001 — one member's failure is isolated
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["raw_error"] = rec["error"]
            rec["failure_kind"] = "execution_exception"
            rec["failure_title"] = "CLI team member crashed before producing a candidate"
            rec["fix_hint"] = "Check the local worktree setup and rerun this member from its native CLI."
        return rec

    results: list[dict[str, Any]] = []
    workers = max(1, min(int(max_workers), len(clean)))
    with _cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cli-team") as pool:
        futures = [pool.submit(_run_one, i, m) for i, m in enumerate(clean)]
        for fut in _cf.as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r["agent_id"])
    succeeded = sum(1 for r in results if r["ok"])
    summary = _summarize_cli_team(goal, results)
    return {
        "ok": succeeded > 0,
        "goal": summary["goal"],
        "members": results,
        "count": len(results),
        "succeeded": succeeded,
        "failed": summary["failed"],
        "summary": summary["summary"],
        "summary_lines": summary["summary_lines"],
        "next_action": summary["next_action"],
        "changed_files": summary["changed_files"],
        "successful_members": summary["successful_members"],
        "failed_members": summary["failed_members"],
        "note": "diffs are NOT merged — review each, or use tournament to judge a winner",
    }
