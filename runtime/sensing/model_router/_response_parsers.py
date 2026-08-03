"""Response-parsing helpers for OpenAI-compatible providers.

Extracted from ``openai_compat_providers.py``.  These pure functions
parse provider responses (reasoning text extraction, usage accounting,
and tool-call argument decoding including the XML ``<parameter>``
fallback) without depending on the provider profile catalog or the
request/retry engine.  ``openai_compat_providers.py`` re-exports the
public entry points so existing import sites continue to work.
"""

from __future__ import annotations

import ast
import html
import json
import re
from typing import Any


def extract_openai_compat_reasoning(message: dict[str, Any]) -> str:
    pieces: list[str] = []
    for key in (
        "reasoning_content",
        "reasoning",
        "thinking",
        "reasoning_text",
        "thought",
    ):
        value = message.get(key)
        rendered = _render_reasoning_value(value)
        if rendered:
            pieces.append(rendered)

    details = _render_reasoning_value(message.get("reasoning_details"))
    if details:
        pieces.append(details)

    return "\n".join(piece for piece in pieces if piece)


def extract_openai_compat_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = _coerce_usage(data.get("usage"))
    if usage is None:
        choices = data.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                usage = _coerce_usage(choice.get("usage"))
                if usage is not None:
                    break
    if usage is None:
        return 0, 0
    return (
        _int_from_any(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("promptTokens")
            or usage.get("inputTokens")
        ),
        _int_from_any(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("completionTokens")
            or usage.get("outputTokens")
        ),
    )


_XML_PARAMETER_RE = re.compile(
    r"<parameter\b(?P<attrs>[^>]*)>(?P<value>.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
_XML_PARAMETER_NAME_RE = re.compile(
    r"\bname\s*=\s*(['\"])(?P<name>[^'\"]+)\1",
    re.IGNORECASE,
)


def _xml_parameter_arguments(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for match in _XML_PARAMETER_RE.finditer(text):
        attrs = match.group("attrs") or ""
        name_match = _XML_PARAMETER_NAME_RE.search(attrs)
        if name_match is None:
            continue
        name = html.unescape(name_match.group("name")).strip()
        if not name:
            continue
        raw = html.unescape(match.group("value") or "").strip()
        if re.search(r"\bstring\s*=\s*(['\"])true\1", attrs, re.IGNORECASE):
            parsed[name] = raw
            continue
        if raw.lower() == "true":
            parsed[name] = True
        elif raw.lower() == "false":
            parsed[name] = False
        elif raw.lower() in {"null", "none"}:
            parsed[name] = None
        else:
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded = raw
            parsed[name] = decoded
    return parsed


def _normalize_tool_argument_mapping(parsed: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parsed)
    wrapper_keys: list[str] = []
    recovered: dict[str, Any] = {}
    for key, raw in parsed.items():
        if not isinstance(raw, str) or "<parameter" not in raw.lower():
            continue
        xml_args = _xml_parameter_arguments(raw)
        if xml_args:
            wrapper_keys.append(key)
            recovered.update(xml_args)
    for key in wrapper_keys:
        normalized.pop(key, None)
    normalized.update(recovered)
    return normalized


def parse_tool_call_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return _normalize_tool_argument_mapping(value)
    if value is None:
        return {}
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text:
        return {}

    parsed: Any
    try:
        parsed = json.loads(text)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return _normalize_tool_argument_mapping(parsed) if isinstance(parsed, dict) else {}
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):  # expected · falls through to the ast.literal_eval fallback below
        pass

    try:
        parsed = ast.literal_eval(text)
        return _normalize_tool_argument_mapping(parsed) if isinstance(parsed, dict) else {}
    except (SyntaxError, ValueError, TypeError):
        return _xml_parameter_arguments(text)


def _render_reasoning_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool):
        return str(value)
    if isinstance(value, list):
        pieces = [_render_reasoning_detail(item) for item in value]
        return "\n".join(piece for piece in pieces if piece)
    if isinstance(value, dict):
        return _render_reasoning_detail(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _render_reasoning_detail(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return _render_reasoning_value(value)
    for key in ("text", "content", "reasoning", "summary", "delta"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return json.dumps(value, ensure_ascii=False, default=str)


def _coerce_usage(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _int_from_any(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else 0
