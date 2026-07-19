from __future__ import annotations

from runtime.core.cerebrum.react_types import (
    REACT_OBSERVATION_FOLLOWUP,
    REACT_SYSTEM_PROMPT_BASE,
)


def test_public_update_is_required_after_observation_before_more_tools() -> None:
    assert "已有 Observation 后继续调用工具时必填" in REACT_SYSTEM_PROMPT_BASE
    assert "收到 Observation 后若还要 Action" in REACT_SYSTEM_PROMPT_BASE
    assert "必须先输出一条 Update:" in REACT_OBSERVATION_FOLLOWUP


def test_observation_followup_allows_direct_final_and_rejects_empty_status() -> None:
    assert "证据已经足够，直接输出 Final Answer" in REACT_OBSERVATION_FOLLOWUP
    assert "不要写空状态" in REACT_OBSERVATION_FOLLOWUP
    assert "不要复述工具名、参数或内部协议" in REACT_OBSERVATION_FOLLOWUP
