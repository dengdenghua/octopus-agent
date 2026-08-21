"""Execution bridge for LocalPartner agents — drive an official coding-agent
CLI (Claude Code, Codex, Trae, Qoder, OpenCode) directly, with the user's own
login/subscription.

LocalPartner registration (``agents_local_partner.write_partner_agent``) detects
an installed CLI and writes an agent whose ``profile.jsonc`` carries::

    "runtime": "local_partner",
    "capabilities": {
        "local_partner": true,
        "local_partner_id": "claude-code",            # which CLI
        "local_partner_command": "claude",            # the bare command
        "local_partner_executable": "/abs/path/claude" # resolved (safe) path
    }

Until now nothing *executed* on those flags: a LocalPartner agent ran as a
normal LLM agent whose SOUL.md merely *told the model* to shell out to the CLI —
indirect, unreliable, and a wasted LLM round-trip wrapping another agent. This
module is the direct dispatch: turn the user's prompt into the CLI's own
non-interactive invocation, run it, and hand the output back.

Design:
  * ``build_partner_argv`` holds the per-CLI knowledge (the only place that
    knows ``claude -p`` vs ``codex exec``). Unknown / not-yet-supported
    partners return ``None`` so the caller can fall back to the normal loop.
  * The prompt is always passed as a **separate argv element** and the process
    is spawned with ``shell=False`` — the user's text never reaches a shell, so
    there is no shell-injection surface.
  * ``run_local_partner`` takes an injectable ``runner`` so the whole path is
    unit-testable without a real CLI installed.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# A runner executes ``argv`` in ``cwd`` with a wall-clock ``timeout`` and
# returns ``(exit_code, stdout, stderr)``. Injectable so tests don't spawn.
Runner = Callable[[list[str], "str | None", float], "tuple[int, str, str]"]

# Wall-clock ceiling for a single CLI run. Coding agents can take a while, but
# a turn shouldn't hang forever; override with OCTOPUS_LOCAL_PARTNER_TIMEOUT.
_DEFAULT_TIMEOUT_S = 240.0

# Trim runaway CLI output so one run can't flood a chat turn / the journal.
_MAX_OUTPUT_CHARS = 20_000

_SLASH_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$")
_MODEL_FLAG_PARTNERS = frozenset({"claude-code", "codex-cli", "codebuddy-cli", "opencode-cli"})
_CONTROL_ONLY_SLASH_COMMANDS = frozenset(
    {
        "clear",
        "compact",
        "config",
        "doctor",
        "help",
        "init",
        "login",
        "logout",
        "models",
        "permissions",
        "resume",
        "status",
        "tools",
    }
)

_PARTNER_LABELS = {
    "claude-code": "Claude Code",
    "codex-cli": "Codex CLI",
    "trae-cli": "Trae CLI",
    "qoder-cli": "Qoder CLI",
    "kimi-cli": "Kimi CLI",
    "codebuddy-cli": "CodeBuddy CLI",
    "opencode-cli": "OpenCode CLI",
}


@dataclass(frozen=True)
class LocalPartnerResult:
    """Outcome of one CLI run. ``ok`` means it ran AND exited 0 with output."""

    ok: bool
    output: str = ""
    error: str = ""
    raw_error: str = ""
    exit_code: int | None = None
    argv: list[str] = field(default_factory=list)
    timed_out: bool = False
    # True only when the partner type has no known non-interactive invocation
    # yet — the caller should fall back to the normal loop rather than show an
    # error (the agent isn't broken, we just can't drive it directly).
    unsupported: bool = False
    failure_kind: str | None = None
    failure_title: str = ""
    fix_hint: str = ""


@dataclass(frozen=True)
class PartnerRequestPlan:
    """A user prompt normalized for one headless CLI invocation."""

    prompt: str
    model: str | None = None
    notices: tuple[str, ...] = ()
    handled_output: str | None = None


@dataclass(frozen=True)
class PartnerFailureDiagnosis:
    kind: str
    title: str
    hint: str


def _display_partner(partner_id: str) -> str:
    return _PARTNER_LABELS.get(partner_id, partner_id)


def _native_command(command: str | None) -> str:
    value = (command or "").strip()
    if not value:
        return "对应 CLI"
    return shlex.quote(value) if re.search(r"\s", value) else value


def _haystack(*parts: object) -> str:
    return "\n".join(str(part or "") for part in parts).lower()


def diagnose_partner_failure(
    partner_id: str,
    command: str,
    *,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    missing_binary: bool = False,
) -> PartnerFailureDiagnosis:
    """Map common black-box CLI failures to user-actionable categories."""
    partner = _display_partner(partner_id)
    native = _native_command(command)
    text = _haystack(stdout, stderr)
    if timed_out:
        return PartnerFailureDiagnosis(
            "timeout",
            f"{partner} 执行超时",
            "可以把任务拆小一点，或调大 OCTOPUS_LOCAL_PARTNER_TIMEOUT 后重试。",
        )
    if missing_binary:
        return PartnerFailureDiagnosis(
            "missing_binary",
            f"没有找到 {partner} 命令",
            f"请确认 {native} 已安装并在 PATH 中，然后重新检测本地伙伴。",
        )
    if any(
        marker in text
        for marker in (
            "not entitled",
            "entitlement",
            "subscription",
            "license",
            "plan does not include",
            "not available for your account",
            "not available for this account",
            "not enabled for your account",
            "account is not enabled",
            "no permission to use model",
            "no access to model",
            "model access denied",
            "未开通",
            "无权益",
            "没有权益",
            "暂无权益",
            "账号无权限",
            "没有模型权限",
        )
    ):
        return PartnerFailureDiagnosis(
            "entitlement",
            f"{partner} 账号权益不足或未开通",
            "桌面端可用不代表 CLI 账号已获得同一权益；请在原生 CLI 中确认订阅/企业授权/模型权限后重试。",
        )
    if any(
        marker in text
        for marker in (
            "not logged in",
            "not login",
            "please login",
            "please log in",
            "sign in",
            "signin",
            "unauthenticated",
            "unauthorized",
            "authentication",
            "api key",
            "token expired",
            "invalid token",
        )
    ):
        return PartnerFailureDiagnosis(
            "auth",
            f"{partner} 需要登录或授权",
            f"请打开原生 CLI：`{native}`，完成登录/授权后再让 Octopus 派工。",
        )
    if any(
        marker in text
        for marker in (
            "no effective model configured",
            "no model configured",
            "model not configured",
            "model_unconfigured",
            "no available model",
            "models is empty",
            "empty models",
            "invalid model",
            "unknown model",
            "unsupported model",
            # Upstream phrasing puts the model first ("The 'x' model is not
            # supported when using Codex with a ChatGPT account"), so the
            # "<adj> model" markers above never fire on it.
            "model is not supported",
            "not supported when using",
            "model_not_supported",
        )
    ):
        if partner_id == "trae-cli":
            hint = "请先在 Trae CLI 原生终端选择/配置模型，或运行 `trae-cli models --json` 检查账号和企业模型授权。"
        else:
            hint = "请在伙伴模型选择器里换一个该 CLI 支持的模型，或在原生 CLI 里配置默认模型。"
        return PartnerFailureDiagnosis("model", f"{partner} 模型不可用", hint)
    if any(
        marker in text
        for marker in (
            "permission denied",
            "eacces",
            "operation not permitted",
            "not trusted",
            "untrusted",
            "requires approval",
            "approval required",
            # A bare "sandbox" matched Codex's own startup banner line
            # ("sandbox: read-only"), stamping every Codex failure as a
            # permission problem. Match denials, not the mode announcement.
            "sandbox denied",
            "sandbox violation",
            "blocked by sandbox",
            "sandbox policy",
        )
    ):
        return PartnerFailureDiagnosis(
            "permission",
            f"{partner} 权限或工作区信任不足",
            "请在原生 CLI 中信任当前项目/调整权限模式，或在 Octopus 里降低本次任务的写入风险后重试。",
        )
    if any(
        marker in text
        for marker in (
            "could not resolve host",
            "enotfound",
            "econnrefused",
            "etimedout",
            "network",
            "proxy",
            "tls",
            "certificate",
            "unable to reach",
            "kdc",
            "dns",
        )
    ):
        return PartnerFailureDiagnosis(
            "network",
            f"{partner} 网络或企业环境不可达",
            "请检查网络、代理、企业 DNS/Kerberos/VPN 后，在原生 CLI 里先跑通再回到 Octopus。",
        )
    if any(marker in text for marker in ("quota", "rate limit", "too many requests", "billing")):
        return PartnerFailureDiagnosis(
            "quota",
            f"{partner} 额度或限流不足",
            "请检查该 CLI 账号的额度/计费/限流状态，稍后重试或换一个可用模型。",
        )
    if any(
        marker in text
        for marker in (
            "unknown option",
            "unrecognized option",
            "invalid option",
            "no such option",
            "unknown flag",
            "unrecognized flag",
            "flag provided but not defined",
            "unexpected argument",
            "unexpected option",
            "requires a newer version",
            "unsupported cli version",
            "please upgrade",
            "upgrade required",
        )
    ):
        return PartnerFailureDiagnosis(
            "version",
            f"{partner} CLI 版本或 headless 参数不兼容",
            f"请先升级原生 CLI，或在终端运行 `{native} --help` 确认当前版本是否支持 Octopus 使用的 headless/print 参数。",
        )
    if exit_code == 0 and not (stdout or "").strip():
        return PartnerFailureDiagnosis(
            "empty_output",
            f"{partner} 没有返回可显示内容",
            "请在原生 CLI 里验证 print/headless 模式是否可用；如果它只进入交互界面，暂不能自动派工。",
        )
    return PartnerFailureDiagnosis(
        "unknown",
        f"{partner} 返回了未分类错误",
        f"请先在原生 CLI：`{native}` 中复现；如果原生可用，再把原始错误贴回来继续适配。",
    )


def _format_failure_error(diagnosis: PartnerFailureDiagnosis, raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return f"{diagnosis.title}\n建议：{diagnosis.hint}"
    return f"{diagnosis.title}\n建议：{diagnosis.hint}\n\n原始错误：\n{raw}"


def _partner_slash_help(partner_id: str, *, command: str | None = None) -> str:
    partner = _display_partner(partner_id)
    native = _native_command(command)
    model_line = (
        "- `/model <模型名>` 换行接任务：本次调用转成该 CLI 的模型参数。"
        if partner_id in _MODEL_FLAG_PARTNERS
        else "- `/model <模型名>` 换行接任务：Octopus 会识别这个意图，但本伙伴暂不支持稳定模型参数，本次仍用 CLI 默认模型。"
    )
    extra = ""
    if partner_id == "trae-cli":
        extra = "\n- Trae 模型为空时，请在原生终端运行 `trae-cli models --json` 检查账号/企业网络/模型授权。"
    elif partner_id == "codebuddy-cli":
        extra = "\n- CodeBuddy 可选模型会从 `codebuddy --help` 读取，并显示在伙伴模型菜单里。"
    return (
        f"{partner} 的 Octopus 兼容快捷指令：\n"
        f"这里是 Octopus 的本地伙伴调度入口，不是原生交互终端；原生终端指 {partner} 自己的终端会话。\n"
        f"{model_line}\n"
        "- `/models`：说明模型从哪里看/怎么切。\n"
        "- `/help`：显示这份兼容说明。\n"
        "- `/clear`、`/compact`、`/resume`：不会转发给外部 CLI；请开启新任务或在原生 CLI 里使用。\n"
        "- `/login`、`/doctor`、`/status`、`/config`：不会在 headless 派工里执行；请打开原生 CLI 处理。\n"
        f"\n原生快捷指令仍按 {partner} 自己的规则走。需要完整原生体验时，在终端运行：`{native}`。"
        f"{extra}"
    )


def _control_slash_guidance(
    partner_id: str,
    command: str,
    *,
    native_command: str | None = None,
) -> str:
    partner = _display_partner(partner_id)
    native = _native_command(native_command)
    if command == "help":
        return _partner_slash_help(partner_id, command=native_command)
    if command == "models":
        if partner_id in _MODEL_FLAG_PARTNERS:
            return (
                f"{partner} 的模型不使用 Octopus 全局模型列表。请用伙伴模型选择器，"
                "或输入 `/model <模型名>` 后换行接任务来做一次性覆盖。"
            )
        if partner_id == "trae-cli":
            return (
                "Trae CLI 的模型由 Trae 自己管理；Octopus 暂不传模型参数。"
                "可在终端运行 `trae-cli models --json` 检查当前 CLI 是否已配置模型。"
            )
        return f"{partner} 当前由 CLI 自己决定模型；Octopus 暂不传模型覆盖参数。"
    if command in {"login", "logout", "doctor", "status", "config", "permissions", "tools"}:
        return (
            f"识别到 `/{command}`。这类账号/诊断/配置指令需要 {partner} 的原生交互环境，"
            f"不会在 Octopus 的 headless 派工里执行。请在终端运行 `{native}` 后使用该 CLI 自己的 `/{command}`。"
        )
    return (
        f"识别到 `/{command}`。这里是 Octopus 的本地伙伴调度入口，不是"
        f" {partner} 的原生交互终端；此类会话级快捷指令不会转发给外部 CLI。"
        "模型请用伙伴模型选择器，清上下文可开启新任务，原生快捷键请在对应 CLI 终端中使用。"
    )


def _expand_args_template(
    template: list[Any],
    *,
    command: str,
    prompt: str,
    model: str | None,
) -> list[str] | None:
    """Expand an ``args_template`` from profile.jsonc into a real argv list.

    Template syntax:
      * ``"{command}"`` → the CLI command
      * ``"{prompt}"`` → the wrapped prompt
      * ``"{model}"`` → the model name (or empty string if None)
      * ``{"if": "model", "then": [...]}`` → conditional block, expanded only if
        model is set
      * ``{"if": "model", "then": [...], "else": [...]}`` → conditional with
        fallback
      * Plain strings → literal argv elements

    Returns ``None`` if the template is malformed or produces an empty argv.
    """
    result: list[str] = []
    context = {"command": command, "prompt": prompt, "model": model or ""}

    def expand(item: Any) -> list[str]:
        if isinstance(item, str):
            # Simple string: substitute placeholders
            expanded = item
            for key, value in context.items():
                expanded = expanded.replace(f"{{{key}}}", value)
            return [expanded] if expanded else []

        if isinstance(item, dict):
            # Conditional block
            condition = item.get("if")
            if condition == "model":
                if model:
                    then_branch = item.get("then", [])
                    if isinstance(then_branch, list):
                        out: list[str] = []
                        for sub in then_branch:
                            out.extend(expand(sub))
                        return out
                else:
                    else_branch = item.get("else", [])
                    if isinstance(else_branch, list):
                        out = []
                        for sub in else_branch:
                            out.extend(expand(sub))
                        return out
            return []

        # Unknown type: skip
        return []

    for item in template:
        result.extend(expand(item))

    return result if result else None


def partner_identity(capabilities: Any) -> tuple[str, str] | None:
    """Read ``(partner_id, command)`` from an agent's capabilities, or ``None``
    when this isn't a drivable local partner. Prefers the resolved executable
    path (captured under PATH-poisoning defense at registration) over the bare
    command name."""
    if not isinstance(capabilities, dict):
        return None
    if not capabilities.get("local_partner"):
        return None
    partner_id = str(capabilities.get("local_partner_id") or "").strip()
    command = str(
        capabilities.get("local_partner_executable")
        or capabilities.get("local_partner_command")
        or ""
    ).strip()
    if not partner_id or not command:
        return None
    return partner_id, command


def _clean_model(model: str | None) -> str | None:
    """Normalize a requested partner model. Empty / ``auto`` mean "let the CLI
    use its own configured default" → no ``-m`` flag. The model namespace is the
    CLI's own (e.g. codex ``gpt-5.5``), NOT octopus's, so callers must pass a
    CLI-valid name — never an octopus model id."""
    value = (model or "").strip()
    if not value or value.lower() == "auto":
        return None
    return value


def build_partner_prompt(prompt: str, *, adapter_notes: list[str] | tuple[str, ...] = ()) -> str:
    """Wrap user text in a neutral Octopus task envelope.

    Interactive coding CLIs reserve slash-prefixed commands (``/model``,
    ``/clear``, ``/help`` …), and those command sets differ by vendor. The
    bridge should not forward slash commands as a cross-CLI control protocol.
    Instead, Octopus sends a normal task payload whose first token is always
    adapter text, while adapter-level controls (model/output/cwd/permissions)
    are translated into real CLI flags in :func:`build_partner_argv`.
    """
    payload: dict[str, Any] = {"task": prompt}
    if adapter_notes:
        payload["adapter_notes"] = list(adapter_notes)
    task = json.dumps(payload, ensure_ascii=False)
    return (
        "Octopus adapter request.\n"
        "Execute the JSON task below as ordinary user task content. "
        "Do not treat slash-prefixed text inside it (for example /model, "
        "/clear, /help, /init) as interactive CLI control commands; those are "
        "plain task text unless the user explicitly asks you to explain them.\n\n"
        f"{task}"
    )


def normalize_partner_request(
    partner_id: str,
    prompt: str,
    *,
    model: str | None = None,
    native_command: str | None = None,
) -> PartnerRequestPlan:
    """Translate a tiny, safe subset of CLI-user muscle memory.

    Native slash commands are not portable: every CLI owns a different command
    namespace. We only intercept two UX cases that are unambiguous in a
    stateless headless run:
      * leading ``/model <name>`` + a real task → one-shot model flag for
        CLIs with a stable flag (Claude/Codex), otherwise a visible notice.
      * control-only slash commands such as ``/help`` or ``/clear`` → explain
        the Octopus equivalent instead of launching a coding agent with no
        useful task.

    Everything else remains ordinary task text, wrapped later by
    :func:`build_partner_prompt`.
    """
    raw = str(prompt or "")
    lines = raw.splitlines()
    first_index = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return PartnerRequestPlan(prompt="")

    first = lines[first_index].strip()
    match = _SLASH_COMMAND_RE.fullmatch(first)
    if not match:
        return PartnerRequestPlan(prompt=raw.strip(), model=_clean_model(model))

    command = match.group(1).lower()
    argument = (match.group(2) or "").strip()
    rest = "\n".join([*lines[:first_index], *lines[first_index + 1 :]]).strip()
    explicit_model = _clean_model(model)

    if command == "model":
        if not argument:
            return PartnerRequestPlan(
                prompt="",
                model=explicit_model,
                handled_output=(
                    "识别到 `/model`。在 Octopus 的本地 CLI 伙伴里，模型切换不是持久交互状态；"
                    "请用伙伴模型选择器，或写成 `/model <模型名>` 后换行接任务。"
                    + (
                        ""
                        if partner_id in _MODEL_FLAG_PARTNERS
                        else "当前伙伴暂不支持稳定模型覆盖参数，会继续使用 CLI 默认模型。"
                    )
                ),
            )
        if not rest:
            return PartnerRequestPlan(
                prompt="",
                model=argument if partner_id in _MODEL_FLAG_PARTNERS else explicit_model,
                handled_output=(
                    f"识别到 `/model {argument}`，但这次没有后续任务。Octopus 的本地 CLI "
                    "伙伴是一次性执行；请在下一行补上要做的事，或在模型选择器里设置默认值。"
                ),
            )
        if partner_id in _MODEL_FLAG_PARTNERS:
            selected = explicit_model or argument
            return PartnerRequestPlan(
                prompt=rest,
                model=selected,
                notices=(f"已将开头的模型快捷意图转为本次 {partner_id} 的模型参数：{argument}",),
            )
        return PartnerRequestPlan(
            prompt=rest,
            model=explicit_model,
            notices=(
                f"已识别但未转发模型快捷意图：{partner_id} 的 headless 模式"
                "暂无稳定模型覆盖参数，本次使用该 CLI 自身默认模型。",
            ),
        )

    if command in _CONTROL_ONLY_SLASH_COMMANDS and not rest:
        return PartnerRequestPlan(
            prompt="",
            model=explicit_model,
            handled_output=_control_slash_guidance(
                partner_id,
                command,
                native_command=native_command,
            ),
        )

    return PartnerRequestPlan(prompt=raw.strip(), model=explicit_model)


def build_partner_argv(
    partner_id: str,
    command: str,
    prompt: str,
    model: str | None = None,
    adapter_notes: list[str] | tuple[str, ...] = (),
    capabilities: dict[str, Any] | None = None,
) -> list[str] | None:
    """Map ``(partner_id, command, prompt[, model])`` to the CLI's own
    non-interactive invocation, or ``None`` for partners we can't drive headless
    yet.

    Prefers declarative ``args_template`` from the agent's ``profile.jsonc``
    capabilities (when provided), falling back to hardcoded rules for backward
    compatibility and for partners without a template yet.

    The hardcoded flags are best-effort for the known CLIs and intentionally
    isolated here so a single edit fixes a tool whose interface drifts:
      * ``claude-code`` → ``claude -p [--model <m>] "<prompt>"`` (headless)
      * ``codex-cli``   → ``codex exec [-m <m>] --skip-git-repo-check "<prompt>"``
        (non-interactive exec; the skip flag lets it run in any chosen workspace
        — without it codex refuses outside a git repo: "Not inside a trusted
        directory". Octopus already controls/gates the workspace dir.)
      * ``trae-cli``    → ``trae-cli -p --output-format text "<prompt>"``
        (print-and-exit mode; prompt remains one argv element).
      * ``qoder-cli``   → ``qodercli -p "<prompt>"`` (print-and-exit mode).
      * ``codebuddy-cli`` → ``codebuddy -p [--model <m>] --output-format text "<prompt>"``
        (official CodeBuddy CLI headless mode). The desktop/IDE ``buddy``
        launcher is intentionally not driven headless here because it opens UI
        chat sessions rather than returning an answer on stdout.
      * ``opencode-cli`` → ``opencode run [-m <provider/model>] "<prompt>"``
        (one-shot non-interactive run; output is returned on stdout).

    ``model`` (when set to a CLI-valid name) overrides the CLI's configured
    default. ``None`` / ``"auto"`` → the CLI keeps its own default.

    ``openclaw`` (desktop automation, not a prompt→answer coding agent) has no
    headless prompt form here → ``None`` (caller falls back to the LLM loop).
    """
    prompt = (prompt or "").strip()
    if not command or not prompt:
        return None
    prompt_arg = build_partner_prompt(prompt, adapter_notes=adapter_notes)
    m = _clean_model(model)

    # Try declarative template first (if capabilities provided)
    if capabilities:
        invocation = capabilities.get("local_partner_invocation")
        if isinstance(invocation, dict):
            args_template = invocation.get("args_template")
            if isinstance(args_template, list):
                try:
                    argv = _expand_args_template(
                        args_template,
                        command=command,
                        prompt=prompt_arg,
                        model=m,
                    )
                    if argv:
                        return argv
                except Exception:  # noqa: BLE001 — fall back to hardcoded on any template error
                    pass

    # Fallback to hardcoded rules
    if partner_id == "claude-code":
        return [command, "-p", *(["--model", m] if m else []), prompt_arg]
    if partner_id == "codex-cli":
        return [
            command,
            "exec",
            *(["-m", m] if m else []),
            "--skip-git-repo-check",
            prompt_arg,
        ]
    if partner_id == "trae-cli":
        return [command, "-p", "--output-format", "text", prompt_arg]
    if partner_id == "qoder-cli":
        return [command, "-p", prompt_arg]
    if partner_id == "codebuddy-cli":
        exe_name = os.path.basename(command).lower()
        normalized_command = command.replace("\\", "/")
        if exe_name in {"buddy", "buddy.exe", "buddy.cmd", "buddy.ps1"} or (
            exe_name == "code" and "/CodeBuddy.app/" in normalized_command
        ):
            return None
        return [
            command,
            "-p",
            *(["--model", m] if m else []),
            "--output-format",
            "text",
            prompt_arg,
        ]
    if partner_id == "opencode-cli":
        return [
            command,
            "run",
            *(["-m", m] if m else []),
            "--auto",  # auto-approve permissions (non-interactive mode)
            prompt_arg,
        ]
    return None


def _default_runner(
    argv: list[str],
    cwd: str | None,
    timeout: float,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Spawn ``argv`` with no shell, capturing stdout/stderr. ``env`` (when given)
    is layered OVER the inherited environment, so extra vars like
    ``OCTOPUS_BLACKBOARD_DB`` / ``OCTOPUS_TURN_ID`` reach the CLI (letting a
    shell-capable agent read/write the shared blackboard via ``octopus bb``)
    without dropping PATH etc. Raises ``subprocess.TimeoutExpired`` on timeout."""
    from runtime.platform.process.tree import run_capture

    layered_env = {**os.environ, **env} if env else None
    # Preserve the long-standing injectable ``subprocess.run`` seam used by
    # embedders and tests.  Real execution goes through run_capture below;
    # this branch is only active when that seam has explicitly been replaced.
    if getattr(subprocess.run, "__module__", "subprocess") != "subprocess":
        proc = subprocess.run(  # noqa: S603 — compatibility seam, shell=False
            argv,
            cwd=cwd,
            env=layered_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    else:
        proc = run_capture(  # noqa: S603 — argv is a list, shell=False, no user shell string
            argv,
            cwd=cwd,
            env=layered_env,
            timeout=timeout,
        )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_local_partner(
    *,
    partner_id: str,
    command: str,
    prompt: str,
    cwd: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
    env: dict[str, str] | None = None,
    runner: Runner | None = None,
    model: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> LocalPartnerResult:
    """Drive the partner CLI once. Best-effort and total — never raises; every
    failure mode (unsupported tool, missing binary, non-zero exit, timeout) is
    reflected in the returned :class:`LocalPartnerResult`. ``env`` is layered over
    the inherited environment for the default runner (custom runners ignore it).
    ``model`` (a CLI-valid name) overrides the CLI's configured default.
    ``capabilities`` (the agent's profile capabilities dict) enables declarative
    ``args_template`` expansion."""
    plan = normalize_partner_request(partner_id, prompt, model=model, native_command=command)
    if plan.handled_output is not None:
        return LocalPartnerResult(ok=True, output=plan.handled_output)

    argv = build_partner_argv(
        partner_id,
        command,
        plan.prompt,
        plan.model,
        adapter_notes=plan.notices,
        capabilities=capabilities,
    )
    if argv is None:
        return LocalPartnerResult(ok=False, unsupported=True)

    if runner is None:

        def run(a: list[str], c: str | None, t: float) -> tuple[int, str, str]:
            return _default_runner(a, c, t, env=env)
    else:
        run = runner
    try:
        exit_code, stdout, stderr = run(argv, cwd, timeout)
    except subprocess.TimeoutExpired:
        diagnosis = diagnose_partner_failure(
            partner_id,
            command,
            timed_out=True,
        )
        return LocalPartnerResult(
            ok=False,
            error=_format_failure_error(
                diagnosis,
                f"{command} did not finish within {int(timeout)}s",
            ),
            raw_error=f"{command} did not finish within {int(timeout)}s",
            argv=argv,
            timed_out=True,
            failure_kind=diagnosis.kind,
            failure_title=diagnosis.title,
            fix_hint=diagnosis.hint,
        )
    except FileNotFoundError:
        diagnosis = diagnose_partner_failure(
            partner_id,
            command,
            missing_binary=True,
        )
        return LocalPartnerResult(
            ok=False,
            error=_format_failure_error(diagnosis, f"{command} is not installed or not on PATH"),
            raw_error=f"{command} is not installed or not on PATH",
            argv=argv,
            failure_kind=diagnosis.kind,
            failure_title=diagnosis.title,
            fix_hint=diagnosis.hint,
        )
    except OSError as exc:
        diagnosis = diagnose_partner_failure(partner_id, command, stderr=str(exc))
        return LocalPartnerResult(
            ok=False,
            error=_format_failure_error(diagnosis, str(exc)),
            raw_error=str(exc),
            argv=argv,
            failure_kind=diagnosis.kind,
            failure_title=diagnosis.title,
            fix_hint=diagnosis.hint,
        )

    output = (stdout or "").strip()
    if output and plan.notices:
        output = "\n".join([*(f"[Octopus adapter] {notice}" for notice in plan.notices), output])
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[:_MAX_OUTPUT_CHARS].rstrip() + "\n…(truncated)"
    if exit_code == 0 and output:
        return LocalPartnerResult(ok=True, output=output, exit_code=exit_code, argv=argv)

    # Ran but failed: surface the most useful tail we have (stderr, else a hint).
    err_tail = (stderr or "").strip() or (output or "exited without output")
    if len(err_tail) > 2_000:
        err_tail = err_tail[-2_000:]
    diagnosis = diagnose_partner_failure(
        partner_id,
        command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr or output,
    )
    return LocalPartnerResult(
        ok=False,
        output=output,
        error=_format_failure_error(diagnosis, err_tail),
        raw_error=err_tail,
        exit_code=exit_code,
        argv=argv,
        failure_kind=diagnosis.kind,
        failure_title=diagnosis.title,
        fix_hint=diagnosis.hint,
    )


# ── Shared-blackboard envelope (octopus-mediated stigmergy) ──────────
# External CLIs are black boxes: we can't touch their internal context. So
# teammates collaborate at the I/O boundary — brief the agent FROM the shared
# blackboard (read → into the prompt) and harvest its output BACK to the
# blackboard (so the next teammate's brief sees it). Shell-capable CLIs can also
# read/write the same board directly via ``octopus bb`` (we pass the env).

_BRIEF_VALUE_CAP = 300
_HARVEST_CAP = 4000


def blackboard_brief(turn_id: str | None, *, max_entries: int = 8) -> str:
    """A compact digest of the turn's shared blackboard, to brief a teammate —
    ``""`` when there's nothing to share (or no turn / no board). Best-effort."""
    if not turn_id:
        return ""
    try:
        from runtime.memory.runtime_state.blackboard import get_blackboard

        board = get_blackboard(str(turn_id))
        snap = board.snapshot() if board is not None else {}
    except Exception:  # noqa: BLE001 — briefing is strictly best-effort
        return ""
    if not isinstance(snap, dict) or not snap:
        return ""
    lines: list[str] = []
    for key, value in list(snap.items())[: max(1, max_entries)]:
        text = str(value)
        if len(text) > _BRIEF_VALUE_CAP:
            text = text[:_BRIEF_VALUE_CAP].rstrip() + "…"
        lines.append(f"- {key}: {text}")
    return "TEAM SHARED CONTEXT (from the shared blackboard):\n" + "\n".join(lines)


def harvest_to_blackboard(turn_id: str | None, writer: str | None, output: str) -> None:
    """Write a partner's output back to the turn blackboard so teammates see it.
    Best-effort; no-op without a turn / output / board."""
    if not turn_id or not (output or "").strip():
        return
    try:
        from runtime.memory.runtime_state.blackboard import get_blackboard

        board = get_blackboard(str(turn_id))
        if board is not None:
            board.write(
                f"partner.{writer or 'agent'}.output",
                output[:_HARVEST_CAP],
                writer=str(writer or "partner"),
            )
    except Exception:  # noqa: BLE001 — harvesting is strictly best-effort
        pass
