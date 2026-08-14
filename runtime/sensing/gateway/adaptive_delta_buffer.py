"""自适应流式事件批处理器

优化后端事件推送策略，根据实时吞吐量动态调整批处理阈值。

优化目标:
- CPU 占用降低 30-50%
- WebSocket 帧数减少 40%
- 保持相同的感知延迟 (<50ms p99)

使用方式:
    buffer = AdaptiveDeltaBuffer()

    for chunk in stream:
        buffer.append(chunk)
        if buffer.should_flush():
            await flush_buffer(buffer.get_content())
            buffer.clear()
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class BufferMetrics:
    """批处理缓冲区性能指标"""

    chars_accumulated: int = 0
    flushes: int = 0
    elapsed_s: float = 0.0
    avg_throughput_chars_per_s: float = 0.0


class AdaptiveDeltaBuffer:
    """自适应批处理缓冲器

    根据实时吞吐量动态调整批次大小和刷新频率:
    - 高吞吐 (>1000 chars/s): 增大批次 256 chars / 64ms
    - 中吞吐 (100-1000): 标准批次 64 chars / 32ms
    - 低吞吐 (<100): 减小批次 32 chars / 16ms
    """

    # 阈值配置
    _MIN_INTERVAL_S = 0.016  # 16ms (60fps)
    _STD_INTERVAL_S = 0.032  # 32ms (30fps, 原始默认值)
    _MAX_INTERVAL_S = 0.064  # 64ms (15fps)

    _MIN_CHARS = 32
    _STD_CHARS = 64
    _MAX_CHARS = 256

    # 吞吐量样本的最小刷新间隔：低于此值视为测量噪声
    # (时钟精度 + 调度抖动)，不记录，避免瞬时 flush 污染移动平均。
    _MIN_SAMPLE_INTERVAL_S = 0.001

    # 吞吐量分级
    _LOW_THROUGHPUT = 100  # chars/s
    _HIGH_THROUGHPUT = 1000  # chars/s

    def __init__(self, max_history: int = 10):
        """初始化缓冲器

        Args:
            max_history: 保留的吞吐量历史记录数（用于计算移动平均）
        """
        self._buffer: list[str] = []
        self._buffer_chars = 0
        self._last_flush_time: float | None = None
        self._throughput_history: deque[float] = deque(maxlen=max_history)
        self._metrics = BufferMetrics()

    def append(self, chunk: str) -> None:
        """添加数据到缓冲区"""
        self._buffer.append(chunk)
        self._buffer_chars += len(chunk)
        self._metrics.chars_accumulated += len(chunk)

    def should_flush(self) -> bool:
        """判断是否应该刷新缓冲区

        基于当前吞吐量和缓冲区状态动态决策。
        """
        if not self._buffer:
            return False

        # 首次刷新：立即发送（time-to-first-token）
        if self._last_flush_time is None:
            return True

        elapsed = time.monotonic() - self._last_flush_time
        avg_throughput = self._estimate_throughput()

        # 根据吞吐量选择阈值
        if avg_throughput > self._HIGH_THROUGHPUT:
            # 高吞吐：增大批次，降低频率
            return self._buffer_chars >= self._MAX_CHARS or elapsed >= self._MAX_INTERVAL_S
        if avg_throughput < self._LOW_THROUGHPUT:
            # 低吞吐：减小批次，提高响应性
            return self._buffer_chars >= self._MIN_CHARS or elapsed >= self._MIN_INTERVAL_S
        # 中等吞吐：保持原始策略
        return self._buffer_chars >= self._STD_CHARS or elapsed >= self._STD_INTERVAL_S

    def get_content(self) -> str:
        """获取缓冲区内容"""
        return "".join(self._buffer)

    def clear(self) -> None:
        """清空缓冲区并记录指标"""
        chars_flushed = self._buffer_chars
        now = time.monotonic()

        if self._last_flush_time is not None:
            elapsed = now - self._last_flush_time
            if elapsed >= self._MIN_SAMPLE_INTERVAL_S:
                throughput = chars_flushed / elapsed
                self._throughput_history.append(throughput)

        self._buffer.clear()
        self._buffer_chars = 0
        self._last_flush_time = now
        self._metrics.flushes += 1

    def _estimate_throughput(self) -> float:
        """估算平均吞吐量 (chars/s)"""
        if not self._throughput_history:
            return 0.0
        return sum(self._throughput_history) / len(self._throughput_history)

    def get_metrics(self) -> BufferMetrics:
        """获取性能指标"""
        self._metrics.avg_throughput_chars_per_s = self._estimate_throughput()
        if self._last_flush_time is not None:
            self._metrics.elapsed_s = time.monotonic() - self._last_flush_time
        return self._metrics

    @property
    def size(self) -> int:
        """当前缓冲区字符数"""
        return self._buffer_chars

    @property
    def is_empty(self) -> bool:
        """缓冲区是否为空"""
        return self._buffer_chars == 0
