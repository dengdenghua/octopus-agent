"""自适应批处理缓冲器的单元测试"""

import asyncio
import time

import pytest

from runtime.sensing.gateway.adaptive_delta_buffer import AdaptiveDeltaBuffer


def test_first_flush_immediate():
    """首次刷新应立即触发 (time-to-first-token)"""
    buffer = AdaptiveDeltaBuffer()
    buffer.append("first")
    assert buffer.should_flush()


def test_low_throughput_small_batch():
    """低吞吐量应使用小批次策略"""
    buffer = AdaptiveDeltaBuffer()

    # 模拟低吞吐 (<100 chars/s)
    buffer.append("a")
    buffer._last_flush_time = time.monotonic()
    buffer.clear()

    # 推送几次建立吞吐量历史
    for _ in range(5):
        buffer.append("b" * 10)  # 10 chars
        time.sleep(0.15)  # ~67 chars/s
        buffer._last_flush_time = time.monotonic() - 0.15
        buffer.clear()

    # 现在应该使用小批次阈值 (32 chars / 16ms)
    buffer.append("c" * 20)
    buffer._last_flush_time = time.monotonic() - 0.001  # 1ms
    assert not buffer.should_flush()  # 未达到 32 chars

    buffer.append("d" * 15)  # 总共 35 chars
    assert buffer.should_flush()  # 超过 32 chars


def test_high_throughput_large_batch():
    """高吞吐量应使用大批次策略"""
    buffer = AdaptiveDeltaBuffer()

    # 模拟高吞吐 (>1000 chars/s)
    buffer.append("x")
    buffer._last_flush_time = time.monotonic()
    buffer.clear()

    # 建立高吞吐历史
    for _ in range(5):
        buffer.append("y" * 200)  # 200 chars
        buffer._last_flush_time = time.monotonic() - 0.1  # 2000 chars/s
        buffer.clear()

    # 应该使用大批次阈值 (256 chars / 64ms)
    buffer.append("z" * 100)
    buffer._last_flush_time = time.monotonic() - 0.01  # 10ms
    assert not buffer.should_flush()  # 未达到 256 chars 也未达到 64ms

    buffer.append("z" * 160)  # 总共 260 chars
    assert buffer.should_flush()  # 超过 256 chars


def test_time_based_flush():
    """超时应触发刷新"""
    buffer = AdaptiveDeltaBuffer()
    buffer.append("x")
    buffer._last_flush_time = time.monotonic()
    buffer.clear()

    buffer.append("test")
    buffer._last_flush_time = time.monotonic() - 0.100  # 100ms 前
    assert buffer.should_flush()  # 超过最大间隔 64ms


def test_empty_buffer_no_flush():
    """空缓冲区不应刷新"""
    buffer = AdaptiveDeltaBuffer()
    assert not buffer.should_flush()


def test_metrics_tracking():
    """应正确追踪性能指标"""
    buffer = AdaptiveDeltaBuffer()

    buffer.append("a" * 50)
    buffer._last_flush_time = time.monotonic()
    buffer.clear()

    buffer.append("b" * 100)
    buffer._last_flush_time = time.monotonic() - 0.05  # 2000 chars/s
    buffer.clear()

    metrics = buffer.get_metrics()
    assert metrics.chars_accumulated == 150
    assert metrics.flushes == 2
    assert metrics.avg_throughput_chars_per_s > 0


def test_get_content():
    """应正确拼接缓冲区内容"""
    buffer = AdaptiveDeltaBuffer()
    buffer.append("Hello")
    buffer.append(" ")
    buffer.append("World")

    assert buffer.get_content() == "Hello World"
    assert buffer.size == 11


def test_clear_resets_buffer():
    """清空应重置缓冲区但保留历史"""
    buffer = AdaptiveDeltaBuffer()
    buffer.append("test")
    buffer._last_flush_time = time.monotonic() - 0.05  # 模拟真实刷新间隔
    buffer.clear()

    assert buffer.is_empty
    assert buffer.size == 0
    assert len(buffer._throughput_history) > 0  # 历史应保留


@pytest.mark.asyncio
async def test_realistic_streaming_scenario():
    """模拟真实流式场景"""
    buffer = AdaptiveDeltaBuffer()
    chunks_sent = []

    # 模拟 LLM 流式输出
    async def simulate_stream():
        # 初始慢速（模型预热）
        for _ in range(3):
            buffer.append("初")
            await asyncio.sleep(0.1)
            if buffer.should_flush():
                chunks_sent.append(buffer.get_content())
                buffer.clear()

        # 然后快速（稳定输出）
        for _ in range(20):
            buffer.append("快速输出" * 5)
            await asyncio.sleep(0.01)
            if buffer.should_flush():
                chunks_sent.append(buffer.get_content())
                buffer.clear()

        # 最后剩余内容
        if not buffer.is_empty:
            chunks_sent.append(buffer.get_content())
            buffer.clear()

    await simulate_stream()

    # 验证结果
    assert len(chunks_sent) > 0
    assert len(chunks_sent) < 23  # 应该有批处理效果
    assert "".join(chunks_sent).count("初") == 3
    assert "".join(chunks_sent).count("快速输出") == 100  # 20 * 5
