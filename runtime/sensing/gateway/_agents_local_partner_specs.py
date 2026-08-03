"""Registry of supported LocalPartner CLI specs.

Extracted from ``agents_local_partner.py`` (god-file reduction). The exact
commands / tool groups / icons each partner resolves to are declared here so
both the connect dialog and the detection code read from one source.
"""

from __future__ import annotations

from typing import Any

LOCAL_PARTNER_SPECS: dict[str, dict[str, Any]] = {
    "claude-code": {
        "id": "claude-code",
        "agent_id": "local_claude_code",
        "name": "Claude Code",
        "default_alias": "Claude Code 伙伴",
        "description": "检测本机 Claude Code CLI，注册为可被团队指派的本地开发伙伴。",
        "commands": ["claude", "claude.cmd", "claude.exe", "claude.ps1"],
        "tool_groups": ["web_read", "fs_writer", "git", "shell"],
        "tags": ["local", "partner", "coding", "claude"],
        "icon": "CC",
        "avatar_url": "https://claude.ai/favicon.ico",
    },
    "codex-cli": {
        "id": "codex-cli",
        "agent_id": "local_codex_cli",
        "name": "Codex CLI",
        "default_alias": "Codex CLI 伙伴",
        "description": "检测本机 Codex CLI，注册为可被团队指派的本地工程伙伴。",
        "commands": ["codex", "codex.cmd", "codex.exe", "codex.ps1"],
        "tool_groups": ["web_read", "fs_writer", "git", "shell"],
        "tags": ["local", "partner", "coding", "codex"],
        "icon": "CX",
        "avatar_url": "https://chatgpt.com/favicon.ico",
    },
    "openclaw": {
        "id": "openclaw",
        "agent_id": "local_openclaw",
        "name": "OpenClaw",
        "default_alias": "OpenClaw 伙伴",
        "description": "检测本机 OpenClaw 自动化能力，注册为可被团队指派的本地执行伙伴。",
        "commands": ["openclaw", "openclaw.cmd", "openclaw.exe", "openclaw.ps1"],
        "tool_groups": ["desktop_operator", "shell"],
        "tags": ["local", "partner", "automation", "desktop"],
        "icon": "OC",
    },
    "trae-cli": {
        "id": "trae-cli",
        "agent_id": "local_trae_cli",
        "name": "Trae CLI",
        "default_alias": "Trae CLI 伙伴",
        "description": "检测本机 Trae CLI，注册为可被团队指派的本地工程伙伴。",
        "commands": [
            "trae-cli",
            "traecli",
            "trae-agent",
            "ta",
            "trae",
            "trae.cmd",
            "trae.exe",
            "trae.ps1",
        ],
        "tool_groups": ["web_read", "fs_writer", "git", "shell"],
        "tags": ["local", "partner", "coding", "trae"],
        "icon": "TR",
        "avatar_url": "https://lf-static.traecdn.us/obj/trae-ai-tx/trae_website/favicon.png",
    },
    "qoder-cli": {
        "id": "qoder-cli",
        "agent_id": "local_qoder_cli",
        "name": "Qoder CLI",
        "default_alias": "Qoder CLI 伙伴",
        "description": "检测本机 Qoder CLI，注册为可被团队指派的本地工程伙伴。",
        "commands": [
            "qodercli",
            "qoder",
            "qoder-cli",
            "qodercli.cmd",
            "qodercli.exe",
            "qodercli.ps1",
            "qoder.cmd",
            "qoder.exe",
            "qoder.ps1",
        ],
        "tool_groups": ["web_read", "fs_writer", "git", "shell"],
        "tags": ["local", "partner", "coding", "qoder"],
        "icon": "QD",
        "avatar_url": (
            "https://img.alicdn.com/imgextra/i3/"
            "O1CN01KliT1u1jEq947NlKH_!!6000000004517-55-tps-180-180.svg"
        ),
    },
    "kimi-cli": {
        "id": "kimi-cli",
        "agent_id": "local_kimi_cli",
        "name": "Kimi CLI",
        "default_alias": "Kimi CLI 伙伴",
        "description": "检测本机 Kimi CLI，注册为可被团队指派的本地工程伙伴。",
        "commands": [
            "kimi",
            "kimi-cli",
            "kimi-code",
            "kimi-coding",
            "kimi-code.cmd",
            "kimi-code.exe",
            "kimi-code.ps1",
            "kimi.cmd",
            "kimi.exe",
            "kimi.ps1",
        ],
        "tool_groups": ["web_read", "fs_writer", "git", "shell"],
        "tags": ["local", "partner", "coding", "kimi"],
        "icon": "KM",
        "avatar_url": "https://www.kimi.com/favicon.ico",
    },
    "codebuddy-cli": {
        "id": "codebuddy-cli",
        "agent_id": "local_codebuddy_cli",
        "name": "CodeBuddy CLI",
        "default_alias": "CodeBuddy CLI 伙伴",
        "description": (
            "检测本机腾讯 CodeBuddy CLI，注册为可被团队指派的本地工程伙伴。"
            "官方 codebuddy 命令支持 headless 输出；桌面版 buddy 启动器仅作为发现兜底。"
        ),
        "commands": [
            "codebuddy",
            "codebuddy-code",
            "cbc",
            "codebuddy.cmd",
            "codebuddy.exe",
            "codebuddy.ps1",
            "cbc.cmd",
            "cbc.exe",
            "cbc.ps1",
            "~/.codebuddy/bin/buddy",
        ],
        "tool_groups": ["web_read", "fs_writer", "git", "shell"],
        "tags": ["local", "partner", "coding", "codebuddy", "tencent"],
        "icon": "CB",
        "avatar_url": "https://codebuddy-1328495429.cos.accelerate.myqcloud.com/web/ide/logo.svg",
    },
}


__all__ = ["LOCAL_PARTNER_SPECS"]
