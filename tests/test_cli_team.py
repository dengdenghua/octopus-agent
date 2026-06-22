"""A team of external CLI agents in parallel isolated worktrees (real git, fake CLI)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from runtime.execution.agents.cli_team import run_cli_team
from runtime.execution.agents.local_partner_bridge import LocalPartnerResult


def _git_repo(tmp_path: Path) -> str:
    def g(*a: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "README.md").write_text("x")
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    return str(tmp_path)


_MEMBERS = [
    {"agent_id": "a_claude", "partner_id": "claude-code", "command": "claude"},
    {"agent_id": "a_codex", "partner_id": "codex-cli", "command": "codex"},
]


def test_each_member_runs_isolated_and_diff_is_captured(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    seen: list[dict] = []

    def fake_runner(*, partner_id, command, prompt, cwd, timeout=None, env=None):
        seen.append({"partner_id": partner_id, "prompt": prompt, "env": env})
        # the "CLI" edits a file inside ITS OWN worktree (cwd), not the main repo
        (Path(cwd) / f"{partner_id}.txt").write_text(f"edit by {partner_id}\n")
        return LocalPartnerResult(ok=True, output=f"{partner_id} done", exit_code=0)

    out = run_cli_team(
        "implement X", _MEMBERS, repo_root=repo, turn_id="turn-1", partner_runner=fake_runner
    )
    assert out["ok"] is True
    assert out["count"] == 2 and out["succeeded"] == 2
    by = {m["agent_id"]: m for m in out["members"]}
    assert by["a_claude"]["ok"] and "claude-code.txt" in by["a_claude"]["diff"]
    assert by["a_codex"]["ok"] and "codex-cli.txt" in by["a_codex"]["diff"]
    # every member got the turn env so it can reach `octopus bb`
    assert all(s["env"]["OCTOPUS_TURN_ID"] == "turn-1" for s in seen)
    # ISOLATION: candidate edits never landed in the main repo
    assert not (Path(repo) / "claude-code.txt").exists()
    assert not (Path(repo) / "codex-cli.txt").exists()


def test_outputs_harvested_to_shared_blackboard(tmp_path: Path) -> None:
    from runtime.memory.runtime_state.blackboard import get_blackboard

    repo = _git_repo(tmp_path)

    def fake_runner(*, partner_id, command, prompt, cwd, timeout=None, env=None):
        return LocalPartnerResult(ok=True, output=f"{partner_id} did the thing", exit_code=0)

    run_cli_team("g", _MEMBERS, repo_root=repo, turn_id="turn-bb", partner_runner=fake_runner)
    board = get_blackboard("turn-bb")
    assert "did the thing" in str(board.read("partner.a_claude.output"))
    assert "did the thing" in str(board.read("partner.a_codex.output"))


def test_one_member_failure_is_isolated(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    def fake_runner(*, partner_id, command, prompt, cwd, timeout=None, env=None):
        if partner_id == "codex-cli":
            return LocalPartnerResult(ok=False, error="not logged in", exit_code=1)
        (Path(cwd) / "ok.txt").write_text("done")
        return LocalPartnerResult(ok=True, output="ok", exit_code=0)

    out = run_cli_team("g", _MEMBERS, repo_root=repo, partner_runner=fake_runner)
    by = {m["agent_id"]: m for m in out["members"]}
    assert by["a_claude"]["ok"] is True
    assert by["a_codex"]["ok"] is False and "not logged in" in by["a_codex"]["error"]
    assert out["succeeded"] == 1 and out["ok"] is True  # team ok if anyone succeeded


def test_guards(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    assert run_cli_team("", _MEMBERS, repo_root=repo)["ok"] is False  # no goal
    assert run_cli_team("g", [], repo_root=repo)["ok"] is False  # no members
    assert run_cli_team("g", _MEMBERS, repo_root=str(tmp_path / "nope"))["ok"] is False  # not git


# ── detection + the reachable cli_team skill (judge) ──────────────────


def test_detect_installed_partners(monkeypatch) -> None:
    from runtime.execution.agents import cli_team as ct

    monkeypatch.setattr(
        ct.shutil, "which", lambda c: f"/usr/bin/{c}" if c in ("claude", "codex") else None
    )
    mems = ct.detect_installed_partners()
    assert {m["partner_id"] for m in mems} == {"claude-code", "codex-cli"}
    assert all(m["command"].startswith("/usr/bin/") for m in mems)


def test_detect_none_when_nothing_installed(monkeypatch) -> None:
    from runtime.execution.agents import cli_team as ct

    monkeypatch.setattr(ct.shutil, "which", lambda _c: None)
    assert ct.detect_installed_partners() == []


def test_cli_team_skill_judges_a_winner(monkeypatch) -> None:
    from runtime.execution.agents import cli_team as ct
    from runtime.execution.suckers import delegation_skills as ds

    monkeypatch.setattr(
        ct,
        "detect_installed_partners",
        lambda: [
            {"agent_id": "local_claude_code", "partner_id": "claude-code", "command": "claude"},
            {"agent_id": "local_codex_cli", "partner_id": "codex-cli", "command": "codex"},
        ],
    )
    monkeypatch.setattr(
        ct,
        "run_cli_team",
        lambda goal, members, **kw: {
            "ok": True,
            "count": 2,
            "succeeded": 2,
            "members": [
                {"agent_id": "local_claude_code", "partner_id": "claude-code", "ok": True, "diff": "diff A", "files": ["a.py"]},
                {"agent_id": "local_codex_cli", "partner_id": "codex-cli", "ok": True, "diff": "diff B", "files": ["b.py"]},
            ],
        },
    )
    monkeypatch.setattr(
        ds, "_call_agent_vote",
        lambda **kw: {"ok": True, "verdict": "local_codex_cli", "confidence": 0.8, "votes": []},
    )
    r = ds._run_cli_team(goal="implement X")
    assert r["ok"] is True
    assert r["winner"]["agent_id"] == "local_codex_cli"
    assert r["winner"]["diff"] == "diff B"
    assert r["count"] == 2
    assert {m["agent_id"] for m in r["members"]} == {"local_claude_code", "local_codex_cli"}


def test_cli_team_skill_errors(monkeypatch) -> None:
    from runtime.execution.agents import cli_team as ct
    from runtime.execution.suckers import delegation_skills as ds

    assert ds._run_cli_team(goal="")["ok"] is False  # missing goal
    monkeypatch.setattr(ct, "detect_installed_partners", lambda: [])
    r = ds._run_cli_team(goal="x")
    assert r["ok"] is False and "no installed" in r["error"]  # none detected
