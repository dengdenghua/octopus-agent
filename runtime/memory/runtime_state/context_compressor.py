from __future__ import annotations

import logging
from dataclasses import dataclass

_LOG = logging.getLogger("octopus.memory.context_compressor")


@dataclass
class CompressorConfig:
    max_chars: int = 80000
    preserve_system: bool = True
    preserve_recent_n: int = 4
    summary_max_chars: int = 2000


@dataclass
class CompressionResult:
    original_chars: int
    compressed_chars: int
    ratio: float
    method: str
    sections_preserved: int
    sections_summarized: int


class ContextCompressor:
    def __init__(self, config: CompressorConfig | None = None) -> None:
        self.config = config or CompressorConfig()

    def compress(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars <= self.config.max_chars:
            return messages

        system_msgs: list[dict[str, str]] = []
        recent_msgs: list[dict[str, str]] = []
        older_msgs: list[dict[str, str]] = []

        for m in messages:
            role = m.get("role", "")
            if role == "system" and self.config.preserve_system:
                system_msgs.append(m)
            else:
                older_msgs.append(m)

        if len(older_msgs) > self.config.preserve_recent_n:
            recent_msgs = older_msgs[-self.config.preserve_recent_n:]
            older_msgs = older_msgs[:-self.config.preserve_recent_n]
        else:
            recent_msgs = older_msgs
            older_msgs = []

        if not older_msgs:
            return system_msgs + recent_msgs

        summary = self._summarize_older(older_msgs)
        summary_msg = {
            "role": "system",
            "content": f"[Context Summary]\n{summary}",
        }

        return system_msgs + [summary_msg] + recent_msgs

    def compress_with_report(self, messages: list[dict[str, str]]) -> tuple[list[dict[str, str]], CompressionResult]:
        original_chars = sum(len(m.get("content", "")) for m in messages)
        compressed = self.compress(messages)
        compressed_chars = sum(len(m.get("content", "")) for m in compressed)
        ratio = compressed_chars / max(1, original_chars)

        sections_preserved = sum(1 for m in compressed if "[Context Summary]" not in m.get("content", ""))
        sections_summarized = len(messages) - sections_preserved

        return compressed, CompressionResult(
            original_chars=original_chars,
            compressed_chars=compressed_chars,
            ratio=round(ratio, 3),
            method="truncate_older",
            sections_preserved=sections_preserved,
            sections_summarized=max(0, sections_summarized),
        )

    def _summarize_older(self, messages: list[dict[str, str]]) -> str:
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            chunk = content[:500]
            if len(content) > 500:
                chunk += "..."
            parts.append(f"[{role}] {chunk}")

        full = "\n".join(parts)
        if len(full) > self.config.summary_max_chars:
            full = full[: self.config.summary_max_chars] + "\n...[truncated]"
        return full


__all__ = ["CompressorConfig", "CompressionResult", "ContextCompressor"]
