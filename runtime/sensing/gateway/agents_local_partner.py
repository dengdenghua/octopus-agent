"""LocalPartner subsystem — detection + secure registration.

Extracted from ``agents_router.py`` (2026-06) to keep that file under
the god-file threshold. LocalPartner registers external CLI tools
(Claude Code, Codex, Trae, Qoder, Kimi, OpenClaw) as agents in the registry so the team
can dispatch tasks to them via shell.

Security model:
  * Aliases (user-provided display names) are validated against a
    strict regex that blocks markdown/control chars — see
    ``validate_alias`` and ``_LOCAL_PARTNER_ALIAS_RE``.
  * Executable paths from ``shutil.which`` are checked against the
    current working directory to defeat PATH-poisoning attacks
    (see ``safe_executable``).
  * Admin role required at the router layer — see
    ``identity_has_admin_role`` and the ``/api/agents/local-partners``
    endpoints in ``agents_router.py``.

Module organization:
  * ``LOCAL_PARTNER_SPECS`` — the registry of supported partners
  * ``validate_alias`` / ``identity_has_admin_role`` — security gates
  * ``safe_executable`` — PATH-poisoning defense
  * ``which_command`` / ``dir_registered`` — detection helpers
  * ``to_wire`` / ``soul_template`` — output formatters
  * ``write_partner_agent`` — the registration writer
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from runtime.execution.agents.local_partner_bridge import build_partner_argv, run_local_partner
from runtime.execution.misc.agent_avatar import pixel_agent_avatar_svg
from runtime.platform.process.paths import project_root

from .agents_models import LocalPartnerWire

# ── Security primitives ────────────────────────────────────────────
#
# These constants and helpers fence off the shape of user-controllable
# values that flow into LLM context (SOUL.md, IDENTITY.md) or trigger
# command resolution (shutil.which).
#
# ``_LOCAL_PARTNER_ALIAS_RE`` is intentionally tight:
#   * 1..64 chars
#   * letters / digits / CJK / space / a few punctuation marks
#   * no control chars, no slashes, no markdown break-out chars
#
# Tightening past prompt-injection still leaves SOUL.md as a markdown
# file the LLM may eventually read — so we additionally require alias
# to not look like an instruction stub. We don't claim immunity, just
# defense in depth.

# Allowed alias characters: letters, digits, CJK, regular space,
# hyphen, underscore, dot. Notably NOT \s (which would allow \n / \r
# / \t and enable line-break-based prompt injection into SOUL.md).
# Length capped at 64. Rejecting markdown structural chars
# (`*` `_` `[` `]` `(` `)` `>` `#`) prevents trivial markdown
# break-out from the SOUL template.
_LOCAL_PARTNER_ALIAS_RE = re.compile(
    r"^[A-Za-z0-9一-龥　-〿 .\-_]{1,64}$",
)
_SAFE_LOCAL_PARTNER_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _require_safe_agent_id(value: str) -> str:
    agent_id = str(value or "").strip()
    if not _SAFE_LOCAL_PARTNER_AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError(
            "local partner agent_id may only contain alphanumeric characters, "
            "hyphens, and underscores"
        )
    return agent_id


def _cleanup_created_agent_dir(agent_dir: Path, *, created: bool) -> None:
    if created and agent_dir.is_dir() and not agent_dir.is_symlink():
        shutil.rmtree(agent_dir, ignore_errors=True)


def validate_alias(value: str | None) -> str:
    """Reject aliases that could pollute SOUL.md / IDENTITY.md or DoS disk.

    Raises ``ValueError`` on bad input — caller must convert to HTTP 400.
    """
    if value is None:
        return ""
    candidate = value.strip()
    if not candidate:
        return ""
    if len(candidate) > 64:
        raise ValueError("alias must be 64 chars or fewer")
    if not _LOCAL_PARTNER_ALIAS_RE.fullmatch(candidate):
        raise ValueError("alias may only contain letters, digits, CJK, spaces, '.', '-', '_'")
    return candidate


def identity_has_admin_role(identity: Any) -> bool:
    """Conservative admin check.

    True iff the resolved identity carries the ``admin`` role. This is
    the gate for endpoints that mutate global agent registry / write
    files under ``default_agents_root()``.
    """
    if identity is None:
        return False
    roles = getattr(identity, "roles", ()) or ()
    return "admin" in {str(role).lower() for role in roles}


def safe_executable(executable_path: str) -> bool:
    """Reject executables that resolve into the current working
    directory subtree. Defense against the most common PATH-poisoning
    scenario: an attacker drops a fake ``claude.cmd`` in cwd and
    Windows' default ``.``-in-PATH resolves to it before the real one.

    Note we INTENTIONALLY do not reject paths under the user's home —
    legitimate per-user installs of Claude Code, Codex, etc. live
    there (``~/AppData/Local/Programs/...`` on Windows, ``~/.local/bin``
    on Linux). Rejecting home-paths would block every real install.

    Returns True iff the resolved path lives outside cwd. When path
    resolution fails we REJECT (fail-closed) — a resolve error means
    we cannot verify the path is safe, and accepting it would open a
    PATH-poisoning vector.
    """
    from pathlib import Path

    try:
        resolved = Path(executable_path).resolve()
    except (OSError, RuntimeError):
        return False  # fail-closed on resolve error

    try:
        cwd = Path.cwd().resolve()
    except (OSError, RuntimeError):
        return False  # fail-closed on resolve error

    try:
        resolved.relative_to(cwd)
    except ValueError:
        return True
    return False


# ── Partner specs registry ─────────────────────────────────────────

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


# ── Model config (the CLI's OWN model namespace) ───────────────────


def _trae_model_label(command: str | None = None) -> tuple[str, str]:
    if not command:
        command, _path = which_command(list(LOCAL_PARTNER_SPECS["trae-cli"]["commands"]))
    if not command:
        return "", ""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv list, no shell
            [command, "models", "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "Trae CLI 默认", command
    try:
        models = json.loads(proc.stdout or "[]")
    except ValueError:
        models = []
    if isinstance(models, list) and not models:
        return "未配置模型", f"{command} models --json"
    return "Trae CLI 默认", command


_CODEBUDDY_MODELS_RE = re.compile(r"Currently supported:\s*\(([^)]*)\)", re.IGNORECASE)


def _is_codebuddy_launcher(command: str) -> bool:
    exe_name = Path(command).name.lower()
    normalized = command.replace("\\", "/")
    return exe_name in {"buddy", "buddy.exe", "buddy.cmd", "buddy.ps1"} or (
        exe_name == "code" and "/CodeBuddy.app/" in normalized
    )


def _parse_codebuddy_models(help_text: str) -> list[str]:
    match = _CODEBUDDY_MODELS_RE.search(help_text or "")
    if not match:
        return []
    return [item.strip() for item in match.group(1).split(",") if item.strip()]


def _codebuddy_model_options(command: str | None = None) -> tuple[list[str], str]:
    if not command:
        command, _path = which_command(list(LOCAL_PARTNER_SPECS["codebuddy-cli"]["commands"]))
    if not command or _is_codebuddy_launcher(command):
        return [], ""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv list, no shell
            [command, "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], command
    models = _parse_codebuddy_models(f"{proc.stdout or ''}\n{proc.stderr or ''}")
    return models, f"{command} --help" if models else command


_SHELL_BARE_COMMAND_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./~-]+$")


def _display_command(command: str | None) -> str | None:
    if not command:
        return None
    return command if _SHELL_BARE_COMMAND_RE.fullmatch(command) else shlex.quote(command)


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
        setup_hint = "首次使用请运行原生 CodeBuddy CLI，并按提示登录/授权。"
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
            setup_hint = "Trae CLI 需要在原生 CLI 内完成模型选择；若 models 为空，请先处理账号/企业网络/模型授权。"
        if command:
            verify = shlex.join([command, "models", "--json"])
    elif partner_id == "qoder-cli":
        if command:
            setup_hint = "Qoder CLI 会走 -p headless 模式；若不可用，请先在原生 CLI 内完成登录。"
    elif partner_id == "kimi-cli":
        if command:
            setup_hint = "已保留 Kimi 入口；等官方稳定 prompt→stdout headless 参数后再启用自动派工。"
    elif partner_id == "claude-code":
        if command:
            setup_hint = "使用 Claude Code 自己的登录态和模型配置；Octopus 只负责派工。"
    elif partner_id == "codex-cli":
        if command:
            setup_hint = "使用 Codex CLI 自己的登录态和模型配置；Octopus 只负责派工。"

    if command and headless_supported and not verify:
        argv = build_partner_argv(partner_id, command, "请只回复 OK，不要修改文件。")
        if argv:
            verify = shlex.join(argv)
    if ready and not setup_hint:
        setup_hint = "已可被 Octopus 自动派工；也可以打开原生 CLI 使用它自己的快捷指令。"

    if partner_id in {"claude-code", "codex-cli", "codebuddy-cli"}:
        interaction_hint = (
            "Octopus 这里是一次性派工入口，不是原生交互终端；"
            "`/model <模型名>` 可转成本次模型覆盖，`/login`、`/doctor`、`/clear` "
            "等会话/账号指令请回原生 CLI 使用。"
        )
    elif partner_id == "trae-cli":
        interaction_hint = (
            "Trae 的模型、登录和企业网络状态由 Trae CLI 自己管理；"
            "Octopus 只做派工，不转发 Trae 原生 `/` 指令。"
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
    if partner_id in {"claude-code", "codex-cli", "codebuddy-cli"}:
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


def readiness_for_partner(
    partner_id: str,
    command: str | None,
    executable: str | None,
) -> dict[str, Any]:
    """Explain whether a detected local partner is actually dispatchable.

    ``detected`` only means "some executable-like entry exists". A polished UI
    needs the next layer: is it the official headless CLI, an interactive-only
    TUI, a desktop launcher, or a CLI with no model configured?
    """
    if not executable or not command:
        return {
            "ready": False,
            "headless_supported": False,
            "readiness_status": "missing",
            "readiness_message": "未发现本机 CLI。",
            "fix_hint": "安装对应官方 CLI，并确认命令在 PATH 中。",
        }

    probe_command = executable or command
    headless_supported = build_partner_argv(partner_id, probe_command, "health check") is not None
    if not headless_supported:
        if partner_id == "codebuddy-cli":
            return {
                "ready": False,
                "headless_supported": False,
                "readiness_status": "launcher_only",
                "readiness_message": "只发现 CodeBuddy 桌面/IDE 启动器，未发现官方 headless CLI。",
                "fix_hint": "安装 @tencent-ai/codebuddy-code，使 codebuddy/cbc 命令进入 PATH。",
            }
        if partner_id == "kimi-cli":
            return {
                "ready": False,
                "headless_supported": False,
                "readiness_status": "headless_unsupported",
                "readiness_message": "已发现 Kimi CLI，但暂未接入稳定的 prompt→stdout headless 形式。",
                "fix_hint": "等待官方 headless 参数稳定后再启用自动派工。",
            }
        return {
            "ready": False,
            "headless_supported": False,
            "readiness_status": "headless_unsupported",
            "readiness_message": "已发现本机入口，但 Octopus 暂不能用它稳定地非交互执行任务。",
            "fix_hint": "使用该 CLI 的原生终端，或安装支持 -p/print 的官方 CLI。",
        }

    if partner_id == "trae-cli":
        model, source = _trae_model_label(probe_command)
        if model == "未配置模型":
            return {
                "ready": False,
                "headless_supported": True,
                "readiness_status": "model_unconfigured",
                "readiness_message": "Trae CLI 已安装，但当前没有有效模型配置。",
                "fix_hint": f"在 Trae CLI 中用 /model 选择模型，或检查 {source}。",
            }

    return {
        "ready": True,
        "headless_supported": True,
        "readiness_status": "ready",
        "readiness_message": "可作为本地 CLI 伙伴自动派工。",
        "fix_hint": None,
    }


def partner_model(partner_id: str) -> dict[str, Any]:
    """Read a local CLI partner's own configured default model — its namespace
    (e.g. codex ``gpt-5.5``), NOT octopus's — so the UI can display it instead of
    the octopus model selector. Returns ``{partner_id, model, source}`` with
    ``model=""`` when not found. Best-effort and total — never raises."""
    import os
    from pathlib import Path

    home = Path(os.path.expanduser("~"))
    model = ""
    source = ""
    models: list[str] = []
    try:
        if partner_id == "codex-cli":
            cfg = home / ".codex" / "config.toml"
            if cfg.is_file():
                import tomllib

                data = tomllib.loads(cfg.read_text(encoding="utf-8"))
                model = str(data.get("model") or "")
                source = "~/.codex/config.toml" if model else ""
        elif partner_id == "claude-code":
            # Claude Code: ANTHROPIC_MODEL env first, then ~/.claude/settings.json.
            model = os.environ.get("ANTHROPIC_MODEL", "").strip()
            source = "$ANTHROPIC_MODEL" if model else ""
            if not model:
                cfg = home / ".claude" / "settings.json"
                if cfg.is_file():
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                    model = str(data.get("model") or "")
                    source = "~/.claude/settings.json" if model else ""
        elif partner_id == "trae-cli":
            model, source = _trae_model_label()
        elif partner_id == "qoder-cli":
            model = "Qoder CLI 默认"
            source = "qodercli"
        elif partner_id == "kimi-cli":
            model = "Kimi CLI 默认"
            source = "kimi"
        elif partner_id == "codebuddy-cli":
            model = "CodeBuddy 默认"
            models, source = _codebuddy_model_options()
            source = source or "codebuddy"
    except (
        OSError,
        ValueError,
        KeyError,
    ):  # best-effort · falls through with model/source left at their defaults
        pass
    payload: dict[str, Any] = {"partner_id": partner_id, "model": model, "source": source}
    if models:
        payload["models"] = models
    return payload


# ── Detection ──────────────────────────────────────────────────────


def which_command(commands: list[str]) -> tuple[str | None, str | None]:
    """Probe a list of candidate commands; return (name, path) for the
    first match, or (None, None) if none found."""
    for command in commands:
        expanded = os.path.expanduser(command)
        if expanded != command or "/" in command or "\\" in command:
            try:
                candidate = Path(expanded)
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate), str(candidate.resolve())
            except OSError:
                pass
        path = shutil.which(command)
        if path:
            return command, path
    return None, None


def dir_registered(agent_id: str) -> bool:
    """True iff ``agents/<agent_id>/profile.jsonc`` exists on disk."""
    try:
        from runtime.execution.agents.loader import default_agents_root

        return (default_agents_root() / agent_id / "profile.jsonc").is_file()
    except (OSError, ImportError):
        return False


def to_wire(
    spec: dict[str, Any],
    registry: Any,
    *,
    which_fn: Callable[[list[str]], tuple[str | None, str | None]] | None = None,
) -> LocalPartnerWire:
    """Materialize a partner spec into its current-state wire form.

    ``which_fn`` is injectable so callers (e.g. agents_router) can swap
    in a re-exported alias that tests monkeypatch. When ``None`` we use
    the module-local ``which_command``.
    """
    probe = which_fn or which_command
    command, executable = probe(list(spec["commands"]))
    readiness = readiness_for_partner(str(spec["id"]), command, executable)
    guidance = _partner_guidance(
        str(spec["id"]),
        command,
        ready=bool(readiness.get("ready")),
        headless_supported=bool(readiness.get("headless_supported")),
    )
    agent_id = str(spec["agent_id"])
    in_registry = bool(getattr(registry, "has", lambda _agent_id: False)(agent_id))
    registered = in_registry or dir_registered(agent_id)
    status = "registered" if registered else ("detected" if executable else "missing")
    return LocalPartnerWire(
        id=str(spec["id"]),
        agent_id=agent_id,
        name=str(spec["name"]),
        default_alias=str(spec["default_alias"]),
        description=str(spec["description"]),
        avatar_url=str(spec.get("avatar_url") or "") or None,
        detected=bool(executable),
        registered=registered,
        status=status,
        command=command,
        executable=executable,
        ready=bool(readiness.get("ready")),
        headless_supported=bool(readiness.get("headless_supported")),
        readiness_status=str(readiness.get("readiness_status") or status),
        readiness_message=str(readiness.get("readiness_message") or ""),
        fix_hint=str(readiness.get("fix_hint") or "") or None,
        install_command=guidance.get("install_command"),
        native_command=guidance.get("native_command"),
        native_launch_command=guidance.get("native_launch_command"),
        native_launch_cwd=guidance.get("native_launch_cwd"),
        verify_command=guidance.get("verify_command"),
        setup_hint=guidance.get("setup_hint"),
        interaction_hint=guidance.get("interaction_hint"),
        command_hints=_partner_command_hints(str(spec["id"])),
    )


_PROBE_PROMPT = "请只回复 OK，不要修改文件。"


def probe_partner(
    partner_id: str,
    *,
    command: str | None,
    executable: str | None,
    timeout: float = 30.0,
    runner: Any = None,
) -> dict[str, Any]:
    """Run a small real health probe against a detected local partner.

    ``readiness_for_partner`` answers "should this be drivable?" from static
    signals. The probe answers "does it actually run right now with this user's
    login/model/network?". It deliberately uses the same bridge and diagnostic
    path as real dispatch so failures are not a separate, misleading universe.
    """
    started = time.monotonic()
    spec = LOCAL_PARTNER_SPECS.get(partner_id) or {}
    agent_id = str(spec.get("agent_id") or "")

    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("id", partner_id)
        payload.setdefault("agent_id", agent_id)
        payload.setdefault("command", command)
        payload.setdefault("executable", executable)
        payload.setdefault("elapsed_ms", int((time.monotonic() - started) * 1000))
        return payload

    if partner_id not in LOCAL_PARTNER_SPECS:
        return finish(
            {
                "ok": False,
                "detected": False,
                "ready": False,
                "status": "unknown_partner",
                "error": f"unknown local partner: {partner_id}",
                "raw_error": "",
                "failure_kind": "unknown_partner",
                "failure_title": "未知本地 CLI 伙伴",
                "fix_hint": "请刷新本地伙伴列表后重试。",
            }
        )

    if not command or not executable:
        return finish(
            {
                "ok": False,
                "detected": False,
                "ready": False,
                "status": "missing",
                "error": "未发现本机 CLI。",
                "raw_error": "",
                "failure_kind": "missing_binary",
                "failure_title": "没有找到本地 CLI 命令",
                "fix_hint": "安装对应官方 CLI，并确认命令在 PATH 中。",
            }
        )

    readiness = readiness_for_partner(partner_id, command, executable)
    if not readiness.get("ready"):
        return finish(
            {
                "ok": False,
                "detected": True,
                "ready": False,
                "status": str(readiness.get("readiness_status") or "not_ready"),
                "error": str(readiness.get("readiness_message") or "本地伙伴暂不可派工。"),
                "raw_error": "",
                "failure_kind": str(readiness.get("readiness_status") or "not_ready"),
                "failure_title": str(readiness.get("readiness_message") or "本地伙伴暂不可派工。"),
                "fix_hint": str(readiness.get("fix_hint") or "") or None,
            }
        )

    result = run_local_partner(
        partner_id=partner_id,
        command=executable or command,
        prompt=_PROBE_PROMPT,
        timeout=timeout,
        runner=runner,
    )
    if result.ok:
        return finish(
            {
                "ok": True,
                "detected": True,
                "ready": True,
                "status": "ok",
                "output": result.output[:1000],
                "error": "",
                "raw_error": "",
                "failure_kind": None,
                "failure_title": "",
                "fix_hint": None,
            }
        )
    return finish(
        {
            "ok": False,
            "detected": True,
            "ready": True,
            "status": result.failure_kind or ("timeout" if result.timed_out else "failed"),
            "output": result.output[:1000],
            "error": result.error,
            "raw_error": result.raw_error,
            "failure_kind": result.failure_kind,
            "failure_title": result.failure_title,
            "fix_hint": result.fix_hint or None,
        }
    )


# ── SOUL.md template + agent writer ────────────────────────────────


def soul_template(*, alias: str, partner_name: str, command: str) -> str:
    """Render the SOUL.md persona block for a registered partner."""
    return f"""# Soul

## Persona

你是 {alias}，一个接入到 Octopus 人力池的本地伙伴。你的背后对应本机已经安装的 {partner_name} 工作流。

## Working Style

- 优先用中文和用户协作，保持简洁、可执行。
- 当任务明确需要调用本地伙伴能力时，通过 shell 运行 `{command}`，并把关键结果整理回对话。
- 调用外部命令前先判断是否必要；涉及文件写入、网络、账号态或长任务时说明将要做什么。
- 如果本地工具返回错误,先给出降级方案,而不是把用户卡在工具细节里。
"""


def write_partner_agent(
    *,
    spec: dict[str, Any],
    alias: str,
    command: str,
    executable: str,
    runtime: Any,
    registry: Any,
) -> Any:
    """Write a LocalPartner agent's profile + SOUL/IDENTITY/AGENTS docs
    to disk and register it in the agent registry. Returns the loaded
    Agent instance.

    Idempotent: if the agent dir already exists with a profile.jsonc,
    we just reload + re-register without overwriting any existing
    customizations the user made.
    """
    import uuid

    from runtime.execution.agents.loader import default_agents_root, load_agent
    from runtime.platform.io import atomic_write_text

    agent_id = _require_safe_agent_id(str(spec["agent_id"]))
    root = default_agents_root().resolve()
    agent_dir = root / agent_id
    if agent_dir.is_symlink():
        raise ValueError(f"agent folder is not a real directory: {agent_id}")
    if agent_dir.exists() and not agent_dir.is_dir():
        raise ValueError(f"agent path is not a directory: {agent_id}")
    if agent_dir.exists():
        profile_path = agent_dir / "profile.jsonc"
        if profile_path.is_symlink() or not profile_path.is_file():
            raise ValueError(f"agent folder exists without profile: {agent_id}")
        agent = load_agent(agent_dir, runtime, root / "_shared")
        if hasattr(registry, "replace"):
            registry.replace(agent)
        elif not registry.has(agent_id):
            registry.register(agent)
        return agent

    created_agent_dir = False
    try:
        agent_dir.mkdir(parents=True)
        created_agent_dir = True
        for rel in (
            "agent-core",
            "agent-core/.soul_history",
            "agent-core/diary",
            "agent-core/skills",
            "memory",
            "permissions",
            "project",
            "runtime",
            "sessions",
            "skills",
        ):
            (agent_dir / rel).mkdir(parents=True, exist_ok=True)
    except OSError:
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise

    did = f"DID-{uuid.uuid4().hex[:12].upper()}-{uuid.uuid4().hex[:6].upper()}"
    profile = {
        "id": agent_id,
        "templateId": str(spec["id"]),
        "templateVersion": "1.0.0",
        "name": alias,
        "icon": str(spec.get("icon") or "L"),
        "did": did,
        "description": str(spec["description"]),
        "avatar": "avatar.svg",
        "model": {"provider": "auto", "name": "auto"},
        "runtime": "local_partner",
        "creator": "user",
        "category": "automation",
        "tags": list(spec.get("tags") or []),
        "defaultProject": {"dir": "project"},
        "capabilities": {
            "local_partner": True,
            "local_partner_id": str(spec["id"]),
            "local_partner_command": command,
            "local_partner_executable": executable,
        },
    }
    try:
        atomic_write_text(
            agent_dir / "profile.jsonc",
            (
                f"// Octopus local partner profile · {agent_id}\n"
                "// Created by local partner registration\n\n"
                + json.dumps(profile, ensure_ascii=False, indent=2)
            ),
        )
        soul = soul_template(
            alias=alias,
            partner_name=str(spec["name"]),
            command=command,
        )
        atomic_write_text(agent_dir / "agent-core" / "SOUL.md", soul, newline=None)
        atomic_write_text(
            agent_dir / "agent-core" / "IDENTITY.md",
            f"""# Identity

- **Name**: {alias}
- **Role**: Local partner bridge for {spec["name"]}

## Boundary

- You are registered from a local executable detected on this machine.
- Respect the current workspace and the user's requested task.
""",
            newline=None,
        )
        atomic_write_text(
            agent_dir / "agent-core" / "AGENTS.md",
            """# Working rules

Before using the local partner command, understand the user's task and current workspace. Keep outputs concise and user-facing.
""",
            newline=None,
        )
        atomic_write_text(
            agent_dir / "agent-core" / "tool-registry.jsonc",
            (
                "// Tool registry for this local partner\n\n"
                + json.dumps(
                    {
                        "arms": list(spec.get("tool_groups") or []),
                        "extra_affinity": ["local_partner", str(spec["id"])],
                        "private_skills": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        )
        atomic_write_text(agent_dir / "avatar.svg", pixel_agent_avatar_svg(alias), newline=None)
    except OSError:
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise

    try:
        agent = load_agent(agent_dir, runtime, root / "_shared")
    except (OSError, ValueError, TypeError):
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise
    try:
        registry.register(agent)
    except (ValueError, TypeError):
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise
    return agent
