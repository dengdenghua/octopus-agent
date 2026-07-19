"""drive_local_partner — direct CLI dispatch + fallback decisions (fakes only)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from runtime.execution.agents.local_partner_bridge import LocalPartnerResult
from runtime.protocol import TurnStatus
from runtime.sensing.gateway import realtime_local_partner as mod


class _FakeRuntime:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.react_called = False

    async def _emit_agent_message(self, turn, log, emitter, text) -> None:
        self.messages.append(text)
        turn.items.append(SimpleNamespace(text=text))

    async def _drive_react(self, turn, log, emitter, intent, provider, agent) -> None:
        self.react_called = True


def _agent(partner_id="claude-code", command="claude", name="Claude Code 伙伴"):
    return SimpleNamespace(
        capabilities={
            "local_partner": True,
            "local_partner_id": partner_id,
            "local_partner_command": command,
        },
        display_name=name,
    )


def _drive(rt, agent, *, result=None, monkeypatch=None):
    turn = SimpleNamespace(items=[], status="inProgress")
    if result is not None and monkeypatch is not None:
        monkeypatch.setattr(mod, "run_local_partner", lambda **kw: result)
    asyncio.run(
        mod.drive_local_partner(rt, turn, object(), object(), object(), agent, object(), text="go")
    )
    return turn


# ── the helper used by routing ───────────────────────────────────────


def test_agent_is_local_partner_decision() -> None:
    assert mod.agent_is_local_partner(_agent()) is True
    assert mod.agent_is_local_partner(SimpleNamespace(capabilities={})) is False
    assert mod.agent_is_local_partner(SimpleNamespace(capabilities=None)) is False


# ── ok: CLI output becomes one plain message, no LLM fallback ─────────


def test_ok_emits_output_and_does_not_fall_back(monkeypatch) -> None:
    rt = _FakeRuntime()
    turn = _drive(
        rt,
        _agent(),
        result=LocalPartnerResult(ok=True, output="edited 3 files", exit_code=0),
        monkeypatch=monkeypatch,
    )
    assert rt.messages == ["edited 3 files"]
    assert rt.react_called is False
    assert turn.status == "inProgress"  # success leaves finalization to the lifecycle


# ── unsupported partner → fall back to the normal ReAct loop ─────────


def test_unsupported_falls_back_to_react(monkeypatch) -> None:
    rt = _FakeRuntime()
    _drive(
        rt,
        _agent(),
        result=LocalPartnerResult(ok=False, unsupported=True),
        monkeypatch=monkeypatch,
    )
    assert rt.react_called is True
    assert rt.messages == []  # no message — the LLM loop takes over


# ── ran-but-errored → plain report + failed turn, NO model fallback ──


def test_error_reports_plainly_and_fails_turn(monkeypatch) -> None:
    rt = _FakeRuntime()
    turn = _drive(
        rt,
        _agent(),
        result=LocalPartnerResult(ok=False, error="not logged in", exit_code=1),
        monkeypatch=monkeypatch,
    )
    assert rt.react_called is False  # deliberately no fallback to octopus's model
    assert len(rt.messages) == 1
    assert "couldn't finish" in rt.messages[0]
    assert "not logged in" in rt.messages[0]
    assert turn.status == TurnStatus.FAILED


def test_error_reports_structured_diagnosis_once(monkeypatch) -> None:
    rt = _FakeRuntime()
    turn = _drive(
        rt,
        _agent(partner_id="trae-cli", command="trae-cli", name="Trae CLI 伙伴"),
        result=LocalPartnerResult(
            ok=False,
            error=(
                "Trae CLI 模型不可用\n"
                "建议：请先在 Trae CLI 原生终端选择/配置模型。\n\n"
                "原始错误：\nno effective model configured"
            ),
            raw_error="no effective model configured",
            exit_code=1,
            failure_kind="model",
            failure_title="Trae CLI 模型不可用",
            fix_hint="请先在 Trae CLI 原生终端选择/配置模型。",
        ),
        monkeypatch=monkeypatch,
    )

    message = rt.messages[0]
    assert "诊断：Trae CLI 模型不可用" in message
    assert "建议：请先在 Trae CLI 原生终端选择/配置模型。" in message
    assert "no effective model configured" in message
    assert message.count("Trae CLI 模型不可用") == 1
    assert turn.status == TurnStatus.FAILED


def test_timeout_reports_plainly(monkeypatch) -> None:
    rt = _FakeRuntime()
    turn = _drive(
        rt,
        _agent(),
        result=LocalPartnerResult(ok=False, timed_out=True, error="claude did not finish"),
        monkeypatch=monkeypatch,
    )
    assert "timed out" in rt.messages[0]
    assert turn.status == TurnStatus.FAILED


# ── safety net: a non-partner agent never spawns, just runs react ────


def test_non_partner_agent_falls_back(monkeypatch) -> None:
    rt = _FakeRuntime()
    # run_local_partner must NOT be reached for a non-partner agent.
    monkeypatch.setattr(
        mod, "run_local_partner", lambda **kw: (_ for _ in ()).throw(AssertionError("spawned"))
    )
    _drive(rt, SimpleNamespace(capabilities={}, display_name="plain"))
    assert rt.react_called is True
    assert rt.messages == []


def test_envelope_briefs_prompt_passes_env_and_harvests(monkeypatch) -> None:
    rt = _FakeRuntime()
    monkeypatch.setattr(
        mod, "blackboard_brief", lambda tid, **_k: "TEAM: prior finding" if tid else ""
    )
    harvested: dict = {}
    monkeypatch.setattr(
        mod,
        "harvest_to_blackboard",
        lambda tid, w, out: harvested.update({"tid": tid, "writer": w, "out": out}),
    )
    seen: dict = {}

    def fake_run(**kw):
        seen.update(kw)
        return LocalPartnerResult(ok=True, output="did the work", exit_code=0)

    monkeypatch.setattr(mod, "run_local_partner", fake_run)
    turn = SimpleNamespace(id="turn-1", thread_id="th", items=[], status="inProgress")
    intent = SimpleNamespace(user_context={})
    asyncio.run(
        mod.drive_local_partner(
            rt, turn, object(), object(), intent, _agent(), object(), text="do X"
        )
    )
    # brief was prepended to the prompt the CLI received
    assert "TEAM: prior finding" in seen["prompt"]
    assert "do X" in seen["prompt"]
    # env carries the turn id so `octopus bb` is reachable from the CLI
    assert seen["env"]["OCTOPUS_TURN_ID"] == "turn-1"
    # the CLI's output was harvested back to the shared board
    assert harvested["out"] == "did the work"
    assert harvested["tid"] == "turn-1"
    assert rt.messages == ["did the work"]
