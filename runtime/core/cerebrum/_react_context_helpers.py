"""Token estimation and context-compression helpers for the ReAct loop.

Extracted from ``react_context.py``. Pure helpers — no behaviour change.
"""

from __future__ import annotations

import json
import logging
from typing import Any

_logger = logging.getLogger(__name__)


def _content_to_text(content: Any) -> str:
    """Best-effort text projection for string or structured LLM content blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part for part in (_content_to_text(item) for item in content) if part)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        nested = content.get("content")
        if nested is not None:
            return _content_to_text(nested)
        image_url = content.get("image_url")
        if isinstance(image_url, str):
            return image_url
        if isinstance(image_url, dict):
            return str(image_url.get("url") or "")
        try:
            return json.dumps(content, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


def _estimate_tokens(text: Any) -> int:
    text = _content_to_text(text)
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en = len(text) - cn
    return int(cn / 1.5 + en / 4)


def _estimate_messages_tokens(messages: list) -> int:
    return sum(_estimate_tokens(getattr(m, "content", "") or "") for m in messages)


def context_budget_tokens_for_model(model: str | None) -> int:
    """Return the coarse context budget used by pressure + compression.

    The hot path intentionally avoids tokenizer imports.  Budgets are in
    the same approximate token units as ``_estimate_tokens`` so Chinese
    text no longer gets treated as if one character were one English
    character.
    """
    name = (model or "").lower()
    try:
        from runtime.platform.models.custom_model_flags import model_context_window

        configured_window = model_context_window(model or "")
    except ImportError:
        configured_window = None
    if configured_window is not None:
        # Reserve 10% for the next response, tool schemas and provider-side
        # accounting differences instead of filling the advertised window.
        return max(25_000, int(configured_window * 0.9))
    if any(model_id in name for model_id in ("glm-5.2", "deepseek-v4-flash", "deepseek-v4-pro")):
        return 230_400
    if "claude-3-5" in name or "claude-4" in name or "claude-sonnet" in name:
        return 150_000
    if "gpt-4o" in name or "gpt-5" in name:
        return 100_000
    return 25_000


def _compress_context(
    messages: list,
    *,
    max_tokens: int = 60000,
    router: Any = None,
    model: str = "",
    is_code_mode: bool = False,
) -> list:
    total = _estimate_messages_tokens(messages)
    if total <= max_tokens:
        return messages

    keep_head = 0
    for j, m in enumerate(messages):
        if getattr(m, "role", "") == "system":
            keep_head = j + 1
        else:
            break

    keep_tail = 12
    if len(messages) <= keep_head + keep_tail:
        return _ensure_context_budget(messages, max_tokens=max_tokens)

    mid_start = keep_head
    mid_end = len(messages) - keep_tail
    mid_messages = messages[mid_start:mid_end]

    # Code trajectories need an auditable execution history.  A generated
    # summary can accidentally promote a failed shell/edit attempt into a
    # claimed file mutation or passing test, so code mode always uses the
    # deterministic observation-preserving branch below.
    if router is not None and len(mid_messages) > 4 and not is_code_mode:
        summary = _summarize_messages(mid_messages, router, model)
        if summary:
            from runtime.platform.models.llm import Message

            compressed = list(messages[:mid_start])
            compressed.append(
                Message(
                    role="system",
                    content=(f"[以下是之前对话的摘要]\n{summary}\n[摘要结束 · 最近对话如下]"),
                )
            )
            compressed.extend(messages[mid_end:])
            _logger.info(
                "context compressed with LLM summary: %d tokens → ~%d tokens",
                total,
                _estimate_messages_tokens(compressed),
            )
            return _ensure_context_budget(compressed, max_tokens=max_tokens)

    if is_code_mode:
        compressed = list(messages[:mid_start])
        for m in mid_messages:
            content = getattr(m, "content", "") or ""
            role = getattr(m, "role", "")
            is_file_obs = (
                role == "user"
                and content.startswith("Observation:")
                and any(
                    marker in content
                    for marker in (
                        "read_file",
                        "edit_text_file",
                        "edit_file",
                        "multi_edit_file",
                        "write_text_file",
                        "list_cwd",
                        "todo_write",
                    )
                )
            )
            if is_file_obs:
                compressed.append(m)
            elif role == "user" and content.startswith("Observation:"):
                short = content[:200] + "... [已压缩]" if len(content) > 200 else content
                from runtime.platform.models.llm import Message

                compressed.append(Message(role=role, content=short))
            else:
                compressed.append(m)
        compressed.extend(messages[mid_end:])
        _logger.info(
            "context compressed (code-aware): %d tokens → ~%d tokens",
            total,
            _estimate_messages_tokens(compressed),
        )
        return _ensure_context_budget(compressed, max_tokens=max_tokens)

    compressed = list(messages[:mid_start])
    for m in mid_messages:
        content = getattr(m, "content", "") or ""
        role = getattr(m, "role", "")
        if role == "user" and content.startswith("Observation:"):
            short = content[:200] + "... [已压缩]" if len(content) > 200 else content
            from runtime.platform.models.llm import Message

            compressed.append(Message(role=role, content=short))
        else:
            compressed.append(m)

    compressed.extend(messages[mid_end:])
    _logger.info(
        "context compressed (truncation): %d tokens → ~%d tokens (%d msgs → %d msgs)",
        total,
        _estimate_messages_tokens(compressed),
        len(messages),
        len(compressed),
    )
    return _ensure_context_budget(compressed, max_tokens=max_tokens)


def _ensure_context_budget(messages: list, *, max_tokens: int) -> list:
    """Hard cap compressed context when soft summarization still runs long."""
    if max_tokens <= 0 or _estimate_messages_tokens(messages) <= max_tokens:
        return messages

    keep_head = 0
    for j, m in enumerate(messages):
        if getattr(m, "role", "") == "system":
            keep_head = j + 1
        else:
            break

    head = list(messages[:keep_head])
    if _estimate_messages_tokens(head) >= max_tokens:
        out = (
            [_trim_message_to_budget(head[-1], head_tokens=0, max_tokens=max_tokens)]
            if head
            else []
        )
        _logger.info(
            "context hard-capped oversized system head: ~%d tokens → ~%d tokens (%d msgs → %d msgs)",
            _estimate_messages_tokens(messages),
            _estimate_messages_tokens(out),
            len(messages),
            len(out),
        )
        return out

    kept_tail: list[Any] = []
    for m in reversed(messages[keep_head:]):
        candidate = head + [m] + list(reversed(kept_tail))
        if _estimate_messages_tokens(candidate) <= max_tokens:
            kept_tail.append(m)
            continue
        if not kept_tail:
            kept_tail.append(
                _trim_message_to_budget(
                    m, head_tokens=_estimate_messages_tokens(head), max_tokens=max_tokens
                )
            )
        break

    out = head + list(reversed(kept_tail))
    _logger.info(
        "context hard-capped after compression: ~%d tokens → ~%d tokens (%d msgs → %d msgs)",
        _estimate_messages_tokens(messages),
        _estimate_messages_tokens(out),
        len(messages),
        len(out),
    )
    return out


def _trim_message_to_budget(message: Any, *, head_tokens: int, max_tokens: int) -> Any:
    content = _content_to_text(getattr(message, "content", "") or "")
    role = getattr(message, "role", "")
    remaining_tokens = max(1, max_tokens - head_tokens)
    prefix = "[前文因上下文预算已截断]\n"
    prefix_tokens = _estimate_tokens(prefix)
    trimmed = _suffix_within_token_budget(content, max(1, remaining_tokens - prefix_tokens))
    if len(trimmed) < len(content):
        trimmed = prefix + trimmed
    from runtime.platform.models.llm import Message

    return Message(role=role or "user", content=trimmed)


def _suffix_within_token_budget(content: str, max_tokens: int) -> str:
    if _estimate_tokens(content) <= max_tokens:
        return content
    lo = 0
    hi = len(content)
    best = ""
    while lo <= hi:
        size = (lo + hi) // 2
        candidate = content[-size:] if size else ""
        if _estimate_tokens(candidate) <= max_tokens:
            best = candidate
            lo = size + 1
        else:
            hi = size - 1
    return best


def _summarize_messages(messages: list, router: Any, model: str) -> str:
    try:
        from runtime.platform.models.llm import Message, ModelRequest

        content_parts = []
        for m in messages:
            role = getattr(m, "role", "")
            text = _content_to_text(getattr(m, "content", "") or "")[:300]
            if text.strip():
                content_parts.append(f"[{role}] {text}")
        if not content_parts:
            return ""
        conversation = "\n".join(content_parts[-20:])
        req = ModelRequest(
            model=model or "auto",
            messages=[
                Message(
                    role="system",
                    content=(
                        "你是一个对话摘要助手。把以下对话压缩成 3-5 句话的摘要，"
                        "保留关键信息（工具调用结果、决策、发现）。严格区分工具调用尝试与"
                        "已确认成功的结果：只有明确的成功 Observation 才能写成已完成；"
                        "失败、缺少结果或不确定时必须标成未验证，禁止推断文件已写入、"
                        "测试已通过或命令已成功。只输出摘要，不要解释。"
                    ),
                ),
                Message(role="user", content=conversation),
            ],
            max_tokens=300,
            temperature=0.1,
        )
        resp = router.call(req)
        return (resp.text or "").strip()
    except (ConnectionError, TimeoutError, TypeError, ValueError):  # noqa: BLE001
        return ""
