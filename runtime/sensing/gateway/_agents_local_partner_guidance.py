"""UX guidance / command hints / diagnostics for the LocalPartner connect dialog.

Extracted from ``agents_local_partner.py`` (god-file reduction). Keep these
provider-specific strings here so each partner's quirks are reviewable with the
detection code, and the UI never needs provider-specific branching.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from runtime.execution.agents.local_partner_bridge import build_partner_argv
from runtime.platform.process.paths import project_root

_SHELL_BARE_COMMAND_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./~-]+$")


def _display_command(command: str | None) -> str | None:
    if not command:
        return None
    return command if _SHELL_BARE_COMMAND_RE.fullmatch(command) else shlex.quote(command)


def _is_codebuddy_launcher(command: str) -> bool:
    exe_name = Path(command).name.lower()
    normalized = command.replace("\\", "/")
    return exe_name in {"buddy", "buddy.exe", "buddy.cmd", "buddy.ps1"} or (
        exe_name == "code" and "/CodeBuddy.app/" in normalized
    )


def _partner_guidance(
    partner_id: str,
    command: str | None,
    *,
    ready: bool,
    headless_supported: bool,
) -> dict[str, str | None]:
    """Copyable commands/instructions for the connect dialog.

    The UI should not need provider-specific branching for "how do I open this
    natively?" or "how do I verify it can be driven headless?". Keeping these
    strings here makes each partner's quirks reviewable with the detection code.
    """
    native = _display_command(command) if command else None
    install: str | None = None
    setup_hint: str | None = None
    verify: str | None = None

    if partner_id == "codebuddy-cli":
        install = "npm install -g @tencent-ai/codebuddy-code"
        setup_hint = (
            "首次使用请运行原生 CodeBuddy CLI，并按提示登录/授权；"
            "桌面端账号或免费权益不一定会同步到 CLI。"
        )
        if command and not _is_codebuddy_launcher(command):
            native = _display_command(command)
            verify = shlex.join(
                [
                    command,
                    "-p",
                    "--output-format",
                    "text",
                    "--permission-mode",
                    "plan",
                    "--max-turns",
                    "1",
                    "请只回复 OK，不要修改文件。",
                ]
            )
    elif partner_id == "trae-cli":
        if command:
            setup_hint = (
                "Trae CLI 需要在原生 CLI 内完成模型选择；若 models 为空，请先处理 CLI 账号、"
                "企业网络或模型授权。桌面端可用不代表 CLI 已获得同一权益。"
            )
        if command:
            verify = shlex.join([command, "models", "--json"])
    elif partner_id == "qoder-cli":
        if command:
            setup_hint = (
                "Qoder CLI 会走 -p headless 模式；若不可用，请先在原生 CLI 内完成登录/授权，"
                "并确认 CLI 账号权益可用。"
            )
    elif partner_id == "kimi-cli":
        if command:
            setup_hint = (
                "已保留 Kimi 入口；等官方稳定 prompt→stdout headless 参数后再启用自动派工。"
            )
    elif partner_id == "claude-code":
        if command:
            setup_hint = "使用 Claude Code 自己的登录态、订阅权益和模型配置；Octopus 只负责派工。"
    elif partner_id == "codex-cli":
        if command:
            setup_hint = "使用 Codex CLI 自己的登录态、订阅权益和模型配置；Octopus 只负责派工。"
    elif partner_id == "opencode-cli":
        if command:
            setup_hint = (
                "使用 OpenCode CLI 自己的 Provider 登录态和模型配置；"
                "Octopus 通过 `opencode run` 做一次性派工。"
            )

    if command and headless_supported and not verify:
        argv = build_partner_argv(partner_id, command, "请只回复 OK，不要修改文件。")
        if argv:
            verify = shlex.join(argv)
    if ready and not setup_hint:
        setup_hint = "已可被 Octopus 自动派工；也可以打开原生 CLI 使用它自己的快捷指令。"

    if partner_id in {"claude-code", "codex-cli", "codebuddy-cli", "opencode-cli"}:
        interaction_hint = (
            "Octopus 这里是一次性派工入口，不是原生交互终端；"
            "`/model <模型名>` 可转成本次模型覆盖，`/login`、`/doctor`、`/clear` "
            "等会话/账号指令请回原生 CLI 使用。"
        )
    elif partner_id == "trae-cli":
        interaction_hint = (
            "Trae 的模型、登录和企业网络状态由 Trae CLI 自己管理；"
            "Octopus 只做派工，不转发 Trae 原生 `/` 指令，也不会继承 Trae 桌面端免费额度。"
        )
    elif partner_id in {"qoder-cli", "kimi-cli"}:
        interaction_hint = (
            "Octopus 会保留原文任务并尽量走该 CLI 的 headless 能力；"
            "原生 `/` 指令请在对应 CLI 终端里使用。"
        )
    else:
        interaction_hint = None

    launch_cwd = str(project_root()) if native else None
    return {
        "install_command": install if not command else None,
        "native_command": native,
        "native_launch_command": (
            f"cd {shlex.quote(launch_cwd)} && {native}" if native and launch_cwd else None
        ),
        "native_launch_cwd": launch_cwd,
        "verify_command": verify,
        "setup_hint": setup_hint,
        "interaction_hint": interaction_hint,
    }


def _partner_command_hints(partner_id: str) -> list[dict[str, str]]:
    """Small UX map for native-CLI muscle memory in Octopus.

    These are intentionally product-facing, not exhaustive vendor docs. They
    answer the question users hit first: "If I type a familiar / command here,
    will Octopus run it, translate it, or tell me to open the native CLI?"
    """
    hints = [
        {
            "command": "/help",
            "scope": "Octopus 说明",
            "behavior": "显示本地伙伴兼容说明，不转发给外部 CLI。",
        },
        {
            "command": "/models",
            "scope": "Octopus 说明",
            "behavior": "解释模型来源；不会调用外部 CLI 的交互式模型菜单。",
        },
        {
            "command": "/login /doctor /status",
            "scope": "原生 CLI",
            "behavior": "账号、诊断、状态类命令请在原生 CLI 终端里执行。",
        },
        {
            "command": "/clear /compact /resume",
            "scope": "原生 CLI",
            "behavior": "会话类命令不转发；在 Octopus 里请开启新任务或回原生 CLI。",
        },
    ]
    if partner_id in {"claude-code", "codex-cli", "codebuddy-cli", "opencode-cli"}:
        hints.insert(
            0,
            {
                "command": "/model <模型名>",
                "scope": "一次性覆盖",
                "behavior": "换行接任务时，转成该 CLI 本次调用的模型参数。",
            },
        )
    else:
        hints.insert(
            0,
            {
                "command": "/model <模型名>",
                "scope": "CLI 默认",
                "behavior": "Octopus 会识别意图，但本伙伴暂不支持稳定模型参数，仍使用 CLI 默认模型。",
            },
        )
    if partner_id == "trae-cli":
        hints.append(
            {
                "command": "trae-cli models --json",
                "scope": "原生 CLI",
                "behavior": "用于确认 Trae CLI 账号/企业网络下是否已经分配可用模型。",
            }
        )
    return hints


def _partner_diagnostic_items(
    partner_id: str,
    *,
    command: str | None,
    ready: bool,
    headless_supported: bool,
    readiness_status: str,
    verify_command: str | None,
) -> list[dict[str, str]]:
    """Compact provider-owned diagnostics for the connect dialog.

    These are intentionally generated server-side because each CLI owns a
    different model namespace, login boundary, and headless capability. The UI
    renders the matrix without duplicating partner-specific rules.
    """
    model_value = "CLI 默认"
    model_detail = "模型由该 CLI 自己的配置决定；Octopus 不使用全局模型列表覆盖它。"
    if partner_id in {"claude-code", "codex-cli", "codebuddy-cli", "opencode-cli"}:
        model_value = "可一次性覆盖"
        model_detail = "`/model <模型名>` 换行接任务时会转成本次 CLI 模型参数。"
    elif partner_id == "trae-cli":
        model_value = "Trae CLI models"
        model_detail = "以 `trae-cli models --json` 和原生 `/model` 配置为准。"
    elif partner_id == "kimi-cli":
        model_value = "待 headless 稳定"
        model_detail = "保留发现入口；稳定 prompt→stdout 参数明确后再启用自动派工。"

    account_detail = "桌面端账号、免费权益、企业授权不一定同步到 CLI。"
    if partner_id in {"claude-code", "codex-cli", "opencode-cli"}:
        account_detail = "使用该 CLI 自己的登录态、订阅权益和模型配置。"
    elif partner_id == "codebuddy-cli":
        account_detail = "首次运行原生 CodeBuddy CLI 登录/授权；桌面端权益不保证同步。"
    elif partner_id == "trae-cli":
        account_detail = "Trae 桌面端可用不代表 CLI 已获得同一模型/企业权益。"

    headless_value = "可自动派工" if headless_supported else "仅原生/待适配"
    headless_tone = "ready" if ready else ("warning" if command else "blocked")
    if readiness_status in {"launcher_only", "headless_unsupported"}:
        headless_tone = "blocked"
    elif readiness_status == "model_unconfigured":
        headless_tone = "warning"

    check_value = verify_command or "先安装/打开原生 CLI"
    check_detail = (
        "复制验证命令或点健康检查确认真实 prompt→stdout 可用。"
        if verify_command
        else "未发现可验证的 headless 命令；先安装官方 CLI 或回原生终端处理。"
    )

    return [
        {
            "label": "模型来源",
            "value": model_value,
            "tone": "ready" if ready else "warning",
            "detail": model_detail,
        },
        {
            "label": "账号/权益",
            "value": "CLI 独立",
            "tone": "warning",
            "detail": account_detail,
        },
        {
            "label": "Headless",
            "value": headless_value,
            "tone": headless_tone,
            "detail": f"当前状态：{readiness_status}。",
        },
        {
            "label": "检查命令",
            "value": check_value,
            "tone": "neutral" if verify_command else "blocked",
            "detail": check_detail,
        },
    ]


__all__ = [
    "_is_codebuddy_launcher",
    "_partner_command_hints",
    "_partner_diagnostic_items",
    "_partner_guidance",
]
