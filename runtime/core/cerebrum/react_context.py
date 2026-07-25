from __future__ import annotations

import json
import logging
from collections.abc import Collection
from pathlib import Path
from typing import Any

from runtime.core.cerebrum.capability_router import (
    activate_capabilities,
    order_skill_names,
)

_logger = logging.getLogger(__name__)


def _content_to_text(content: Any) -> str:
    """Best-effort text projection for string or structured LLM content blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part for part in (_content_to_text(item) for item in content) if part)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        nested = content.get("content")
        if nested is not None:
            return _content_to_text(nested)
        image_url = content.get("image_url")
        if isinstance(image_url, str):
            return image_url
        if isinstance(image_url, dict):
            return str(image_url.get("url") or "")
        try:
            return json.dumps(content, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


def _estimate_tokens(text: Any) -> int:
    text = _content_to_text(text)
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en = len(text) - cn
    return int(cn / 1.5 + en / 4)


def _estimate_messages_tokens(messages: list) -> int:
    return sum(_estimate_tokens(getattr(m, "content", "") or "") for m in messages)


def context_budget_tokens_for_model(model: str | None) -> int:
    """Return the coarse context budget used by pressure + compression.

    The hot path intentionally avoids tokenizer imports.  Budgets are in
    the same approximate token units as ``_estimate_tokens`` so Chinese
    text no longer gets treated as if one character were one English
    character.
    """
    name = (model or "").lower()
    try:
        from runtime.sensing.model_router.custom_model_flags import model_context_window

        configured_window = model_context_window(model or "")
    except ImportError:
        configured_window = None
    if configured_window is not None:
        # Reserve 10% for the next response, tool schemas and provider-side
        # accounting differences instead of filling the advertised window.
        return max(25_000, int(configured_window * 0.9))
    if any(model_id in name for model_id in ("glm-5.2", "deepseek-v4-flash", "deepseek-v4-pro")):
        return 230_400
    if "claude-3-5" in name or "claude-4" in name or "claude-sonnet" in name:
        return 150_000
    if "gpt-4o" in name or "gpt-5" in name:
        return 100_000
    return 25_000


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
        return _ensure_context_budget(messages, max_tokens=max_tokens)

    mid_start = keep_head
    mid_end = len(messages) - keep_tail
    mid_messages = messages[mid_start:mid_end]

    # Code trajectories need an auditable execution history.  A generated
    # summary can accidentally promote a failed shell/edit attempt into a
    # claimed file mutation or passing test, so code mode always uses the
    # deterministic observation-preserving branch below.
    if router is not None and len(mid_messages) > 4 and not is_code_mode:
        summary = _summarize_messages(mid_messages, router, model)
        if summary:
            from runtime.platform.models.llm import Message

            compressed = list(messages[:mid_start])
            compressed.append(
                Message(
                    role="system",
                    content=(f"[以下是之前对话的摘要]\n{summary}\n[摘要结束 · 最近对话如下]"),
                )
            )
            compressed.extend(messages[mid_end:])
            _logger.info(
                "context compressed with LLM summary: %d tokens → ~%d tokens",
                total,
                _estimate_messages_tokens(compressed),
            )
            return _ensure_context_budget(compressed, max_tokens=max_tokens)

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
                        "read_file",
                        "edit_text_file",
                        "edit_file",
                        "multi_edit_file",
                        "write_text_file",
                        "list_cwd",
                        "todo_write",
                    )
                )
            )
            if is_file_obs:
                compressed.append(m)
            elif role == "user" and content.startswith("Observation:"):
                short = content[:200] + "... [已压缩]" if len(content) > 200 else content
                from runtime.platform.models.llm import Message

                compressed.append(Message(role=role, content=short))
            else:
                compressed.append(m)
        compressed.extend(messages[mid_end:])
        _logger.info(
            "context compressed (code-aware): %d tokens → ~%d tokens",
            total,
            _estimate_messages_tokens(compressed),
        )
        return _ensure_context_budget(compressed, max_tokens=max_tokens)

    compressed = list(messages[:mid_start])
    for m in mid_messages:
        content = getattr(m, "content", "") or ""
        role = getattr(m, "role", "")
        if role == "user" and content.startswith("Observation:"):
            short = content[:200] + "... [已压缩]" if len(content) > 200 else content
            from runtime.platform.models.llm import Message

            compressed.append(Message(role=role, content=short))
        else:
            compressed.append(m)

    compressed.extend(messages[mid_end:])
    _logger.info(
        "context compressed (truncation): %d tokens → ~%d tokens (%d msgs → %d msgs)",
        total,
        _estimate_messages_tokens(compressed),
        len(messages),
        len(compressed),
    )
    return _ensure_context_budget(compressed, max_tokens=max_tokens)


def _ensure_context_budget(messages: list, *, max_tokens: int) -> list:
    """Hard cap compressed context when soft summarization still runs long."""
    if max_tokens <= 0 or _estimate_messages_tokens(messages) <= max_tokens:
        return messages

    keep_head = 0
    for j, m in enumerate(messages):
        if getattr(m, "role", "") == "system":
            keep_head = j + 1
        else:
            break

    head = list(messages[:keep_head])
    if _estimate_messages_tokens(head) >= max_tokens:
        out = (
            [_trim_message_to_budget(head[-1], head_tokens=0, max_tokens=max_tokens)]
            if head
            else []
        )
        _logger.info(
            "context hard-capped oversized system head: ~%d tokens → ~%d tokens (%d msgs → %d msgs)",
            _estimate_messages_tokens(messages),
            _estimate_messages_tokens(out),
            len(messages),
            len(out),
        )
        return out

    kept_tail: list[Any] = []
    for m in reversed(messages[keep_head:]):
        candidate = head + [m] + list(reversed(kept_tail))
        if _estimate_messages_tokens(candidate) <= max_tokens:
            kept_tail.append(m)
            continue
        if not kept_tail:
            kept_tail.append(
                _trim_message_to_budget(
                    m, head_tokens=_estimate_messages_tokens(head), max_tokens=max_tokens
                )
            )
        break

    out = head + list(reversed(kept_tail))
    _logger.info(
        "context hard-capped after compression: ~%d tokens → ~%d tokens (%d msgs → %d msgs)",
        _estimate_messages_tokens(messages),
        _estimate_messages_tokens(out),
        len(messages),
        len(out),
    )
    return out


def _trim_message_to_budget(message: Any, *, head_tokens: int, max_tokens: int) -> Any:
    content = _content_to_text(getattr(message, "content", "") or "")
    role = getattr(message, "role", "")
    remaining_tokens = max(1, max_tokens - head_tokens)
    prefix = "[前文因上下文预算已截断]\n"
    prefix_tokens = _estimate_tokens(prefix)
    trimmed = _suffix_within_token_budget(content, max(1, remaining_tokens - prefix_tokens))
    if len(trimmed) < len(content):
        trimmed = prefix + trimmed
    from runtime.platform.models.llm import Message

    return Message(role=role or "user", content=trimmed)


def _suffix_within_token_budget(content: str, max_tokens: int) -> str:
    if _estimate_tokens(content) <= max_tokens:
        return content
    lo = 0
    hi = len(content)
    best = ""
    while lo <= hi:
        size = (lo + hi) // 2
        candidate = content[-size:] if size else ""
        if _estimate_tokens(candidate) <= max_tokens:
            best = candidate
            lo = size + 1
        else:
            hi = size - 1
    return best


def _summarize_messages(messages: list, router: Any, model: str) -> str:
    try:
        from runtime.platform.models.llm import Message, ModelRequest

        content_parts = []
        for m in messages:
            role = getattr(m, "role", "")
            text = _content_to_text(getattr(m, "content", "") or "")[:300]
            if text.strip():
                content_parts.append(f"[{role}] {text}")
        if not content_parts:
            return ""
        conversation = "\n".join(content_parts[-20:])
        req = ModelRequest(
            model=model or "auto",
            messages=[
                Message(
                    role="system",
                    content=(
                        "你是一个对话摘要助手。把以下对话压缩成 3-5 句话的摘要，"
                        "保留关键信息（工具调用结果、决策、发现）。严格区分工具调用尝试与"
                        "已确认成功的结果：只有明确的成功 Observation 才能写成已完成；"
                        "失败、缺少结果或不确定时必须标成未验证，禁止推断文件已写入、"
                        "测试已通过或命令已成功。只输出摘要，不要解释。"
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
    include_names: Collection[str] | None = None,
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
    if include_names is not None:
        allowed_names = frozenset(include_names)
        names = [name for name in names if name in allowed_names]

    # A code regression preview runs in Octopus' isolated Playwright browser,
    # not the desktop Electron surface.  Hide incompatible live-browser tools
    # instead of relying on the model to recover after a guaranteed failure.
    from runtime.core.cerebrum.capability_router import filter_surface_compatible_skills

    names = filter_surface_compatible_skills(names, user_context=user_context)

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
                            str(a).lower() for a in (getattr(skill, "affinity", None) or [])
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
        "live_browser_state",
        "live_browser_current_url",
        "live_browser_navigate",
        "live_browser_extract",
        "live_browser_find",
        "live_browser_click",
        "live_browser_type",
        "live_browser_wait",
        "live_browser_scroll",
        "live_browser_screenshot",
        "browser_get",
        "browser_extract",
        "browser_screenshot",
        "browser_click",
        "browser_type",
        "browser_upload",
        "screen_capture",
        "screen_info",
        # High-level document/research workflows.
        "deep-research",
        "report-writing",
        "docx",
    ]
    priority_set = set(priority)
    names = [n for n in priority if n in names] + [n for n in names if n not in priority_set]
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
            short = (getattr(skill, "summary", "") or "").strip() or (
                getattr(skill, "effective_summary", "") or ""
            ).strip()
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
                    short = full[: min(cut, 30)].strip()
            if not short:
                short = "(无描述)"
        except (AttributeError, TypeError, KeyError, ValueError):  # noqa: BLE001
            short = "(无描述)"
        lines.append(f"  - {name}: {short}")
    if len(names) > max_skills:
        lines.append(f"  ... (还有 {len(names) - max_skills} 个,省略)")
    lines.append(
        "提示: 上面只列名+短描述; 调用前若需完整参数 schema 请用 "
        '`query_skill(name="<skill_name>")`。',
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
    modified = sum(1 for line in porcelain.splitlines() if line and not line.startswith("??"))
    untracked = sum(1 for line in porcelain.splitlines() if line.startswith("??"))

    ahead = behind = 0
    upstream = _git("rev-list", "--left-right", "--count", "@{u}...HEAD")
    if upstream:
        # Output is "<behind>\t<ahead>" relative to upstream.
        upstream_parts = upstream.split()
        if (
            len(upstream_parts) == 2
            and upstream_parts[0].isdigit()
            and upstream_parts[1].isdigit()
        ):
            behind, ahead = int(upstream_parts[0]), int(upstream_parts[1])

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
                        "next",
                        "nuxt",
                        "vite",
                        "react",
                        "vue",
                        "svelte",
                        "angular",
                    ]:
                        if fw in pkg.get("dependencies", {}) or fw in pkg.get(
                            "devDependencies", {}
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
            c for c in profile.checks if c["name"] in ("typecheck", "check", "vet", "syntax")
        ]
        if not fast_checks:
            return []
        fast_profile = profile.__class__(
            kind=profile.kind,
            root=profile.root,
            checks=fast_checks[:1],
        )
        from runtime.execution.suckers.verify_skills import (
            output_indicates_missing_tool,
        )

        results = run_checks(fast_profile, timeout_per_check=15, max_output=2000)
        diag_lines: list[str] = []
        real_failures = 0
        for r in results:
            if r.passed:
                diag_lines.append(f"  ✓ {r.name}: 通过")
                continue
            output = (r.stderr or r.stdout or "").strip()
            # A missing checker (no cargo/go/etc.) is an environment gap,
            # not a code failure — same suppression as the post-write
            # _run_auto_diagnostics path, which previously diverged.
            if output_indicates_missing_tool(output):
                continue
            real_failures += 1
            if len(output) > 800:
                output = output[:800] + "\n  ...(截断)"
            diag_lines.append(f"  ✗ {r.name}: 失败")
            if output:
                for line in output.split("\n")[:12]:
                    diag_lines.append(f"    {line}")
        return diag_lines if real_failures else []
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
                {"id": tc.id, "name": tc.name, "input": tc.input} for tc in tool_calls
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
    from runtime.platform.models.llm import Message, ToolCall

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


_CODE_CONTEXT_README_NAMES = ("README.md", "readme.md", "TASK.md")
_CODE_CONTEXT_STYLE_SUFFIXES = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".html",
    ".css",
)
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


def _build_code_context_prelude(workspace_path: str, goal: str = "") -> str:
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

    acceptance = _task_acceptance_context(goal, "\n".join(parts))
    if acceptance:
        parts.append(acceptance)

    if len(parts) == 1:
        return ""
    return "\n\n".join(parts)


def _task_acceptance_context(goal: str, observed_context: str) -> str:
    """Add bounded, task-derived acceptance checks for common high-risk work.

    This is deliberately phrased as verification guidance rather than a
    solution. It makes security and cross-cutting maintenance obligations
    stable across model providers without changing the user's requested API.
    """

    goal_text = str(goal or "").lower()
    context_text = observed_context.lower()
    checks: list[str] = []
    path_boundary_task = any(
        term in goal_text
        for term in ("path-boundary", "path boundary", "traversal", "symlink escape")
    )
    if path_boundary_task and any(
        term in context_text for term in ("unquote", "url decode", "pathboundaryerror")
    ):
        checks.append(
            "Security path-boundary acceptance: test plain, encoded, and repeatedly/double-encoded "
            "traversal; normalize separators; resolve symlinks; prove containment in the canonical "
            "root; raise the public boundary exception for every rejected input; preserve valid "
            "nested reads; and add focused regression tests for these cases."
        )
    crosscutting_change = any(
        term in goal_text for term in ("cross-cutting", "cross cutting", "rename")
    ) and any(term in goal_text for term in ("config", "configuration", "setting", "option"))
    if crosscutting_change:
        checks.append(
            "Cross-cutting configuration acceptance: search runtime consumers, schemas, CLI flags, "
            "documentation, examples/sample configs, and tests; preserve the documented legacy "
            "alias or migration path; then rerun a repository-wide search for stale names."
        )
    concurrent_cache_task = (
        "cache" in goal_text
        and any(term in goal_text for term in ("concurrent", "simultaneous", "并发"))
        and any(term in goal_text for term in ("ttl", "expire", "过期"))
    )
    if concurrent_cache_task:
        checks.append(
            "Concurrent cache acceptance: implement single-flight behavior per key so all simultaneous "
            "misses share exactly one loader result; never hold unrelated keys behind that load; wake "
            "all waiters on success or failure; do not cache exceptions; use a monotonic TTL clock; "
            "and add a barrier-based regression proving one loader call under real thread contention. "
            "Read the existing cache implementation and focused tests first, use one per-key pending "
            "state/condition instead of ad-hoc retry loops, then run the smallest targeted test and lint. "
            "Choose leader versus follower exactly once while holding the map lock; only the creator of "
            "the pending entry may call the loader, and followers must wait outside that lock. Never call "
            "a helper that re-acquires the same non-reentrant lock while its caller still holds it. A shared "
            "pending Event/result/exception entry is the simplest auditable shape. "
            "For failure fan-out tests, hold the first loader in-flight with an Event until followers "
            "have joined; a barrier only before get_or_load does not prove those callers became waiters, "
            "so do not assert scheduler-dependent exception counts. "
            "If the starter still calls the loader directly or the tests directory has no focused "
            "cache test, make the first mutations cache.py and tests/test_cache.py before invoking "
            "test tooling. Use the registered run_tests/lint_check tools; do not install dependencies, "
            "probe unrelated system Python environments, or substitute shell redirection for file tools. "
            "The only permitted product diffs are cache.py and tests/test_cache.py: do not modify "
            "pyproject.toml or add tests/__init__.py, conftest.py, helper scripts, or packaging metadata. "
            "If run_tests times out or fails, inspect its tail and repair cache.py/tests directly before "
            "running it again; do not create alternate test-runner scripts. "
            "When lint_check reports fixable import/format diagnostics, inspect its returned diff or call "
            "lint_check with fix=true instead of guessing edits or probing for a system ruff executable. "
            "Once those checks pass, stop and report the result instead of adding duplicate scripts or "
            "running unrelated broad suites."
        )
    if not checks:
        return ""
    return "[task-acceptance-contract]\n" + "\n".join(f"- {check}" for check in checks)


def _build_code_agent_mode_prompt(agent_mode: str | None) -> str:
    """Mode-specific operating contract for Agent page project/code turns."""
    mode = (agent_mode or "coder").strip().lower()
    aliases = {
        "build": "builder",
        "builder": "builder",
        "new": "builder",
        "code": "coder",
        "coder": "coder",
        "debugger": "coder",
        "architect": "architect",
        "architecture": "architect",
    }
    canonical = aliases.get(mode, "coder")
    if canonical == "builder":
        body = (
            "当前项目子模式: builder / 构建者。\n"
            "- 适合从零搭建项目、补脚手架、初始化配置、生成可运行最小闭环。\n"
            "- 先确认目标产物、运行入口和验收命令;优先创建最小可运行版本。\n"
            "- 不要过早引入大型框架或复杂抽象;每完成一个可运行切片就验证。"
        )
    elif canonical == "architect":
        body = (
            "当前项目子模式: architect / 架构师。\n"
            "- 适合跨模块设计、迁移方案、安全边界、接口契约和技术债治理。\n"
            "- 默认先读现有结构与约束,给出设计取舍;涉及大范围修改前先分阶段执行。\n"
            "- 优先保持兼容性和可回滚性;避免一次性重写核心路径。"
        )
    else:
        body = (
            "当前项目子模式: coder / 编码者。\n"
            "- 适合修 bug、加功能、写测试、重构局部代码。\n"
            "- 优先定位最小相关文件,做小步修改,每个修改点配套验证。\n"
            "- 交付时说明改了哪里、跑了什么验证、还有什么残余风险。"
        )
    return f"<code-agent-mode>\n{body}\n</code-agent-mode>"


def _build_workflow_preset_prompt(workflow_preset: str | None) -> str:
    """Operating contract for an intensity workflow preset (e.g. audit.ultracode).

    Most of the frontend's preset bundle (skill packs, verification policy) is
    advisory metadata, but ``audit.ultracode`` carries real behaviour: it steers
    the turn toward a DEEP multi-agent review instead of a single-pass read.

    Spawn DEPTH is deliberately NOT set here — it stays governed by the operator
    orchestration budget (``OCTOPUS_ORCH_TOKEN_BUDGET``; conservative 48-spawn cap
    unless the operator opts in). This prompt only steers WHAT to do, never how
    many agents to allow, so a client picking this preset cannot escalate its own
    spawn budget. The directive is also defensive about skill availability: if the
    ``run_orchestration`` skill is gated out for this agent, fall back to a manual
    multi-pass review rather than calling a tool that isn't there.
    """
    preset = (workflow_preset or "").strip().lower()
    if preset == "codex.plan":
        body = (
            "当前工作流: codex.plan / Plan 模式。\n"
            "- 可以读取上下文、搜索资料、检查代码结构并提出少量澄清问题。\n"
            "- 默认不要写文件、改代码、执行实现性改动或启动长任务;用户明确要求执行时才切换。\n"
            "- 输出可执行计划,至少包含目标理解、约束/风险、步骤、验收标准和需要确认的点。"
        )
    elif preset == "codex.spec":
        body = (
            "当前工作流: codex.spec / Spec 模式。\n"
            "- 目标是沉淀规格,不是马上实现。默认不要改代码或写入项目文件。\n"
            "- 输出目标、非目标、用户故事/流程、接口或数据契约、边界条件、验收标准和开放问题。\n"
            "- 如果现有代码会影响规格,先读相关文件再写规格;不要凭空假设接口。"
        )
    elif preset == "codex.goal":
        body = (
            "当前工作流: codex.goal / Goal 模式。\n"
            "- 围绕 objective 持续推进,但单轮仍受 max_iterations、token 和成本预算约束。\n"
            "- 开始前拆成可审计 todo;每次推进后更新状态,保留可恢复上下文。\n"
            "- 完成前做 completion audit: 逐项核对原始目标、交付物、测试/验收和当前证据。"
        )
    elif preset == "audit.ultracode":
        body = (
            "当前工作流: audit.ultracode / 最高强度审查。\n"
            "- 不要单轮通读了事,做多代理并行深审。若具备 `run_orchestration` 技能,"
            "用它发起编排(agent_id 传一组不同视角的角色,如 [critic, explorer, "
            "researcher];n=5、rounds=2~3、verify=true、synthesize=true),让发现经过 "
            "收集→去重→投票核验→综合;不具备该技能时,改为按模块多轮交叉审查。\n"
            "- 扇出深度由部署预算自动伸缩,你只负责发起编排,不要自行抬高 max_spawns。\n"
            "- 汇总按 严重度 + 证据(文件:行)+ 修复顺序 归并;核验未通过的发现标注为存疑。"
        )
    else:
        return ""
    return f"<workflow-preset>\n{body}\n</workflow-preset>"


def _build_personal_agent_mode_prompt(personal_mode: str | None) -> str:
    """Operating contract for a PERSONAL-space work mode (no bound user project).

    The code/project modes (:func:`_build_code_agent_mode_prompt`) only apply once
    a workspace directory is bound. Personal space is the agent's own
    conversational/work space — it still has a sandbox to write in, so it can carry
    its own modes. Only "build" carries steering here; "general" is the default
    (no contract) and "research" is handled upstream by the existing deep-research
    reasoning mode, not by this prompt.
    """
    mode = (personal_mode or "").strip().lower()
    if mode not in {"build", "builder", "make", "maker"}:
        return ""
    body = (
        "当前空间: 个人工作空间(未绑定用户项目目录),你有自己的沙箱工作目录可写。\n"
        "构建模式 / maker:\n"
        "- 主动产出可运行的成果,而不是只给方案:需要时在工作目录里创建文件、写代码、跑起来验证。\n"
        "- 每完成一个可运行切片就自测一次;优先最小可运行版本,不要堆到最后才验证。\n"
        "- 收工用 Final Answer 说明:产出了什么、怎么运行或获取(关键文件 / 命令 / 导出方式)、残余风险。"
    )
    return f"<personal-agent-mode>\n{body}\n</personal-agent-mode>"


def _build_project_signals_prompt(project_signals: Any) -> str:
    if not isinstance(project_signals, dict):
        return ""
    signals = project_signals.get("signals")
    if not isinstance(signals, dict):
        signals = project_signals

    def _list(key: str, limit: int = 8) -> list[str]:
        value = signals.get(key)
        if not isinstance(value, list):
            return []
        return [str(item) for item in value[:limit] if isinstance(item, str) and item.strip()]

    def _commands(limit: int = 8) -> list[str]:
        value = signals.get("commands")
        if not isinstance(value, list):
            return []
        formatted: list[str] = []
        for item in value[:limit]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip()
            command = str(item.get("command") or "").strip()
            source = str(item.get("source") or "").strip()
            if not kind or not command:
                continue
            suffix = f" ({source[:80]})" if source else ""
            formatted.append(f"[{kind}] {command}{suffix}")
        return formatted

    lines: list[str] = []
    recommended = project_signals.get("recommended_mode")
    if isinstance(recommended, str) and recommended.strip():
        confidence = project_signals.get("confidence")
        suffix = (
            f" ({round(float(confidence) * 100)}%)" if isinstance(confidence, (int, float)) else ""
        )
        lines.append(f"- 推荐子模式: {recommended.strip()}{suffix}")
    reason = project_signals.get("reason")
    if isinstance(reason, str) and reason.strip():
        lines.append(f"- 检测依据: {reason.strip()[:240]}")

    file_count = signals.get("file_count")
    if isinstance(file_count, int):
        lines.append(f"- 文件数量: {file_count}")
    git_commits = signals.get("git_commits")
    if isinstance(git_commits, int) and git_commits > 0:
        lines.append(f"- Git 提交数: {git_commits}")
    if signals.get("has_readme") is True:
        lines.append("- README: 已发现")

    manifests = _list("manifests")
    if manifests:
        lines.append("- 项目清单/技术栈信号: " + ", ".join(manifests))
    lock_files = _list("lock_files")
    if lock_files:
        lines.append("- 锁文件/包管理器信号: " + ", ".join(lock_files))
    structure_dirs = _list("structure_dirs", limit=12)
    if structure_dirs:
        lines.append("- 关键目录: " + ", ".join(structure_dirs))
    commands = _commands()
    if commands:
        lines.append("- 候选验证命令: " + "; ".join(commands))

    if not lines:
        return ""
    if commands:
        lines.append(
            "- 验证建议: 修改后优先从候选命令里选择最相关的一条执行;"
            "如果候选命令不适用,说明原因并选择更窄的验证。"
        )
    else:
        lines.append(
            "- 验证建议: 优先根据上述清单和锁文件选择项目自带 lint/typecheck/test/build 命令;"
            "不确定时先读取 package/pyproject/README 等清单文件再执行。"
        )
    return "<project-signals>\n" + "\n".join(lines) + "\n</project-signals>"


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


# ── User-message content assembly (moved from react_loop.py) ──────


def _build_user_message_content(
    text: str,
    attachments: Any,
) -> Any:
    """Construct the user-message ``content`` payload.

    When the request carries one or more image attachments with a usable
    URL (data: URL preferred, hosted https URL acceptable), we emit a
    list of OpenAI-shaped blocks::

        [
          {"type": "text", "text": ...},
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
          ...
        ]

    Vision-capable routers (anthropic / openai / gemini / molili) all
    accept this shape. Non-vision routers fall back to plain text via
    their own input filtering, so we don't need to gate by model here.

    When no image attachments are present, returns plain ``text``
    unchanged so we don't break callers that assume a string.
    """
    text = (text or "").strip()
    image_blocks = _image_blocks_from_attachments(attachments)
    if not image_blocks:
        return text
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    blocks.extend(image_blocks)
    return blocks


def _image_blocks_from_attachments(attachments: Any) -> list[dict[str, Any]]:
    """Extract OpenAI-shaped image_url blocks from raw attachment dicts.

    Recognized shapes (any of these is enough):

    - ``data_url`` field with a ``data:image/...;base64,...`` string
    - ``url`` field that is itself a ``data:image/...`` URL
    - ``url`` field with ``mediaType`` / ``mime_type`` starting with
      ``image/`` (we trust the caller, no fetch)

    Filename-extension is a last-resort hint when no media type is set.
    """
    if not isinstance(attachments, list):
        return []
    blocks: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        url = ""
        candidate = item.get("data_url") or item.get("dataUrl")
        if isinstance(candidate, str) and candidate.startswith("data:image/"):
            url = candidate
        else:
            raw_url = item.get("url") or item.get("artifact_url")
            if (
                isinstance(raw_url, str)
                and raw_url.strip()
                and (raw_url.startswith("data:image/") or _looks_like_image_attachment(item))
            ):
                url = raw_url
        if not url:
            continue
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def _looks_like_image_attachment(item: dict[str, Any]) -> bool:
    """Heuristic: does this attachment look like an image?"""
    mt = item.get("mediaType") or item.get("media_type") or item.get("mime_type") or ""
    if isinstance(mt, str) and mt.lower().startswith("image/"):
        return True
    name = item.get("filename") or item.get("name") or ""
    if isinstance(name, str):
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in {"png", "jpg", "jpeg", "gif", "webp", "bmp"}:
            return True
    return False
