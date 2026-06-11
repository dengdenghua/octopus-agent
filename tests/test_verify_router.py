from types import SimpleNamespace

from runtime.sensing.gateway.verify_router import (
    _is_local_preview_host,
    _run_browser_regression_checks,
)


def test_browser_regression_is_skipped_when_disabled() -> None:
    body = SimpleNamespace(browser_regression_enabled=False)

    assert _run_browser_regression_checks(body) == []


def test_browser_regression_requires_preview_url() -> None:
    body = SimpleNamespace(
        browser_regression_enabled=True,
        browser_regression_preview_url="",
        browser_regression_mode="human_cursor",
        browser_regression_requires_visible_cursor=True,
        timeout=1.0,
    )

    result = _run_browser_regression_checks(body)

    assert len(result) == 1
    assert not result[0].passed
    assert "no preview URL" in result[0].stderr


def test_browser_regression_rejects_non_local_preview_url() -> None:
    body = SimpleNamespace(
        browser_regression_enabled=True,
        browser_regression_preview_url="https://example.com",
        browser_regression_mode="human_cursor",
        browser_regression_requires_visible_cursor=True,
        timeout=1.0,
    )

    result = _run_browser_regression_checks(body)

    assert len(result) == 1
    assert not result[0].passed
    assert "localhost/loopback" in result[0].stderr


def test_local_preview_host_detection() -> None:
    assert _is_local_preview_host("localhost")
    assert _is_local_preview_host("127.0.0.1")
    assert _is_local_preview_host("127.1.2.3")
    assert _is_local_preview_host("::1")
    assert not _is_local_preview_host("example.com")
