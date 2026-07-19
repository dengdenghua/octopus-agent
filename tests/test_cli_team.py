"""A team of external CLI agents in parallel isolated worktrees (real git, fake CLI)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    {"agent_id": "a_trae", "partner_id": "trae-cli", "command": "trae-cli"},
    {"agent_id": "a_qoder", "partner_id": "qoder-cli", "command": "qodercli"},
    {"agent_id": "a_codebuddy", "partner_id": "codebuddy-cli", "command": "codebuddy"},
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
    assert out["count"] == 5 and out["succeeded"] == 5
    by = {m["agent_id"]: m for m in out["members"]}
    assert by["a_claude"]["ok"] and "claude-code.txt" in by["a_claude"]["diff"]
    assert by["a_codex"]["ok"] and "codex-cli.txt" in by["a_codex"]["diff"]
    assert by["a_trae"]["ok"] and "trae-cli.txt" in by["a_trae"]["diff"]
    assert by["a_qoder"]["ok"] and "qoder-cli.txt" in by["a_qoder"]["diff"]
    assert by["a_codebuddy"]["ok"] and "codebuddy-cli.txt" in by["a_codebuddy"]["diff"]
    # every member got the turn env so it can reach `octopus bb`
    assert all(s["env"]["OCTOPUS_TURN_ID"] == "turn-1" for s in seen)
    # ISOLATION: candidate edits never landed in the main repo
    assert not (Path(repo) / "claude-code.txt").exists()
    assert not (Path(repo) / "codex-cli.txt").exists()
    assert not (Path(repo) / "trae-cli.txt").exists()
    assert not (Path(repo) / "qoder-cli.txt").exists()
    assert not (Path(repo) / "codebuddy-cli.txt").exists()


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
            return LocalPartnerResult(
                ok=False,
                error=(
                    "Codex CLI 需要登录或授权\n"
                    "建议：请打开原生 CLI。\n\n"
                    "原始错误：\nnot logged in"
                ),
                raw_error="not logged in",
                exit_code=1,
                failure_kind="auth",
                failure_title="Codex CLI 需要登录或授权",
                fix_hint="请打开原生 CLI：`codex`，完成登录/授权后再让 Octopus 派工。",
            )
        (Path(cwd) / "ok.txt").write_text("done")
        return LocalPartnerResult(ok=True, output="ok", exit_code=0)

    out = run_cli_team("g", _MEMBERS, repo_root=repo, partner_runner=fake_runner)
    by = {m["agent_id"]: m for m in out["members"]}
    assert by["a_claude"]["ok"] is True
    assert by["a_codex"]["ok"] is False and "not logged in" in by["a_codex"]["error"]
    assert by["a_codex"]["failure_kind"] == "auth"
    assert by["a_codex"]["failure_title"] == "Codex CLI 需要登录或授权"
    assert by["a_codex"]["raw_error"] == "not logged in"
    assert out["succeeded"] == 4 and out["ok"] is True  # team ok if anyone succeeded
    assert out["failed"] == 1
    assert out["next_action"] == "review_successes_retry_failed"
    assert "4/5 member(s) succeeded" in out["summary"]
    assert "a_codex → Codex CLI 需要登录或授权" in out["summary"]
    assert "Suggested fix: 请打开原生 CLI：`codex`" in out["summary"]
    assert any(line.startswith("Suggested fix: ") for line in out["summary_lines"])
    assert out["failed_members"] == [
        {
            "agent_id": "a_codex",
            "partner_id": "codex-cli",
            "failure_kind": "auth",
            "failure_title": "Codex CLI 需要登录或授权",
            "fix_hint": "请打开原生 CLI：`codex`，完成登录/授权后再让 Octopus 派工。",
            "error": "not logged in",
        }
    ]
    assert "ok.txt" in out["changed_files"]


def test_all_members_failed_recommends_setup_fix(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    def fake_runner(*, partner_id, command, prompt, cwd, timeout=None, env=None):
        return LocalPartnerResult(
            ok=False,
            error="模型不可用\n建议：配置模型。\n\n原始错误：\nno effective model configured",
            raw_error="no effective model configured",
            exit_code=1,
            failure_kind="model",
            failure_title=f"{partner_id} 模型不可用",
            fix_hint="请在原生 CLI 中配置模型后重试。",
        )

    out = run_cli_team("g", _MEMBERS[:2], repo_root=repo, partner_runner=fake_runner)

    assert out["ok"] is False
    assert out["succeeded"] == 0
    assert out["failed"] == 2
    assert out["next_action"] == "fix_cli_setup_and_retry"
    assert len(out["failed_members"]) == 2
    assert "Needs attention" in out["summary"]
    assert out["summary"].count("Suggested fix: 请在原生 CLI 中配置模型后重试。") == 1


def test_multiple_distinct_failures_surface_labeled_fix_hints(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    def fake_runner(*, partner_id, command, prompt, cwd, timeout=None, env=None):
        if partner_id == "codex-cli":
            return LocalPartnerResult(
                ok=False,
                raw_error="not logged in",
                failure_kind="auth",
                failure_title="Codex CLI 需要登录或授权",
                fix_hint="打开 codex 完成登录。",
            )
        return LocalPartnerResult(
            ok=False,
            raw_error="no effective model configured",
            failure_kind="model",
            failure_title=f"{partner_id} 模型不可用",
            fix_hint=f"为 {partner_id} 配置模型。",
        )

    out = run_cli_team("g", _MEMBERS[1:4], repo_root=repo, partner_runner=fake_runner)

    assert out["ok"] is False
    assert out["next_action"] == "fix_cli_setup_and_retry"
    assert "Suggested fixes:" in out["summary"]
    assert "a_codex: 打开 codex 完成登录。" in out["summary"]
    assert "a_trae: 为 trae-cli 配置模型。" in out["summary"]
    assert "a_qoder: 为 qoder-cli 配置模型。" in out["summary"]


def test_guards(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    assert run_cli_team("", _MEMBERS, repo_root=repo)["ok"] is False  # no goal
    assert run_cli_team("g", [], repo_root=repo)["ok"] is False  # no members
    assert run_cli_team("g", _MEMBERS, repo_root=str(tmp_path / "nope"))["ok"] is False  # not git


# ── detection + the reachable cli_team skill (judge) ──────────────────


def test_detect_installed_partners(monkeypatch) -> None:
    from runtime.execution.agents import cli_team as ct

    monkeypatch.setattr(
        ct.shutil,
        "which",
        lambda c: f"/usr/bin/{c}"
        if c in ("claude", "codex", "trae-cli", "qodercli", "codebuddy")
        else None,
    )
    mems = ct.detect_installed_partners()
    assert {m["partner_id"] for m in mems} == {
        "claude-code",
        "codex-cli",
        "trae-cli",
        "qoder-cli",
        "codebuddy-cli",
    }
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
                {
                    "agent_id": "local_claude_code",
                    "partner_id": "claude-code",
                    "ok": True,
                    "diff": "diff A",
                    "files": ["a.py"],
                },
                {
                    "agent_id": "local_codex_cli",
                    "partner_id": "codex-cli",
                    "ok": True,
                    "diff": "diff B",
                    "files": ["b.py"],
                },
            ],
        },
    )
    monkeypatch.setattr(
        ds,
        "_call_agent_vote",
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


def test_router_exposes_status_and_run_routes() -> None:
    from runtime.sensing.gateway.cli_team_router import create_cli_team_router

    router = create_cli_team_router()
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/api/cli-team/status" in paths
    assert "/api/cli-team/run" in paths


def test_router_requires_auth_when_enabled() -> None:
    from runtime.safety.auth import Identity, IdentityStore
    from runtime.sensing.gateway.cli_team_router import create_cli_team_router

    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_cli_team_router(
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)

    assert client.get("/api/cli-team/status").status_code == 401
    assert (
        client.get(
            "/api/cli-team/status",
            headers={"Authorization": "Bearer sk-alice"},
        ).status_code
        == 200
    )


# ── team-task routing: local_* assignees → run_cli_team ───────────────


_DETECTED = [
    {"agent_id": "local_claude_code", "partner_id": "claude-code", "command": "/b/claude"},
    {"agent_id": "local_codex_cli", "partner_id": "codex-cli", "command": "/b/codex"},
    {"agent_id": "local_trae_cli", "partner_id": "trae-cli", "command": "/b/trae-cli"},
    {"agent_id": "local_qoder_cli", "partner_id": "qoder-cli", "command": "/b/qodercli"},
    {"agent_id": "local_codebuddy_cli", "partner_id": "codebuddy-cli", "command": "/b/codebuddy"},
]


def test_select_cli_members_filters_to_assigned() -> None:
    from runtime.execution.agents.cli_team import select_cli_members

    # only the assigned, installed CLIs come back
    got = select_cli_members(["local_codex_cli", "local_trae_cli", "ghost"], detected=_DETECTED)
    assert [m["agent_id"] for m in got] == ["local_codex_cli", "local_trae_cli"]
    # no refs / no match → empty (caller falls back to the topology path)
    assert select_cli_members([], detected=_DETECTED) == []
    assert select_cli_members(["planner"], detected=_DETECTED) == []


def test_local_cli_members_reads_local_assignees(monkeypatch) -> None:
    import runtime.execution.agents.cli_team as ct
    from runtime.sensing.gateway import team_tasks_router as ttr
    from runtime.sensing.gateway.team_tasks_router import TeamTaskWire

    monkeypatch.setattr(ct, "detect_installed_partners", lambda: _DETECTED)
    task = TeamTaskWire(
        id="task-cli",
        room_id="team-alpha",
        title="implement X",
        created_at="2026-06-07T00:00:00+00:00",
        updated_at="2026-06-07T00:00:00+00:00",
        assignees=[
            {"kind": "agent", "ref": "local_codex_cli"},
            {"kind": "agent", "ref": "planner"},  # normal agent, ignored
            {"kind": "participant", "ref": "local_codex_cli"},  # human, ignored
        ],
    )
    got = ttr._local_cli_members(task)
    assert [m["agent_id"] for m in got] == ["local_codex_cli"]


def test_local_cli_members_empty_without_local_assignees(monkeypatch) -> None:
    import runtime.execution.agents.cli_team as ct
    from runtime.sensing.gateway import team_tasks_router as ttr
    from runtime.sensing.gateway.team_tasks_router import TeamTaskWire

    monkeypatch.setattr(ct, "detect_installed_partners", lambda: _DETECTED)
    task = TeamTaskWire(
        id="task-normal",
        room_id="team-alpha",
        title="plan something",
        created_at="2026-06-07T00:00:00+00:00",
        updated_at="2026-06-07T00:00:00+00:00",
        assignees=[{"kind": "agent", "ref": "planner"}],
    )
    assert ttr._local_cli_members(task) == []


def test_cli_team_artifacts_one_per_member_diff_first() -> None:
    from runtime.sensing.gateway.team_tasks_router import _cli_team_artifacts

    arts = _cli_team_artifacts(
        {
            "members": [
                {
                    "agent_id": "local_codex_cli",
                    "partner_id": "codex-cli",
                    "ok": True,
                    "diff": "DIFF-X",
                    "files": ["x.py"],
                },
                {
                    "agent_id": "local_claude_code",
                    "partner_id": "claude-code",
                    "ok": False,
                    "diff": "",
                    "output": "n/c",
                    "error": "boom",
                    "raw_error": "raw boom",
                    "failure_kind": "auth",
                    "failure_title": "Claude Code 需要登录或授权",
                    "fix_hint": "打开原生 CLI 登录。",
                },
            ]
        }
    )
    assert len(arts) == 2
    by_id = {a["agent_id"]: a for a in arts}
    assert by_id["local_codex_cli"]["type"] == "cli_team_diff"
    assert by_id["local_codex_cli"]["content"] == "DIFF-X"  # diff preferred
    assert by_id["local_codex_cli"]["files"] == ["x.py"]
    assert by_id["local_claude_code"]["content"] == "n/c"  # falls back to output
    assert by_id["local_claude_code"]["ok"] is False
    assert by_id["local_claude_code"]["error"] == "boom"
    assert by_id["local_claude_code"]["raw_error"] == "raw boom"
    assert by_id["local_claude_code"]["failure_kind"] == "auth"
    assert by_id["local_claude_code"]["failure_title"] == "Claude Code 需要登录或授权"
    assert by_id["local_claude_code"]["fix_hint"] == "打开原生 CLI 登录。"
    assert by_id["local_claude_code"]["summary"] == "Claude Code 需要登录或授权"
