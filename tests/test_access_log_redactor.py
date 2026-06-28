from __future__ import annotations

import logging


def test_access_log_redacts_query_token_but_keeps_safe_params() -> None:
    from runtime.platform.observability.access_log_redactor import redact_access_log_text

    out = redact_access_log_text(
        'GET /api/realtime?token=sk-alice&surface=chat HTTP/1.1'
    )

    assert "sk-alice" not in out
    assert "token=<redacted>" in out
    assert "surface=chat" in out


def test_access_log_redacts_url_encoded_nested_token() -> None:
    from runtime.platform.observability.access_log_redactor import redact_access_log_text

    out = redact_access_log_text(
        "GET /api/browser/relay/bookmarklet-poll"
        "?url=http%3A%2F%2F127.0.0.1%3A8000%2Fconnect%3Fapi_base_url%3Dhttp"
        "%26relay_token%3Dencoded-secret-value&relay_token=plain-secret HTTP/1.1"
    )

    assert "encoded-secret-value" not in out
    assert "plain-secret" not in out
    assert "relay_token=<redacted>" in out
    assert "relay_token%3D%3Credacted%3E" in out


def test_access_log_redacts_bearer_and_kimi_style_key() -> None:
    from runtime.platform.observability.access_log_redactor import redact_access_log_text

    out = redact_access_log_text(
        "Authorization: Bearer sk-kimi-abcdefghijklmnopqrstuvwxyz0123456789ABCDE"
    )

    assert "sk-kimi" not in out
    assert "Bearer <redacted>" in out


def test_access_log_preserves_non_secret_polling_ids() -> None:
    from runtime.platform.observability.access_log_redactor import redact_access_log_text

    out = redact_access_log_text(
        "GET /api/browser/relay/bookmarklet-poll"
        "?callback=__octopusBookmarkletPoll_1782654045773_f8ve3mrrqkf"
        "&title=Octopus%20Chrome%20Relay%20Probe&t=1782654045793 HTTP/1.1"
    )

    assert "[REDACTED:phone]" not in out
    assert "1782654045773" in out
    assert "1782654045793" in out
    assert "__octopusBookmarkletPoll_" in out


def test_access_log_filter_sanitizes_uvicorn_tuple_args() -> None:
    from runtime.platform.observability.access_log_redactor import SensitiveAccessLogFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:50123",
            "GET",
            "/api/realtime?token=jwt.secret.value&surface=chat",
            "1.1",
            403,
        ),
        None,
    )

    assert SensitiveAccessLogFilter().filter(record) is True
    message = record.getMessage()

    assert "jwt.secret.value" not in message
    assert "token=<redacted>" in message
    assert "surface=chat" in message


def test_access_log_filter_drops_noisy_success_polling() -> None:
    from runtime.platform.observability.access_log_redactor import SensitiveAccessLogFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:50123",
            "GET",
            "/api/preview/stream?token=sk-secret",
            "1.1",
            200,
        ),
        None,
    )

    assert SensitiveAccessLogFilter().filter(record) is False


def test_install_uvicorn_access_filter_is_idempotent() -> None:
    from runtime.platform.observability.access_log_redactor import (
        SensitiveAccessLogFilter,
        install_uvicorn_access_filter,
    )

    logger = logging.getLogger("octopus.test.access")
    logger.filters.clear()

    first = install_uvicorn_access_filter(logger)
    second = install_uvicorn_access_filter(logger)

    assert first is second
    assert sum(isinstance(item, SensitiveAccessLogFilter) for item in logger.filters) == 1
