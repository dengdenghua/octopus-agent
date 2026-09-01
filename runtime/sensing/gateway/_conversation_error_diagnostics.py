"""Privacy-bounded diagnostics for errors persisted in conversation snapshots."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

_AUTH_RE = re.compile(
    r"auth|credential|unauthori[sz]ed|invalid api.?key|not logged in|尚未登录|登录凭据|凭据刷新",
    re.IGNORECASE,
)
_RATE_LIMIT_RE = re.compile(
    r"http[_ ]?429|rate.?limit|too many requests|quota|usage limit|请求过多|限流|额度",
    re.IGNORECASE,
)
_NETWORK_RE = re.compile(
    r"unexpected_eof|ssl eof|remoteprotocolerror|server disconnected|connection (?:refused|reset|lost)|"
    r"econnrefused|network error|fetch failed|websocket closed \(1006|transport error|timeout",
    re.IGNORECASE,
)
_SERVER_RE = re.compile(
    r"http[_ ]?5\d\d|\b5(?:00|02|03|04)\b|bad gateway|service unavailable|internal server error",
    re.IGNORECASE,
)
_REQUEST_RE = re.compile(r"http[_ ]?400|\b400\b|bad request", re.IGNORECASE)
_ENGINE_REPLAY_RE = re.compile(
    r"responses request replay|replay was rejected|\b409 conflict\b",
    re.IGNORECASE,
)
_LIFECYCLE_RE = re.compile(
    r"tool execution blocked because its start event was not durably applied|"
    r"tool_start durable audit failed|serialized payload is not a valid journal event|"
    r"redaction changed journal ownership scope|missing_terminal_state|"
    r"runtime returned without a terminal task outcome",
    re.IGNORECASE,
)
_SAFE_CODE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")


def _safe_error_code(value: Any) -> str:
    code = str(value or "").strip()
    return code if _SAFE_CODE_RE.fullmatch(code) else "unknown"


def classify_conversation_error(code: str, message: str) -> tuple[str, str, bool]:
    """Return a stable category, operator action, and retryability hint.

    The raw message is used only for classification and is never included in
    the public diagnostics response. Codes win where they are authoritative;
    message matching keeps legacy snapshots useful.
    """

    signal = f"{code}\n{message}"
    normalized_code = code.strip().lower()
    if normalized_code in {
        "_toolstartauditerror",
        "journaltransactionerror",
    } or _LIFECYCLE_RE.search(signal):
        return "lifecycle", "retry_task", True
    if normalized_code in {"auth", "chatgptsubscriptionroutererror"} or _AUTH_RE.search(signal):
        return "authentication", "reauthenticate", True
    if _RATE_LIMIT_RE.search(signal):
        return "rate_limit", "retry_later", True
    if _ENGINE_REPLAY_RE.search(signal):
        return "engine_replay", "retry_task", True
    if normalized_code == "remoteprotocolerror" or _NETWORK_RE.search(signal):
        return "network", "retry", True
    if _SERVER_RE.search(signal):
        return "provider", "retry", True
    if _REQUEST_RE.search(signal):
        return "request", "review_model_configuration", False
    if normalized_code == "codex_app_server_error":
        return "engine", "retry_task", True
    if normalized_code == "turn_driver_exception":
        return "engine", "inspect_runtime", False
    return "unknown", "inspect_runtime", False


def build_conversation_error_diagnostics(
    threads: Iterable[dict[str, Any]],
    *,
    message_limit: int = 500,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Summarize bounded thread snapshots without exposing error details."""

    bounded_message_limit = max(1, min(int(message_limit), 5_000))
    bounded_sample_limit = max(0, min(int(sample_limit), 100))
    by_code: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    threads_scanned = 0
    threads_with_errors = 0
    error_count = 0
    retryable_count = 0

    for thread in threads:
        if not isinstance(thread, dict):
            continue
        threads_scanned += 1
        values = thread.get("values")
        values = values if isinstance(values, dict) else {}
        raw_messages = values.get("messages")
        messages = raw_messages if isinstance(raw_messages, list) else []
        thread_errors = 0
        seen: set[str] = set()
        for index, message in enumerate(messages[-bounded_message_limit:]):
            if not isinstance(message, dict):
                continue
            kwargs = message.get("additional_kwargs")
            kwargs = kwargs if isinstance(kwargs, dict) else {}
            error = kwargs.get("error")
            if not isinstance(error, dict):
                continue
            message_id = str(message.get("id") or f"offset:{index}")
            if message_id in seen:
                continue
            seen.add(message_id)
            info = error.get("info")
            info = info if isinstance(info, dict) else {}
            code = _safe_error_code(info.get("code") or info.get("source_kind"))
            raw_message = str(error.get("message") or "")
            category, action, retryable = classify_conversation_error(code, raw_message)
            by_code[code] += 1
            by_category[category] += 1
            error_count += 1
            thread_errors += 1
            retryable_count += int(retryable)
            if len(samples) < bounded_sample_limit:
                samples.append(
                    {
                        "thread_id": str(thread.get("thread_id") or ""),
                        "title": str(values.get("title") or "New chat")[:160],
                        "thread_updated_at": thread.get("updated_at"),
                        "code": code,
                        "category": category,
                        "recommended_action": action,
                        "retryable": retryable,
                    }
                )
        if thread_errors:
            threads_with_errors += 1

    return {
        "schema": "octopus.conversation_error_diagnostics.v1",
        "bounds": {
            "message_limit_per_thread": bounded_message_limit,
            "sample_limit": bounded_sample_limit,
        },
        "summary": {
            "threads_scanned": threads_scanned,
            "threads_with_errors": threads_with_errors,
            "error_count": error_count,
            "retryable_count": retryable_count,
            "by_code": dict(sorted(by_code.items())),
            "by_category": dict(sorted(by_category.items())),
        },
        "samples": samples,
    }


__all__ = ["build_conversation_error_diagnostics", "classify_conversation_error"]
