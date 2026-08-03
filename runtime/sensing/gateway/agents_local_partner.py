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

Module organization (this file keeps the runtime-sensitivity-relevant core so
that test monkeypatches of ``which_command`` / ``run_local_partner`` /
``subprocess.run`` / ``_login_shell_path`` keep working; the rest lives in
``_agents_local_partner_*`` sibling submodules):
  * ``LOCAL_PARTNER_SPECS`` — the registry of supported partners
    (``_agents_local_partner_specs``)
  * ``validate_alias`` / ``identity_has_admin_role`` / ``safe_executable`` —
    security gates (``_agents_local_partner_security``)
  * ``which_command`` / ``dir_registered`` / ``resolve_local_command`` —
    detection helpers (kept here)
  * ``to_wire`` / ``soul_template`` — output formatters
  * ``doctor_summary`` — readiness aggregation (``_agents_local_partner_doctor``)
  * ``write_partner_agent`` — the registration writer
    (``_agents_local_partner_writer``)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.execution.agents.local_partner_bridge import build_partner_argv, run_local_partner

from ._agents_local_partner_doctor import doctor_summary
from ._agents_local_partner_guidance import (
    _is_codebuddy_launcher,
    _partner_command_hints,
    _partner_diagnostic_items,
    _partner_guidance,
)
from ._agents_local_partner_security import (
    identity_has_admin_role,
    safe_executable,
    validate_alias,
)
from ._agents_local_partner_specs import LOCAL_PARTNER_SPECS
from ._agents_local_partner_writer import soul_template, write_partner_agent
from .agents_models import LocalPartnerWire

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
                "fix_hint": (
                    f"在 Trae CLI 中用 /model 选择模型，或检查 {source}；"
                    "如果桌面端可用但 CLI models 为空，通常需要单独完成 CLI 登录/企业网络/模型授权。"
                ),
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


def _path_entries(raw: str | None) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").split(os.pathsep):
        item = os.path.expanduser(part.strip())
        if not item or item in seen:
            continue
        seen.add(item)
        entries.append(item)
    return entries


def _common_local_bin_entries() -> list[str]:
    home = Path.home()
    return [
        str(home / ".local" / "bin"),
        str(home / ".local" / "node" / "bin"),
        str(home / ".codebuddy" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/Applications/ChatGPT.app/Contents/Resources",
    ]


@lru_cache(maxsize=1)
def _login_shell_path() -> str:
    shell = os.environ.get("SHELL", "").strip()
    if not shell or not Path(shell).is_absolute():
        return ""
    try:
        proc = subprocess.run(
            [shell, "-lc", 'printf "%s" "$PATH"'],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _candidate_path_entries() -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for source in (
        _path_entries(os.environ.get("PATH")),
        _path_entries(_login_shell_path()),
        _common_local_bin_entries(),
    ):
        for entry in source:
            if entry in seen:
                continue
            seen.add(entry)
            entries.append(entry)
    return entries


def resolve_local_command(command: str) -> str | None:
    path = shutil.which(command)
    if path:
        return path
    if os.path.sep in command or (os.path.altsep and os.path.altsep in command):
        return None
    for directory in _candidate_path_entries():
        candidate = Path(directory) / command
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
        except OSError:
            continue
    return None


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
                continue
        path = resolve_local_command(command)
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
    readiness_status = str(readiness.get("readiness_status") or status)
    effective_status = (
        "registered" if registered and readiness_status == "ready" else readiness_status
    )
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
        effective_status=effective_status,
        command=command,
        executable=executable,
        ready=bool(readiness.get("ready")),
        headless_supported=bool(readiness.get("headless_supported")),
        readiness_status=readiness_status,
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
        diagnostic_items=_partner_diagnostic_items(
            str(spec["id"]),
            command=command,
            ready=bool(readiness.get("ready")),
            headless_supported=bool(readiness.get("headless_supported")),
            readiness_status=readiness_status,
            verify_command=guidance.get("verify_command"),
        ),
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


__all__ = [
    "LOCAL_PARTNER_SPECS",
    "dir_registered",
    "doctor_summary",
    "identity_has_admin_role",
    "partner_model",
    "probe_partner",
    "readiness_for_partner",
    "resolve_local_command",
    "safe_executable",
    "soul_template",
    "to_wire",
    "validate_alias",
    "which_command",
    "write_partner_agent",
]
