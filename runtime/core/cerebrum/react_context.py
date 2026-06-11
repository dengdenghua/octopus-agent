from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from runtime.core.cerebrum.capability_router import (
    activate_capabilities,
    order_skill_names,
)

_logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn / 1.5 + en / 4)


def _estimate_messages_tokens(messages: list) -> int:
    return sum(_estimate_tokens(getattr(m, "content", "") or "") for m in messages)


def _compress_context(
    messages: list,
    *,
    max_tokens: int = 60000,
    router: Any = None,
    model: str = "",
    is_code_mode: bool = False,
) -> list:
    total = _estimate_messages_tokens(messages)
    if total <= max_tokens:
        return messages

    keep_head = 0
    for j, m in enumerate(messages):
        if getattr(m, "role", "") == "system":
            keep_head = j + 1
        else:
            break

    keep_tail = 8
    if len(messages) <= keep_head + keep_tail:
        return messages

    mid_start = keep_head
    mid_end = len(messages) - keep_tail
    mid_messages = messages[mid_start:mid_end]

    if router is not None and len(mid_messages) > 4:
        summary = _summarize_messages(mid_messages, router, model)
        if summary:
            from runtime.sensing.model_router.models import Message
            compressed = list(messages[:mid_start])
            compressed.append(Message(
                role="system",
                content=(
                    "[以下是之前对话的摘要]\n"
                    f"{summary}\n"
                    "[摘要结束 · 最近对话如下]"
                ),
            ))
            compressed.extend(messages[mid_end:])
            _logger.info(
                "context compressed with LLM summary: %d tokens → ~%d tokens",
                total, _estimate_messages_tokens(compressed),
            )
            return compressed

    if is_code_mode:
        compressed = list(messages[:mid_start])
        for m in mid_messages:
            content = getattr(m, "content", "") or ""
            role = getattr(m, "role", "")
            is_file_obs = (
                role == "user"
                and content.startswith("Observation:")
                and any(
                    marker in content
                    for marker in (
                        "read_file", "edit_text_file", "edit_file",
                        "multi_edit_file", "write_text_file",
                        "list_cwd", "todo_write",
                    )
                )
            )
            if is_file_obs:
                compressed.append(m)
            elif role == "user" and content.startswith("Observation:"):
                short = content[:200] + "... [已压缩]" if len(content) > 200 else content
                from runtime.sensing.model_router.models import Message
                compressed.append(Message(role=role, content=short))
            else:
                compressed.append(m)
        compressed.extend(messages[mid_end:])
        _logger.info(
            "context compressed (code-aware): %d tokens → ~%d tokens",
            total, _estimate_messages_tokens(compressed),
        )
        return compressed

    compressed = list(messages[:mid_start])
    for m in mid_messages:
        content = getattr(m, "content", "") or ""
        role = getattr(m, "role", "")
        if role == "user" and content.startswith("Observation:"):
            short = content[:200] + "... [已压缩]" if len(content) > 200 else content
            from runtime.sensing.model_router.models import Message
            compressed.append(Message(role=role, content=short))
        else:
            compressed.append(m)

    compressed.extend(messages[mid_end:])
    _logger.info(
        "context compressed (truncation): %d tokens → ~%d tokens (%d msgs → %d msgs)",
        total, _estimate_messages_tokens(compressed),
        len(messages), len(compressed),
    )
    return compressed


def _summarize_messages(messages: list, router: Any, model: str) -> str:
    try:
        from runtime.sensing.model_router.models import Message, ModelRequest
        content_parts = []
        for m in messages:
            role = getattr(m, "role", "")
            text = (getattr(m, "content", "") or "")[:300]
            if text.strip():
                content_parts.append(f"[{role}] {text}")
        if not content_parts:
            return ""
        conversation = "\n".join(content_parts[-20:])
        req = ModelRequest(
            model=model or "molili",
            messages=[
                Message(
                    role="system",
                    content=(
                        "你是一个对话摘要助手。把以下对话压缩成 3-5 句话的摘要，"
                        "保留关键信息（工具调用结果、决策、发现）。只输出摘要，不要解释。"
                    ),
                ),
                Message(role="user", content=conversation),
            ],
            max_tokens=300,
            temperature=0.1,
        )
        resp = router.call(req)
        return (resp.text or "").strip()
    except (ConnectionError, TimeoutError, TypeError, ValueError):  # noqa: BLE001
        return ""


def _format_skill_catalog(
    registry: Any,
    *,
    max_skills: int = 100,
    user_context: dict | None = None,
    agent: Any = None,
    goal: str = "",
) -> str:
    try:
        names = list(registry.all_names())
    except (AttributeError, TypeError, ValueError):  # noqa: BLE001
        return ""

    # Skills hidden from the single-agent ReAct catalog. They're
    # registered (so the bridge can dispatch when invoked) but kept
    # out of the prompt's skill listing so the model doesn't try
    # to use them when there's no swarm context.
    #
    # ``deep-research-swarm`` belongs to swarm mode only — it
    # dispatches into ``research_swarm_v1`` via TeamRunner, which
    # spawns sub-agents through ``ephemeral_runner``. That path
    # requires native ``tools`` support; offering it from a single-
    # agent loop tempts the model to call it from Agent / Inspiration
    # mode where the upstream model may not support function calling
    # and the call ends up doing nothing visible.
    # ``deep-research`` is the Agent-mode counterpart: it returns
    # the 7-phase instruction document the parent ReAct loop drives
    # via atomic web_search / fetch_url. Keep that one available.
    # ``call_agent`` is blocked by the ReAct executor because serial
    # single-subagent delegation is usually worse than the lead just doing
    # the work. Keep ``call_agent_parallel`` visible: it is the real
    # Kimi-style fan-out tool for independent lanes in Agent/Swarm mode.
    #
    # OVERRIDE: ``deep-research-swarm`` force-enabled in Agent mode per
    # user request. Risk: if the primary model lacks tool support
    # (Haiku, Inspiration, or certain DeepSeek variants), invocations
    # will fail with a cryptic error. The caller is responsible for
    # using a tool-capable model (Opus, Sonnet, Kimi, DeepSeek-R1).
    hidden_in_react: set[str] = {
        "exit_plan_mode",
        # "deep-research-swarm",  # force-enabled: user accepts tool-support risk
        "call_agent",
    }

    def _enabled(name: str) -> bool:
        try:
            return bool(registry.is_enabled(name))
        except (AttributeError, TypeError, ValueError):  # noqa: BLE001
            return True

    names = [n for n in names if n not in hidden_in_react and _enabled(n)]

    if agent is not None:
        allowed: set[str] | None
        try:
            allowed = set(agent.allowed_skill_union())
            agent_aff = {str(a).lower() for a in agent.affinity()}
        except (AttributeError, TypeError, ValueError):  # noqa: BLE001 - fail open to old behavior
            allowed = None
            agent_aff = set()

        if allowed is not None:
            allow_all = "*" in allowed
            try:
                from runtime.execution.all_skills import skill_kind as _classify
            except ImportError:
                _classify = lambda _name: "domain"  # noqa: E731

            def _visible(name: str) -> bool:
                if allow_all:
                    return True
                if name in allowed:
                    return True
                kind = _classify(name)
                if kind == "domain":
                    try:
                        skill = registry.get(name)
                        skill_aff = {
                            str(a).lower()
                            for a in (getattr(skill, "affinity", None) or [])
                        }
                    except (AttributeError, TypeError, ValueError):  # noqa: BLE001
                        return True
                    if not skill_aff:
                        return False
                    if not agent_aff:
                        return True
                    return bool(skill_aff & agent_aff)
                return False

            names = [n for n in names if _visible(n)]

    if not names:
        return ""
    priority = [
        # Planning + tool discovery.
        "todo_write",
        "search_capabilities",
        "query_capability",
        "use_capability",
        "search_skills",
        "query_skill",

        # Files + code inspection/editing.
        "list_cwd",
        "read_file",
        "file_stats",
        "code_search",
        "code_find_symbol",
        "code_analyze",
        "write_text_file",
        "edit_file",
        "multi_edit_file",
        "append_text_file",
        "edit_text_file",

        # Web research + URL reading.
        "web_search",
        "web_fetch",
        "fetch_url",

        # Local execution + background jobs.
        "exec_shell",
        "ipython",
        "background_exec",
        "read_background_output",
        "kill_background_exec",

        # Git workflow.
        "git_status",
        "git_diff",
        "git_log",
        "git_add",
        "git_commit",
        "git_branch",

        # Delegation + shared blackboard.
        "call_agent_parallel",
        "bb_write",
        "bb_read",
        "bb_keys",

        # Browser/Desktop observation for UI work.
        "browser_navigate",
        "browser_get",
        "browser_extract",
        "browser_screenshot",
        "browser_click",
        "screen_capture",
        "screen_info",

        # High-level document/research workflows.
        "deep-research",
        "report-writing",
        "docx",
    ]
    priority_set = set(priority)
    names = [n for n in priority if n in names] + [
        n for n in names if n not in priority_set
    ]
    activation = activate_capabilities(
        goal,
        user_context=user_context,
        registry=registry,
    )
    names = order_skill_names(
        names,
        activation=activation,
        registry=registry,
    )
    lines: list[str] = ["可用工具 (skill):"]
    for name in names[:max_skills]:
        try:
            skill = registry.get(name)
            # Progressive disclosure (octopus optimisation lane C):
            # the catalog only lists name + ≤30字 short description.
            # The model can call ``query_skill(name)`` for the full
            # parameter schema + long description when it actually
            # needs to invoke the skill. This keeps the system prompt
            # small and stable so prompt cache stays warm.
            short = (
                (getattr(skill, "summary", "") or "").strip()
                or (getattr(skill, "effective_summary", "") or "").strip()
            )
            if not short:
                # Fall back to first sentence of description, capped
                # at 30 characters. Prefer to break at the first
                # punctuation so we don't dangle mid-word.
                full = (getattr(skill, "description", "") or "").strip()
                if full:
                    # Take everything up to the first sentence terminator
                    # / newline; if none, use first 30 chars.
                    cut = len(full)
                    for sep in ("。", ".", "\n", "·", ";", "；"):
                        idx = full.find(sep)
                        if 0 < idx < cut:
                            cut = idx
                    short = full[:min(cut, 30)].strip()
            if not short:
                short = "(无描述)"
        except (AttributeError, TypeError, KeyError, ValueError):  # noqa: BLE001
            short = "(无描述)"
        lines.append(f"  - {name}: {short}")
    if len(names) > max_skills:
        lines.append(f"  ... (还有 {len(names) - max_skills} 个,省略)")
    lines.append(
        "提示: 上面只列名+短描述; 调用前若需完整参数 schema 请用 "
        "`query_skill(name=\"<skill_name>\")`。",
    )
    lines.append(
        "Capability-first: prefer `search_capabilities`, "
        "`query_capability`, and `use_capability` before low-level child skills.",
    )
    return "\n".join(lines)


_PROJECT_RULES_FILES = [
    ".octopus/rules.md",
    ".cursorrules",
    "CLAUDE.md",
]
_PROJECT_RULES_MAX_BYTES = 8 * 1024


def _load_project_rules(workspace_path: str) -> str:
    from pathlib import Path
    root = Path(workspace_path)
    for name in _PROJECT_RULES_FILES:
        p = root / name
        try:
            if p.is_file() and p.stat().st_size <= _PROJECT_RULES_MAX_BYTES:
                return p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
    return ""


def _git_status_summary(root: Any) -> str:
    """Compact one-line git status for project-profile injection.

    Format: ``branch=<name> modified=<n> untracked=<n> [ahead=<n>] [behind=<n>] last="<msg>"``.
    Returns "" silently when git isn't available, the path isn't a
    repo, or the subprocess errors. The goal is to give the model the
    same situational awareness a human gets at first glance, without
    adding seconds to turn startup.

    Capped to ~200 chars total so it never dominates the profile
    section of the system prompt.
    """
    import subprocess
    from pathlib import Path

    try:
        path = Path(root)
        if not (path / ".git").exists():
            return ""
    except (OSError, TypeError, ValueError):
        return ""

    def _git(*args: str, timeout: float = 1.5) -> str:
        try:
            r = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if r.returncode != 0:
            return ""
        return r.stdout.strip()

    branch = _git("branch", "--show-current") or "(detached)"
    porcelain = _git("status", "--porcelain")
    modified = sum(
        1 for line in porcelain.splitlines()
        if line and not line.startswith("??")
    )
    untracked = sum(
        1 for line in porcelain.splitlines()
        if line.startswith("??")
    )

    ahead = behind = 0
    upstream = _git("rev-list", "--left-right", "--count", "@{u}...HEAD")
    if upstream:
        # Output is "<behind>\t<ahead>" relative to upstream.
        parts = upstream.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            behind, ahead = int(parts[0]), int(parts[1])

    last = _git("log", "-1", "--pretty=format:%h %s")
    last_short = (last[:60] + "…") if len(last) > 60 else last

    parts: list[str] = [f"branch={branch}"]
    if modified:
        parts.append(f"modified={modified}")
    if untracked:
        parts.append(f"untracked={untracked}")
    if ahead:
        parts.append(f"ahead={ahead}")
    if behind:
        parts.append(f"behind={behind}")
    if last_short:
        parts.append(f'last="{last_short}"')
    return " ".join(parts)


def _build_project_profile_prompt(workspace_path: str, *, include_diagnostics: bool = False) -> str:
    try:
        from pathlib import Path

        from runtime.execution.suckers.verify_skills import detect_project

        profile = detect_project(workspace_path)
        if profile.kind == "unknown":
            return ""

        root = Path(workspace_path)
        lines = [f"项目类型: {profile.kind}"]

        # Git situational awareness — give the model the same first-look
        # context a human would notice (octopus optimisation §26).
        # Cheap subprocess (≤ 50 ms typical), all best-effort: missing
        # git, not-a-repo, hung remote — silently skip rather than
        # delaying turn start.
        _git_summary = _git_status_summary(root)
        if _git_summary:
            lines.append(f"git: {_git_summary}")

        if profile.kind.startswith("node"):
            pkg_path = root / "package.json"
            if pkg_path.is_file():
                import json
                try:
                    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
                    if pkg.get("name"):
                        lines.append(f"包名: {pkg['name']}")
                    scripts = pkg.get("scripts", {})
                    if scripts:
                        lines.append(f"可用脚本: {', '.join(sorted(scripts.keys())[:12])}")
                    deps = list(pkg.get("dependencies", {}).keys())[:8]
                    if deps:
                        lines.append(f"主要依赖: {', '.join(deps)}")
                    if (root / "tsconfig.json").is_file():
                        lines.append("TypeScript: 已启用")
                    for fw in [
                        "next", "nuxt", "vite", "react",
                        "vue", "svelte", "angular",
                    ]:
                        if (
                            fw in pkg.get("dependencies", {})
                            or fw in pkg.get("devDependencies", {})
                        ):
                            lines.append(f"框架: {fw}")
                            break
                except (TypeError, ValueError) as exc:
                    _logger.debug("framework detection skipped: %s", exc)

        elif profile.kind == "python":
            for entry in ["src", "app", "main.py", "manage.py", "setup.py"]:
                if (root / entry).exists():
                    lines.append(f"入口: {entry}")
                    break
            if (root / "requirements.txt").is_file():
                lines.append("包管理: requirements.txt")
            elif (root / "pyproject.toml").is_file():
                lines.append("包管理: pyproject.toml")

        elif profile.kind == "rust":
            lines.append("构建: cargo")

        elif profile.kind == "go":
            lines.append("构建: go build")

        if profile.checks:
            check_names = [c["name"] for c in profile.checks]
            lines.append(f"验证命令: {', '.join(check_names)}")

        if include_diagnostics and profile.checks:
            _diag_lines = _collect_initial_diagnostics(profile, workspace_path)
            if _diag_lines:
                lines.append("")
                lines.append("⚠ 当前项目诊断状态 (开始前已知):")
                lines.extend(_diag_lines)

        return "\n".join(lines)
    except (TypeError, ValueError, OSError):
        return ""


def _collect_initial_diagnostics(profile: Any, workspace_path: str) -> list[str]:
    try:
        from runtime.execution.suckers.verify_skills import run_checks
        fast_checks = [
            c for c in profile.checks
            if c["name"] in ("typecheck", "check", "vet", "syntax")
        ]
        if not fast_checks:
            return []
        fast_profile = profile.__class__(
            kind=profile.kind,
            root=profile.root,
            checks=fast_checks[:1],
        )
        results = run_checks(fast_profile, timeout_per_check=15, max_output=2000)
        diag_lines: list[str] = []
        for r in results:
            if r.passed:
                diag_lines.append(f"  ✓ {r.name}: 通过")
            else:
                output = (r.stderr or r.stdout or "").strip()
                if len(output) > 800:
                    output = output[:800] + "\n  ...(截断)"
                diag_lines.append(f"  ✗ {r.name}: 失败")
                if output:
                    for line in output.split("\n")[:12]:
                        diag_lines.append(f"    {line}")
        has_failure = any(not r.passed for r in results)
        return diag_lines if has_failure else []
    except (OSError, TypeError, ValueError) as exc:
        _logger.debug("_collect_initial_diagnostics failed: %s", exc)
        return []


def _serialize_messages_for_checkpoint(messages: list) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        entry: dict[str, Any] = {"role": getattr(m, "role", "")}
        content = getattr(m, "content", "")
        if isinstance(content, list):
            entry["content"] = content
        else:
            entry["content"] = str(content) if content else ""
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            entry["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "input": tc.input}
                for tc in tool_calls
            ]
        tool_call_id = getattr(m, "tool_call_id", None)
        if tool_call_id:
            entry["tool_call_id"] = tool_call_id
        name = getattr(m, "name", None)
        if name:
            entry["name"] = name
        result.append(entry)
    return result


def _restore_messages_from_checkpoint(snapshot: list[dict[str, Any]]) -> list:
    from runtime.sensing.model_router.models import Message, ToolCall
    result: list[Message] = []
    for m in snapshot:
        if not isinstance(m, dict) or not m.get("role"):
            continue
        content = m.get("content", "")
        if not content:
            continue
        msg = Message(role=m["role"], content=content)
        tool_calls_data = m.get("tool_calls")
        if tool_calls_data and isinstance(tool_calls_data, list):
            try:
                tcs = tuple(
                    ToolCall(id=tc["id"], name=tc["name"], input=tc.get("input", {}))
                    for tc in tool_calls_data
                    if isinstance(tc, dict) and tc.get("id") and tc.get("name")
                )
                if tcs:
                    msg = msg.model_copy(update={"tool_calls": tcs})
            except (TypeError, ValueError) as exc:
                _logger.debug("tool_calls restore skipped: %s", exc)
        result.append(msg)
    return result


def _prefetch_related_files(
    action: str | None,
    working_set: dict[str, Any],
) -> str | None:
    if not action:
        return None
    try:
        import re
        _path_match = re.search(r'["\']([^"\']+\.(?:py|ts|tsx|js|jsx|go|rs))["\']', action)
        if not _path_match:
            return None
        edited_path = _path_match.group(1)
        import os
        if not os.path.isfile(edited_path):
            return None
        with open(edited_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        _import_patterns = [
            r'(?:from|import)\s+["\'](\.{1,2}/[^"\']+)["\']',
            r'(?:from|import)\s+["\'](\./[^"\']+)["\']',
            r'(?:from|import)\s+["\'](\.\./[^"\']+)["\']',
        ]
        local_imports = set()
        for pat in _import_patterns:
            for m in re.finditer(pat, content):
                imp = m.group(1)
                for ext in ("", ".ts", ".tsx", ".js", ".py", "/index.ts", "/index.py"):
                    candidate = imp + ext
                    if os.path.isfile(candidate) and candidate not in working_set:
                        local_imports.add(candidate)
                        break
        if not local_imports:
            return None
        parts = []
        total = 0
        for fp in sorted(local_imports)[:3]:
            with open(fp, encoding="utf-8", errors="replace") as f:
                fc = f.read()
            if total + len(fc) > 3000:
                fc = fc[: (3000 - total)] + "\n...(截断)"
            parts.append(f"--- {fp} ---\n{fc}")
            total += len(fc)
            if total >= 3000:
                break
        return "\n\n".join(parts) if parts else None
    except (OSError, ValueError):
        return None


_CODE_CONTEXT_README_NAMES = ("README.md", "readme.md")
_CODE_CONTEXT_STYLE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs")
_CODE_CONTEXT_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    "target",
}


def _build_code_context_prelude(workspace_path: str) -> str:
    root = Path(workspace_path).expanduser()
    if not root.is_dir():
        return ""

    parts: list[str] = ["[startup-code-context]"]

    readme = _find_code_context_readme(root)
    if readme is not None:
        readme_text = _read_code_context_file(readme, max_chars=2000)
        if readme_text:
            readme_rel = readme.relative_to(root).as_posix()
            parts.append(f'Observation: read_file("{readme_rel}")')
            parts.append(f"Path: {readme.relative_to(root).as_posix()}")
            parts.append(readme_text)

    style_file = _find_code_context_style_file(root)
    if style_file is not None and style_file != readme:
        style_text = _read_code_context_file(style_file, max_chars=1500)
        if style_text:
            style_rel = style_file.relative_to(root).as_posix()
            parts.append(f'Observation: read_file("{style_rel}")')
            parts.append(f"Path: {style_file.relative_to(root).as_posix()}")
            parts.append(style_text)

    if len(parts) == 1:
        return ""
    return "\n\n".join(parts)


def _find_code_context_readme(root: Path) -> Path | None:
    for name in _CODE_CONTEXT_README_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    try:
        for candidate in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if candidate.is_file() and candidate.name.lower() == "readme.md":
                return candidate
    except OSError:
        return None
    return None


def _find_code_context_style_file(root: Path) -> Path | None:
    def _candidate_depth(path: Path) -> int:
        return len(path.relative_to(root).parts)

    candidates: list[Path] = []
    try:
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.is_file() and child.suffix.lower() in _CODE_CONTEXT_STYLE_SUFFIXES:
                if child.name.lower() != "readme.md":
                    candidates.append(child)
            elif child.is_dir():
                if child.name in _CODE_CONTEXT_SKIP_DIR_NAMES:
                    continue
                try:
                    for grand in sorted(child.iterdir(), key=lambda p: p.name.lower()):
                        if grand.is_file() and grand.suffix.lower() in _CODE_CONTEXT_STYLE_SUFFIXES:  # noqa: SIM102
                            if grand.name.lower() != "readme.md":
                                candidates.append(grand)
                                break
                except OSError:
                    continue
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(key=lambda p: (_candidate_depth(p), p.as_posix().lower()))
    return candidates[0]


def _read_code_context_file(path: Path, *, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(truncated)"
    return text
