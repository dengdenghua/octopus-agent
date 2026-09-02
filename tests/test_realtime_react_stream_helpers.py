from __future__ import annotations

from runtime.sensing.gateway.realtime_react_stream import _model_error_reply


def test_model_error_reply_explains_chatgpt_login_expiry() -> None:
    reply = _model_error_reply(RuntimeError("credential refresh failed: 尚未登录 ChatGPT"))

    assert reply is not None
    assert "模型设置" in reply
    assert "credential" not in reply


def test_model_error_reply_explains_provider_rate_limit() -> None:
    reply = _model_error_reply(RuntimeError("http_429: Error from provider: Rate limit exceeded"))

    assert reply is not None
    assert "请求过多" in reply
    assert "切换" in reply
    assert "http_429" not in reply


def test_model_error_reply_leaves_unknown_errors_for_structured_failure_path() -> None:
    assert _model_error_reply(RuntimeError("unknown provider failure")) is None
