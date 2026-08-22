"""Strict framing, launch, and validation helpers for the stdio client."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from .types import (
    AppServerProcess,
    CodexAppServerConfig,
    ConfigurationError,
    JsonObject,
    JsonValue,
    MessageTooLargeError,
    ProcessLaunch,
    ProtocolError,
)

_logger = logging.getLogger(__name__)

APPROVAL_METHODS = frozenset(
    {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
    }
)
_COMMAND_DECISIONS = frozenset({"accept", "acceptForSession", "decline", "cancel"})
_STRUCTURED_COMMAND_DECISIONS = frozenset(
    {"acceptWithExecpolicyAmendment", "applyNetworkPolicyAmendment"}
)
_TOP_LEVEL_FIELDS = frozenset(
    {"jsonrpc", "id", "method", "params", "result", "error", "emittedAtMs"}
)


async def default_process_factory(launch: ProcessLaunch) -> AppServerProcess:
    kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "cwd": launch.cwd,
        "env": launch.env,
        "limit": launch.stream_limit,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    process = await asyncio.create_subprocess_exec(*launch.argv, **kwargs)
    return cast(AppServerProcess, process)


def build_environment(config: CodexAppServerConfig) -> dict[str, str]:
    source = config.source_environment if config.source_environment is not None else os.environ
    for key, value in source.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConfigurationError("source environment must contain only string pairs")
    allowed = config.env_allowlist
    if os.name == "nt":
        allowed_upper = {key.upper() for key in allowed}
        environment = {key: value for key, value in source.items() if key.upper() in allowed_upper}
    else:
        environment = {key: value for key, value in source.items() if key in allowed}
    environment.update(config.env_overrides)
    for key, value in environment.items():
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ConfigurationError(f"invalid environment entry: {key!r}")
    return environment


def encode_message(message: Mapping[str, Any], config: CodexAppServerConfig) -> bytes:
    normalized = normalize_object(message, config)
    try:
        encoded = (
            json.dumps(
                normalized,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProtocolError("outbound message is not strict JSON") from exc
    if len(encoded) > config.max_message_bytes:
        raise MessageTooLargeError(f"outbound frame exceeds {config.max_message_bytes} bytes")
    return encoded


def decode_message(text: str, config: CodexAppServerConfig) -> JsonObject:
    def _reject_constant(value: str) -> None:
        raise ProtocolError(f"non-finite JSON number is not allowed: {value}")

    def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolError(f"duplicate JSON object key: {key!r}")
            result[key] = value
        return result

    try:
        raw = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicates,
        )
    except ProtocolError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("invalid App Server JSON frame") from exc
    if not isinstance(raw, dict):
        raise ProtocolError("App Server frame must be a JSON object")
    message = normalize_object(raw, config)
    unknown = set(message).difference(_TOP_LEVEL_FIELDS)
    if unknown:
        raise ProtocolError(f"unknown top-level protocol fields: {sorted(unknown)!r}")
    emitted_at_ms = message.get("emittedAtMs")
    if "emittedAtMs" in message and (
        isinstance(emitted_at_ms, bool) or not isinstance(emitted_at_ms, int) or emitted_at_ms < 0
    ):
        raise ProtocolError("emittedAtMs must be a non-negative integer")
    if "jsonrpc" in message and message["jsonrpc"] != "2.0":
        raise ProtocolError("jsonrpc, when present, must equal '2.0'")

    has_method = "method" in message
    has_result = "result" in message
    has_error = "error" in message
    has_id = "id" in message
    if has_method:
        method = message["method"]
        if not isinstance(method, str):
            raise ProtocolError("protocol method must be a string")
        validate_method(method, config.max_method_chars)
        if has_result or has_error:
            raise ProtocolError("method messages cannot contain result or error")
        if "params" in message and not isinstance(message["params"], dict):
            raise ProtocolError("protocol params must be an object")
        if has_id:
            _validate_request_id(message["id"])
        return message

    if not has_id or has_result == has_error or "params" in message:
        raise ProtocolError("invalid JSON-RPC response envelope")
    _validate_request_id(message["id"])
    if has_error:
        error = message["error"]
        if not isinstance(error, dict):
            raise ProtocolError("protocol error must be an object")
        if set(error).difference({"code", "message", "data"}):
            raise ProtocolError("protocol error contains unknown fields")
        if isinstance(error.get("code"), bool) or not isinstance(error.get("code"), int):
            raise ProtocolError("protocol error code must be an integer")
        if not isinstance(error.get("message"), str):
            raise ProtocolError("protocol error message must be a string")
    return message


def normalize_object(value: Mapping[str, Any], config: CodexAppServerConfig) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ProtocolError("JSON payload must be an object")
    normalized = _normalize_json_value(value, config.max_json_depth)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping always normalizes to dict
        raise ProtocolError("JSON payload must be an object")
    return normalized


def _normalize_json_value(value: Any, max_depth: int) -> JsonValue:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            raise ProtocolError(f"JSON payload exceeds maximum depth {max_depth}")
        if current is None or isinstance(current, str | bool | int):
            continue
        if isinstance(current, float):
            if not (float("-inf") < current < float("inf")):
                raise ProtocolError("non-finite JSON numbers are not allowed")
            continue
        if isinstance(current, Mapping):
            for key, child in current.items():
                if not isinstance(key, str):
                    raise ProtocolError("JSON object keys must be strings")
                stack.append((child, depth + 1))
            continue
        if isinstance(current, list | tuple):
            stack.extend((child, depth + 1) for child in current)
            continue
        raise ProtocolError(f"unsupported JSON value type: {type(current).__name__}")

    def _copy(current: Any) -> JsonValue:
        if isinstance(current, Mapping):
            return {key: _copy(child) for key, child in current.items()}
        if isinstance(current, list | tuple):
            return [_copy(child) for child in current]
        return cast(JsonValue, current)

    return _copy(value)


def validate_method(method: str, max_chars: int) -> None:
    if not method or len(method) > max_chars or "\x00" in method:
        raise ProtocolError(f"invalid protocol method: {method!r}")


def _validate_request_id(value: JsonValue) -> None:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ProtocolError("protocol id must be an integer or string")
    if isinstance(value, str) and (not value or len(value) > 256):
        raise ProtocolError("string protocol id must contain 1..256 characters")


def validate_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
        raise ConfigurationError(f"{name} must contain 1..512 NUL-free characters")


def validate_absolute_path(value: str, name: str) -> None:
    if not value or "\x00" in value or not Path(value).is_absolute():
        raise ConfigurationError(f"{name} must be an absolute, NUL-free path")


def validate_thread_security(approval_policy: str, sandbox: str) -> None:
    if approval_policy not in {"untrusted", "on-request", "never"}:
        raise ConfigurationError(f"unsupported approval policy: {approval_policy!r}")
    if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
        raise ConfigurationError(f"unsupported sandbox mode: {sandbox!r}")


def merge_extra_params(
    extra: Mapping[str, Any] | None,
    *,
    reserved: set[str],
) -> dict[str, Any]:
    result = dict(extra or {})
    overlap = reserved.intersection(result)
    if overlap:
        raise ConfigurationError(
            f"extra_params cannot override reserved fields: {sorted(overlap)!r}"
        )
    return result


def normalize_input_items(
    value: str | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    config: CodexAppServerConfig,
) -> list[JsonObject]:
    if isinstance(value, str):
        items: list[Mapping[str, Any]] = [{"type": "text", "text": value}]
    elif isinstance(value, Mapping):
        items = [value]
    elif isinstance(value, Sequence):
        items = list(cast(Sequence[Mapping[str, Any]], value))
    else:  # pragma: no cover - protected by the public annotation
        raise ConfigurationError("turn input must be text or JSON input items")
    if not items:
        raise ConfigurationError("turn input must contain at least one item")
    return [normalize_object(item, config) for item in items]


def require_entity_response(result: JsonValue, method: str, entity: str) -> JsonObject:
    if not isinstance(result, dict):
        raise ProtocolError(f"{method} response must be a JSON object")
    nested = result.get(entity)
    if not isinstance(nested, dict) or not isinstance(nested.get("id"), str):
        raise ProtocolError(f"{method} response is missing {entity}.id")
    return result


def deny_approval(method: str) -> JsonObject:
    if method == "item/permissions/requestApproval":
        return {"permissions": {}, "scope": "turn"}
    return {"decision": "decline"}


def validate_approval_response(
    method: str,
    response: Mapping[str, Any],
    config: CodexAppServerConfig,
) -> JsonObject:
    normalized = normalize_object(response, config)
    if method == "item/permissions/requestApproval":
        if set(normalized).difference({"permissions", "scope", "strictAutoReview"}):
            raise ProtocolError("permission approval response contains unknown fields")
        if not isinstance(normalized.get("permissions"), dict):
            raise ProtocolError("permission approval must return a permissions object")
        scope = normalized.get("scope", "turn")
        if scope not in {"turn", "session"}:
            raise ProtocolError("permission approval scope must be 'turn' or 'session'")
        strict_auto_review = normalized.get("strictAutoReview")
        if strict_auto_review is not None and not isinstance(strict_auto_review, bool):
            raise ProtocolError("strictAutoReview must be a boolean when present")
        normalized["scope"] = cast(JsonValue, scope)
        return normalized

    if set(normalized) != {"decision"}:
        raise ProtocolError("approval response must contain only decision")
    decision = normalized["decision"]
    if isinstance(decision, str) and decision in _COMMAND_DECISIONS:
        return normalized
    if (
        method.startswith("item/commandExecution")
        and isinstance(decision, dict)
        and len(decision) == 1
        and next(iter(decision)) in _STRUCTURED_COMMAND_DECISIONS
    ):
        return normalized
    raise ProtocolError(f"unsupported approval decision for {method}")


async def wait_for_exit(process: AppServerProcess, timeout_s: float) -> bool:
    if process.returncode is not None:
        return True
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_s)
        return True
    except TimeoutError:
        return process.returncode is not None


async def taskkill_process_tree(pid: int) -> None:
    taskkill = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "System32",
        "taskkill.exe",
    )
    try:
        process = await asyncio.create_subprocess_exec(
            taskkill,
            "/pid",
            str(pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except (OSError, TimeoutError):
        _logger.debug("taskkill failed for App Server pid=%d", pid, exc_info=True)


__all__ = [
    "APPROVAL_METHODS",
    "build_environment",
    "decode_message",
    "default_process_factory",
    "deny_approval",
    "encode_message",
    "merge_extra_params",
    "normalize_input_items",
    "normalize_object",
    "require_entity_response",
    "taskkill_process_tree",
    "validate_absolute_path",
    "validate_approval_response",
    "validate_identifier",
    "validate_method",
    "validate_thread_security",
    "wait_for_exit",
]
