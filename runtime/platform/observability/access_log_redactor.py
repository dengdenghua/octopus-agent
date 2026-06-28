"""Access-log redaction for HTTP request targets.

Uvicorn access logs format request targets before application handlers see
them, so endpoint-level redaction is too late for ``?token=...`` SSE and
WebSocket fallback URLs.  This module keeps the filtering small and explicit:
drop known noisy success polls, and redact sensitive URL parameters on records
that still get emitted.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from runtime.platform.observability.redactor import Redactor

DEFAULT_NOISY_ROUTES: tuple[str, ...] = (
    "/api/agents",
    "/api/llm-models",
    "/api/files/stream",
    "/api/preview/stream",
    "/api/evolution/status",
    "/api/auth/status",
    "/api/auth/providers",
    "/api/threads/search",
    "/api/tasks?",
    "/api/regeneration/status",
    "/history HTTP",
)

_SENSITIVE_KEY = (
    r"access[_-]?token|api[_-]?key|apikey|auth|authorization|bearer|code|jwt|key|"
    r"preview[_-]?token|refresh[_-]?token|relay[_-]?token|secret|session[_-]?token|"
    r"sig|signature|token"
)
_URL_PARAM_RE = re.compile(rf"(?i)([?&#](?:{_SENSITIVE_KEY})=)([^&#\s\"']*)")
_ENCODED_URL_PARAM_RE = re.compile(
    rf"(?i)((?:%3[fF]|%26)(?:{_SENSITIVE_KEY})%3[dD])([^%&#\s\"']*)"
)
_BARE_PARAM_RE = re.compile(rf"(?i)(\b(?:{_SENSITIVE_KEY})=)([^&#\s\"']*)")
_BEARER_RE = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9._\-+/=]{8,})")
_SUCCESS_STATUS_RE = re.compile(r"(?<!\d)(?:200|304)(?!\d)")
_SECRET_REDACTOR = Redactor(
    enabled_categories=frozenset({"api_key", "aws_secret", "jwt", "private_key"})
)


def redact_access_log_text(text: str) -> str:
    """Redact secrets likely to appear in an HTTP access-log line."""

    if not text or not isinstance(text, str):
        return text
    redacted = _URL_PARAM_RE.sub(r"\1<redacted>", text)
    redacted = _ENCODED_URL_PARAM_RE.sub(r"\1%3Credacted%3E", redacted)
    redacted = _BARE_PARAM_RE.sub(r"\1<redacted>", redacted)
    redacted = _BEARER_RE.sub(r"\1<redacted>", redacted)
    return _SECRET_REDACTOR.redact(redacted)


def _redact_arg(value: Any) -> Any:
    if isinstance(value, str):
        return redact_access_log_text(value)
    if isinstance(value, tuple):
        return tuple(_redact_arg(item) for item in value)
    if isinstance(value, list):
        return [_redact_arg(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_arg(item) for key, item in value.items()}
    return value


def _has_success_status(record: logging.LogRecord, message: str) -> bool:
    args = record.args
    values: tuple[Any, ...]
    if isinstance(args, tuple):
        values = args
    elif isinstance(args, list):
        values = tuple(args)
    elif isinstance(args, dict):
        values = tuple(args.values())
    else:
        values = ()
    if any(value in (200, 304, "200", "304") for value in values):
        return True
    return bool(_SUCCESS_STATUS_RE.search(message))


def sanitize_access_log_record(record: logging.LogRecord) -> logging.LogRecord:
    """Mutate a ``LogRecord`` so emitted access logs cannot expose tokens."""

    if isinstance(record.args, tuple):
        record.args = tuple(_redact_arg(arg) for arg in record.args)
    elif isinstance(record.args, dict):
        record.args = {key: _redact_arg(value) for key, value in record.args.items()}
    elif record.args:
        record.args = _redact_arg(record.args)
    else:
        record.msg = redact_access_log_text(str(record.msg))
    return record


class SensitiveAccessLogFilter(logging.Filter):
    """Drop noisy success polls and redact secrets from remaining access logs."""

    def __init__(
        self,
        *,
        noisy_routes: tuple[str, ...] = DEFAULT_NOISY_ROUTES,
        drop_noisy_success: bool = True,
    ) -> None:
        super().__init__()
        self.noisy_routes = noisy_routes
        self.drop_noisy_success = drop_noisy_success

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if self.drop_noisy_success and _has_success_status(record, message):
            if any(route in message for route in self.noisy_routes):
                return False
        sanitize_access_log_record(record)
        return True


def install_uvicorn_access_filter(
    logger: logging.Logger | None = None,
    *,
    drop_noisy_success: bool = True,
) -> SensitiveAccessLogFilter:
    """Install one idempotent sanitizer on the uvicorn access logger."""

    target = logger or logging.getLogger("uvicorn.access")
    for existing in target.filters:
        if isinstance(existing, SensitiveAccessLogFilter):
            existing.drop_noisy_success = drop_noisy_success
            return existing
    access_filter = SensitiveAccessLogFilter(drop_noisy_success=drop_noisy_success)
    target.addFilter(access_filter)
    return access_filter


__all__ = [
    "DEFAULT_NOISY_ROUTES",
    "SensitiveAccessLogFilter",
    "install_uvicorn_access_filter",
    "redact_access_log_text",
    "sanitize_access_log_record",
]
