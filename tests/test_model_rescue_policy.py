from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.sensing.model_router.rescue_policy import (
    is_retryable_model_error,
    next_custom_model_fallback,
)


def test_retryable_model_error_covers_capacity_and_transport_failures() -> None:
    assert is_retryable_model_error(RuntimeError("http_429: rate limit exceeded"))
    assert is_retryable_model_error(TimeoutError("upstream timeout"))
    assert is_retryable_model_error(ConnectionError("connection reset by peer"))
    assert not is_retryable_model_error(ValueError("invalid request schema"))


def test_custom_model_fallback_prefers_strongest_untried_tool_model(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "custom_models.json"
    config_path.write_text(
        json.dumps(
            {
                "slow": {
                    "models": ["agnes-2.0-flash"],
                    "supports_tool_use": True,
                },
                "fast": {
                    "models": ["kimi-k2.7-code", "small-chat"],
                    "supports_tool_use": True,
                },
                "text-only": {
                    "models": ["reasoning-pro"],
                    "supports_tool_use": False,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "runtime.platform.process.paths.app_paths",
        lambda: SimpleNamespace(custom_models_path=config_path),
    )

    assert next_custom_model_fallback(
        "agnes-2.0-flash",
        {"agnes-2.0-flash"},
    ) == "kimi-k2.7-code"
    assert next_custom_model_fallback(
        "agnes-2.0-flash",
        {"agnes-2.0-flash", "kimi-k2.7-code"},
        require_tool_use=False,
    ) == "reasoning-pro"
