"""流式事件协议版本定义（Python 后端）

与前端 protocol-versioning.ts 对应，定义服务端事件格式。

版本演进策略：
- V1: 原始协议（现有代码）
- V2: 增强协议（支持取消、性能指标、流式输入）

使用方式：
    from runtime.protocol.realtime_schema import (
        RealtimeEventV2,
        ToolStartEventV2,
        CURRENT_PROTOCOL_VERSION,
    )

    event = ToolStartEventV2(
        tool_call_id="call_123",
        tool_name="read_file",
        input={"path": "/tmp/test.txt"},
        supports_cancellation=True,  # V2 特性
    )

    # 序列化时自动添加协议版本
    json_data = event.model_dump(by_alias=True, mode="json")
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ============================================================================
# 协议版本
# ============================================================================


class ProtocolVersion(BaseModel):
    """协议版本号"""

    major: int = Field(ge=1, description="主版本号（破坏性变更）")
    minor: int = Field(ge=0, description="次版本号（向后兼容的新功能）")
    patch: int = Field(ge=0, description="补丁版本号（Bug 修复）")


PROTOCOL_VERSION_V1 = ProtocolVersion(major=1, minor=0, patch=0)
PROTOCOL_VERSION_V2 = ProtocolVersion(major=2, minor=0, patch=0)
CURRENT_PROTOCOL_VERSION = PROTOCOL_VERSION_V2


# ============================================================================
# 基础事件
# ============================================================================


class BaseRealtimeEvent(BaseModel):
    """所有实时事件的基类"""

    type: str = Field(description="事件类型")
    protocol_version: ProtocolVersion = Field(
        default=CURRENT_PROTOCOL_VERSION,
        description="协议版本",
    )
    timestamp: int | None = Field(
        default=None,
        description="事件时间戳（毫秒）",
    )
    extended_metadata: dict[str, Any] | None = Field(
        default=None,
        description="扩展元数据（V2+）",
    )


# ============================================================================
# V1 事件（兼容现有代码）
# ============================================================================


class ToolStartEventV1(BaseRealtimeEvent):
    """工具启动事件 V1"""

    type: Literal["tool_start"] = "tool_start"
    tool_call_id: str = Field(description="工具调用 ID")
    tool_name: str = Field(description="工具名称")
    input: dict[str, Any] | None = Field(default=None, description="工具输入")
    input_preview: dict[str, Any] | None = Field(
        default=None,
        description="输入预览（简化版）",
    )
    parent_tool_use_id: str | None = Field(
        default=None,
        description="父工具调用 ID（嵌套调用）",
    )


class ToolEndEventV1(BaseRealtimeEvent):
    """工具结束事件 V1"""

    type: Literal["tool_end"] = "tool_end"
    tool_call_id: str = Field(description="工具调用 ID")
    tool_name: str = Field(description="工具名称")
    output: Any | None = Field(default=None, description="工具输出")
    output_preview: Any | None = Field(default=None, description="输出预览")
    status: str | None = Field(default=None, description="执行状态")
    is_error: bool = Field(default=False, description="是否错误")
    duration_ms: float | None = Field(default=None, description="执行时长（毫秒）")


# ============================================================================
# V2 事件（增强版）
# ============================================================================


class ToolStartEventV2(ToolStartEventV1):
    """工具启动事件 V2（增强）

    新增特性：
    - 支持取消（supports_cancellation）
    - 流式输入（input_stream_id）
    - 性能预算（estimated_duration_ms）
    """

    protocol_version: ProtocolVersion = Field(default=PROTOCOL_VERSION_V2)

    supports_cancellation: bool = Field(
        default=False,
        description="是否支持取消",
    )
    input_stream_id: str | None = Field(
        default=None,
        description="流式输入 ID（用于大型输入的增量传输）",
    )
    estimated_duration_ms: float | None = Field(
        default=None,
        description="预估执行时长（毫秒）",
    )


class PerformanceMetrics(BaseModel):
    """性能指标（V2）"""

    cpu_time_ms: float | None = Field(default=None, description="CPU 时间（毫秒）")
    memory_peak_mb: float | None = Field(default=None, description="内存峰值（MB）")
    io_read_bytes: int | None = Field(default=None, description="读取字节数")
    io_write_bytes: int | None = Field(default=None, description="写入字节数")


class ToolEndEventV2(ToolEndEventV1):
    """工具结束事件 V2（增强）

    新增特性：
    - 性能指标（performance_metrics）
    - 结构化错误（error_detail）
    """

    protocol_version: ProtocolVersion = Field(default=PROTOCOL_VERSION_V2)

    performance_metrics: PerformanceMetrics | None = Field(
        default=None,
        description="性能指标",
    )
    error_detail: dict[str, Any] | None = Field(
        default=None,
        description="结构化错误详情",
    )


# ============================================================================
# 事件联合类型
# ============================================================================

RealtimeEventV1 = ToolStartEventV1 | ToolEndEventV1
RealtimeEventV2 = ToolStartEventV2 | ToolEndEventV2
RealtimeEvent = RealtimeEventV1 | RealtimeEventV2


# ============================================================================
# 辅助函数
# ============================================================================


def make_tool_start_event(
    tool_call_id: str,
    tool_name: str,
    input_data: dict[str, Any] | None = None,
    *,
    use_v2: bool = True,
    supports_cancellation: bool = False,
) -> ToolStartEventV1 | ToolStartEventV2:
    """创建工具启动事件

    Args:
        tool_call_id: 工具调用 ID
        tool_name: 工具名称
        input_data: 工具输入
        use_v2: 是否使用 V2 协议
        supports_cancellation: 是否支持取消（仅 V2）

    Returns:
        工具启动事件
    """
    if use_v2:
        return ToolStartEventV2(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            input=input_data,
            supports_cancellation=supports_cancellation,
        )
    return ToolStartEventV1(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        input=input_data,
    )


def make_tool_end_event(
    tool_call_id: str,
    tool_name: str,
    output: Any | None = None,
    *,
    use_v2: bool = True,
    duration_ms: float | None = None,
    performance_metrics: PerformanceMetrics | None = None,
    is_error: bool = False,
) -> ToolEndEventV1 | ToolEndEventV2:
    """创建工具结束事件

    Args:
        tool_call_id: 工具调用 ID
        tool_name: 工具名称
        output: 工具输出
        use_v2: 是否使用 V2 协议
        duration_ms: 执行时长（毫秒）
        performance_metrics: 性能指标（仅 V2）
        is_error: 是否错误

    Returns:
        工具结束事件
    """
    if use_v2:
        return ToolEndEventV2(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            output=output,
            duration_ms=duration_ms,
            performance_metrics=performance_metrics,
            is_error=is_error,
            status="error" if is_error else "success",
        )
    return ToolEndEventV1(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        output=output,
        duration_ms=duration_ms,
        is_error=is_error,
        status="error" if is_error else "success",
    )
