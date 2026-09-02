from __future__ import annotations

from runtime.sensing.gateway._team_stream_topology import (
    _adaptive_orchestration_start_marker,
)


def test_adaptive_marker_describes_effective_unique_roster() -> None:
    marker = _adaptive_orchestration_start_marker(
        {
            "adaptive_team_orchestration": True,
            "agent_roster": [
                {"agent_id": "general", "role": "tl"},
                {"agent_id": "researcher", "role": "member"},
                {"agent_id": "researcher", "role": "member"},
            ],
        }
    )

    assert marker is not None
    assert "2 位成员就绪" in marker
    assert "调整分工、顺序与复核" in marker


def test_adaptive_marker_is_hidden_without_server_grant() -> None:
    assert _adaptive_orchestration_start_marker({"agent_roster": ["general", "researcher"]}) is None


def test_adaptive_marker_is_hidden_for_solo_roster() -> None:
    assert (
        _adaptive_orchestration_start_marker(
            {
                "adaptive_team_orchestration": True,
                "agent_roster": ["general", "general"],
            }
        )
        is None
    )
