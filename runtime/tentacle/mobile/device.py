"""MobileDevice —— Android 触手实现（Phase 1）.

本文件实现 WebSocket 客户端，通过 TentacleWebSocketServer 与 octopus-agent 通信。
Octopus Mobile 端（Kotlin）通过 WebSocket 连接本服务器，接收 tool/execute 指令并返回结果。

30 个工具的实现代码 100% 复用 Octopus Mobile 现有 BaseTool。
本类只负责"通信 + 协议"，不重复实现工具。

详见：
- ``docs/biomimetic/tentacle/mobile.md``
- ``docs/mobile/architecture.md`` 第 3 节
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..base import (
    Heartbeat,
    Tentacle,
    TentacleStatus,
    TentacleType,
    ToolCall,
    ToolResult,
    now_ms,
)
from ..transport.ws_server import TentacleWebSocketServer

logger = logging.getLogger(__name__)

# 30 个 Android 技能的标准清单（与 Octopus Mobile 现有 BaseTool 一一对应）
ANDROID_CAPABILITIES: list[str] = [
    # 基础操作
    "android.tap", "android.swipe", "android.input_text",
    "android.long_press", "android.system_key",
    # 屏幕感知
    "android.get_screen_info", "android.take_screenshot",
    "android.find_node", "android.find_text",
    # 应用管理
    "android.open_app", "android.install_app",
    "android.get_installed_apps", "android.wait",
    # 智能复合
    "android.scroll_to_find", "android.detect_dialog",
    "android.find_and_tap", "android.get_current_app",
    # 任务控制
    "android.finish", "android.fail",
    # 文件 / 剪贴板
    "android.read_file", "android.write_file",
    "android.get_clipboard", "android.set_clipboard",
    # 浏览器（Phase 7，远期）
    "android.browser.navigate", "android.browser.get_dom",
    "android.browser.click", "android.browser.type",
    "android.browser.screenshot", "android.browser.evaluate",
    "android.browser.install_extension",
]


class MobileDevice:
    """Android 设备触手.

    Phase 1 实现：通过 TentacleWebSocketServer 与 Octopus Mobile 通信.

    Args:
        tentacle_id: 全局唯一 ID（如 "android-abc123"）
        device_meta: 设备元信息
        ws_server: TentacleWebSocketServer 实例（用于发送指令）
    """

    def __init__(
        self,
        tentacle_id: str,
        device_meta: dict[str, Any] | None = None,
        ws_server: TentacleWebSocketServer | None = None,
    ) -> None:
        self.tentacle_id = tentacle_id
        self.tentacle_type = TentacleType.MOBILE
        self.platform = "android"
        self.meta = device_meta or {
            "brand": "Unknown",
            "model": "Unknown",
            "android_version": "14",
            "sdk": 34,
            "screen_size": [1080, 2400],
        }
        self._ws_server = ws_server

        # 状态
        self._status: TentacleStatus = TentacleStatus.OFFLINE
        self._last_used_at: float = 0.0
        self._capabilities: list[str] = list(ANDROID_CAPABILITIES)

    # ── Tentacle 接口实现 ──────────────────────────────────

    @property
    def capabilities(self) -> list[str]:
        return list(self._capabilities)

    @property
    def status(self) -> TentacleStatus:
        return self._status

    @property
    def is_online(self) -> bool:
        return self._status in (TentacleStatus.ONLINE, TentacleStatus.BUSY)

    @property
    def is_busy(self) -> bool:
        return self._status == TentacleStatus.BUSY

    @property
    def last_used_at(self) -> float:
        return self._last_used_at

    async def connect(self) -> None:
        """连接设备.

        - 有 ws_server 时：标记为 CONNECTING，等待 device/hello 回调 mark_online()
        - 无 ws_server 时（mock/测试）：直接标记为 ONLINE
        """
        if self._ws_server is not None:
            self._status = TentacleStatus.CONNECTING
            logger.info("MobileDevice waiting for WebSocket connection id=%s", self.tentacle_id)
        else:
            self._status = TentacleStatus.ONLINE
            logger.info("MobileDevice mock-connect id=%s", self.tentacle_id)

    def mark_online(self) -> None:
        """由 ws_server 回调触发 —— 设备已连接."""
        self._status = TentacleStatus.ONLINE
        logger.info("MobileDevice online id=%s", self.tentacle_id)

    async def disconnect(self) -> None:
        """断开设备."""
        self._status = TentacleStatus.OFFLINE
        logger.info("MobileDevice disconnected id=%s", self.tentacle_id)

    async def heartbeat(self) -> Heartbeat:
        """心跳 —— 返回最后已知状态."""
        if not self.is_online:
            return Heartbeat(
                tentacle_id=self.tentacle_id,
                ts=now_ms(),
                online=False,
            )
        return Heartbeat(
            tentacle_id=self.tentacle_id,
            ts=now_ms(),
            online=True,
            current_app=self.meta.get("current_app"),
            screen_on=self.meta.get("screen_on", True),
            battery=self.meta.get("battery", 85),
            is_charging=self.meta.get("is_charging", False),
            last_screen_tree_hash=self.meta.get("last_screen_tree_hash"),
            running_tasks=self.meta.get("running_tasks", 0),
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        """执行工具调用.

        Phase 1: 通过 WebSocket Server 转发给 Octopus Mobile，等待结果.
        无 ws_server 时（mock/测试）：返回模拟成功结果.
        """
        start = time.time()
        if not self.is_online:
            return ToolResult.fail(
                call.call_id, -32011, "Device offline", 0
            )
        if call.tool not in self._capabilities:
            return ToolResult.fail(
                call.call_id, -32003, f"Unknown tool: {call.tool}", 0
            )
        if self._ws_server is None:
            # Mock 模式：模拟成功执行
            return ToolResult(
                call_id=call.call_id,
                success=True,
                data=f"mock:{call.tool}",
                error_code=None,
                error_message=None,
                duration_ms=1,
                screenshot_after=None,
                screen_hash_after=None,
                extra={},
            )

        self._status = TentacleStatus.BUSY
        try:
            result = await self._ws_server.send_tool_execute(
                self.tentacle_id, call, timeout_ms=call.timeout_ms
            )
            return result
        except Exception as e:
            return ToolResult.fail(
                call.call_id, -32015, f"Execute error: {e}", int((time.time() - start) * 1000)
            )
        finally:
            self._status = TentacleStatus.ONLINE
            self._last_used_at = time.time()

    def __repr__(self) -> str:
        return (
            f"MobileDevice(id={self.tentacle_id!r}, "
            f"status={self._status.value!r}, "
            f"caps={len(self._capabilities)})"
        )
