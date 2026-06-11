"""Octopus Mobile —— 手机触手模块.

将 mobile 相关的所有子模块统一导出，外部只需:

    from runtime.tentacle.mobile import MobileDevice, TentacleMcpServer, ...
"""

from .device import MobileDevice, ANDROID_CAPABILITIES
from .cerebrum_adapter import CerebrumDecisionAdapter
from .mcp_server import TentacleMcpServer, serve_stdio, SseSession, SseSessionManager
from .screen_relay import ScreenRelay, FrameType, FrameFlags
from .pc_screen_capture import PcScreenCapture, PcScreenConfig, RemoteInputHandler, PC_HOST_ID
from .run_server import main as run_server_main

__all__ = [
    # device
    "MobileDevice",
    "ANDROID_CAPABILITIES",
    # cerebrum
    "CerebrumDecisionAdapter",
    # mcp
    "TentacleMcpServer",
    "serve_stdio",
    "SseSession",
    "SseSessionManager",
    # screen relay
    "ScreenRelay",
    "FrameType",
    "FrameFlags",
    # pc screen capture
    "PcScreenCapture",
    "PcScreenConfig",
    "RemoteInputHandler",
    "PC_HOST_ID",
    # run_server
    "run_server_main",
]
