from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_PATHISH_RE = re.compile(
    r"([A-Za-z]:\\|/[\w.-]+|\.{1,2}/|[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|md|json|yaml|yml|css|html))"
)


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return tuple(out)


@dataclass(frozen=True)
class CapabilityActivation:
    labels: tuple[str, ...] = ()
    priority_skills: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()
    pinned_skills: tuple[str, ...] = ()
    pinned_plugins: tuple[str, ...] = ()
    pinned_agents: tuple[str, ...] = ()
    pinned_packs: tuple[str, ...] = ()
    pinned_surfaces: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.labels and self.priority_skills) or bool(
            self.pinned_skills
            or self.pinned_plugins
            or self.pinned_agents
            or self.pinned_packs
            or self.pinned_surfaces
        )

    def render_prompt(self) -> str:
        if not self.active:
            return ""
        sections: list[str] = []
        if self.labels and self.priority_skills:
            labels = ", ".join(self.labels)
            skills = ", ".join(f"`{name}`" for name in self.priority_skills[:16])
            sections.append(
                "<active-capability-router>\n"
                f"This turn likely needs these capability lanes: {labels}.\n"
                f"Prefer these skills first when they fit the next action: {skills}.\n"
                "Do not call tools just because they are listed here; use the smallest real tool path.\n"
                "For plugin, skill-pack, or workflow-shaped tasks, prefer "
                "`search_capabilities` / `query_capability` / `use_capability` "
                "before low-level child skills. If a listed skill is unfamiliar, "
                "call `query_skill(name=...)` before using it.\n"
                "When spawning subagents, pass explicit `skill_packs`, `skills`, or `plugins` in the delegation spec so workers get the same relevant capabilities.\n"
                "</active-capability-router>",
            )
        if (
            self.pinned_skills
            or self.pinned_plugins
            or self.pinned_agents
            or self.pinned_packs
            or self.pinned_surfaces
        ):
            pin_lines = ["<input-mentions>"]
            if self.pinned_skills:
                pin_lines.append(
                    "User pinned these skills via @skill: "
                    + ", ".join(f"`{n}`" for n in self.pinned_skills)
                    + ". Prefer them when they match the next concrete action.",
                )
            if self.pinned_packs:
                pin_lines.append(
                    "User pinned these skill packs via @pack: "
                    + ", ".join(f"`{n}`" for n in self.pinned_packs)
                    + ". Treat each pack as a bundled toolkit.",
                )
            if self.pinned_plugins:
                pin_lines.append(
                    "User pinned these plugins via @plugin: "
                    + ", ".join(f"`{n}`" for n in self.pinned_plugins)
                    + ". Treat this as an explicit routing request: use "
                    "`query_capability` / `use_capability` for the pinned plugin "
                    "before lower-level tools unless it is unavailable or clearly "
                    "irrelevant.",
                )
            if self.pinned_agents:
                pin_lines.append(
                    "User pinned these teammates via @agent: "
                    + ", ".join(f"`{n}`" for n in self.pinned_agents)
                    + ". When delegation fits, call them via `call_agent` "
                    "/ `call_agent_parallel` first.",
                )
            if self.pinned_surfaces:
                pin_lines.append(
                    "User invoked these runtime surfaces via @Surface: "
                    + ", ".join(f"`{n}`" for n in self.pinned_surfaces)
                    + ". Treat this as explicit permission and intent to use "
                    "that UI surface when it is relevant.",
                )
            pin_lines.append(
                "These pins are strong routing preferences. If a pinned "
                "capability cannot be used, say why before falling back.",
            )
            pin_lines.append("</input-mentions>")
            sections.append("\n".join(pin_lines))
        return "\n\n".join(sections)


_RULES: tuple[dict[str, Any], ...] = (
    {
        "label": "research",
        "modes": {"research", "deep", "deep_research"},
        "keywords": (
            "research", "market", "competitor", "compare", "survey",
            "latest", "source", "citation", "调研", "研究", "市场",
            "竞品", "赛道", "资料", "来源", "引用", "最新", "报告",
        ),
        "skills": (
            "todo_write", "search_capabilities", "use_capability",
            "web_search", "web_fetch", "fetch_url",
            "deep-research", "report-writing", "call_agent_parallel",
            "bb_write", "bb_read", "bb_keys",
        ),
    },
    {
        "label": "code",
        "modes": {"code"},
        "keywords": (
            "code", "bug", "fix", "implement", "test", "repo",
            "frontend", "backend", "server", "port", "restart",
            "代码", "修复", "实现", "测试", "前端", "后端",
            "启动", "重启", "端口", "文件", "报错", "接口",
        ),
        "skills": (
            "todo_write", "search_capabilities", "use_capability",
            "list_cwd", "glob_files", "grep_text",
            "read_file", "read_file_range", "code_search",
            "code_find_symbol", "code_analyze", "edit_file",
            "multi_edit_file", "write_text_file", "exec_shell",
            "git_status", "git_diff",
        ),
    },
    {
        "label": "capability",
        "modes": {"plugin", "capability", "skill_pack"},
        "keywords": (
            "plugin", "plugins", "skill pack", "skill-pack", "capability",
            "workflow", "toolbox", "mcp", "connector",
            "插件", "技能包", "能力包", "能力", "工作流", "工具箱",
            "连接器",
        ),
        "skills": (
            "search_capabilities", "query_capability", "use_capability",
            "query_skill",
        ),
    },
    {
        "label": "browser-ui",
        "modes": {"browser", "chrome", "ui"},
        "keywords": (
            "browser", "localhost", "127.0.0.1", "screenshot",
            "click", "ux", "ui", "playwright", "regression",
            "浏览器", "页面", "点击", "截图", "回归", "交互",
            "对齐", "侧边栏", "按钮", "输入框", "流式",
        ),
        "skills": (
            "live_browser_state", "live_browser_current_url",
            "live_browser_navigate", "live_browser_extract",
            "live_browser_find", "live_browser_click", "live_browser_type",
            "live_browser_wait", "live_browser_scroll",
            "live_browser_screenshot", "browser_state", "browser_navigate",
            "browser_get", "browser_extract", "browser_screenshot",
            "browser_click",
            "screen_capture", "screen_info",
        ),
    },
    {
        "label": "delegation",
        "modes": {"swarm"},
        "keywords": (
            "subagent", "sub-agent", "parallel", "delegate", "worker",
            "fan-out", "swarm", "子agent", "子 agent", "并行",
            "派生", "召唤", "分工", "专家", "集群", "多路",
        ),
        "skills": (
            "call_agent_parallel", "bb_write", "bb_read", "bb_keys",
            "query_skill",
        ),
    },
    {
        "label": "files",
        "modes": {"code"},
        "keywords": (
            "file", "folder", "diff", "artifact", "write", "edit",
            "文件", "目录", "产物", "生成", "编辑", "保存",
            "撤销", "审核", "diff",
        ),
        "skills": (
            "list_cwd", "glob_files", "read_file", "write_text_file",
            "edit_file", "multi_edit_file", "append_text_file", "git_diff",
        ),
    },
    {
        "label": "memory",
        "modes": {"memory"},
        "keywords": (
            "remember", "memory", "preference", "profile", "template",
            "记住", "记忆", "偏好", "以后", "模板", "技能库",
        ),
        "skills": (
            "recall", "remember", "note_user", "list_learned_skills",
            "apply_skill", "learn_skill_from_text",
        ),
    },
)


def _context_text(goal: str, user_context: dict[str, Any] | None) -> tuple[str, str]:
    user_context = user_context or {}
    pieces = [str(goal or "")]
    mode = str(user_context.get("mode") or user_context.get("capability_mode") or "").lower()
    history = user_context.get("conversation_messages")
    if isinstance(history, list) and history:
        for item in history[-3:]:
            if isinstance(item, dict) and item.get("role") == "user":
                content = item.get("content")
                if isinstance(content, str):
                    pieces.append(content)
    return "\n".join(pieces).lower(), mode


def _skill_available(registry: Any, name: str) -> bool:
    if registry is None:
        return True
    try:
        if not registry.has(name):
            return False
        return bool(registry.is_enabled(name))
    except (AttributeError, TypeError, ValueError, KeyError):
        return True


def activate_capabilities(
    goal: str = "",
    *,
    user_context: dict[str, Any] | None = None,
    registry: Any = None,
) -> CapabilityActivation:
    text, mode = _context_text(goal, user_context)
    labels: list[str] = []
    skills: list[str] = []
    terms: list[str] = []

    # Parse @plugin/@skill/@agent/@pack mentions from the goal text early
    # so we can boost pinned skills into the priority list and pass the
    # full mention payload back to the caller for delegation routing.
    pinned_skills: tuple[str, ...] = ()
    pinned_plugins: tuple[str, ...] = ()
    pinned_agents: tuple[str, ...] = ()
    pinned_packs: tuple[str, ...] = ()
    pinned_surfaces: tuple[str, ...] = ()
    pack_expanded_skills: list[str] = []
    try:
        from runtime.core.cerebrum.input_mentions import (
            parse_input_mentions,
        )
        mentions = parse_input_mentions(goal)
        pinned_skills = mentions.skills
        pinned_plugins = mentions.plugins
        pinned_agents = mentions.agents
        pinned_packs = mentions.packs
        pinned_surfaces = mentions.surfaces
    except (ImportError, AttributeError):
        pass

    # Expand @pack mentions into their constituent skills using the
    # dynamic skill pack registry. Unknown pack names are silently
    # ignored — the prompt hint still tells the model the pack name.
    if pinned_packs:
        try:
            from runtime.execution.suckers.delegation_skills import (
                _DYNAMIC_SKILL_PACKS,
            )
            for pack_name in pinned_packs:
                pack_skills = _DYNAMIC_SKILL_PACKS.get(
                    pack_name.strip().lower(), (),
                )
                pack_expanded_skills.extend(pack_skills)
        except (ImportError, AttributeError):
            pass

    for rule in _RULES:
        mode_hit = bool(mode and mode in rule["modes"])
        keyword_hits = [kw for kw in rule["keywords"] if str(kw).lower() in text]
        if not mode_hit and not keyword_hits:
            continue
        labels.append(rule["label"])
        terms.extend(keyword_hits[:3] or ([mode] if mode_hit else []))
        skills.extend(rule["skills"])

    if _PATHISH_RE.search(text):
        labels.append("files")
        skills.extend((
            "list_cwd", "read_file", "write_text_file",
            "edit_file", "git_diff",
        ))

    if "chrome" in pinned_surfaces:
        labels.append("external-chrome")
        terms.append("@Chrome")
        leading_chrome_skills = (
            "browser_state",
            "browser_get",
            "browser_navigate",
            "browser_extract",
            "browser_find",
            "browser_click",
            "browser_type",
            "browser_wait",
            "browser_scroll",
            "browser_screenshot",
            "live_browser_state",
            "live_browser_current_url",
            "live_browser_extract",
            "live_browser_screenshot",
        )
        skills = [*leading_chrome_skills, *skills]

    elif "browser" in pinned_surfaces:
        labels.append("browser-ui")
        terms.append("@Browser")
        leading_browser_skills = (
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
            "browser_state",
            "browser_navigate",
            "browser_extract",
            "browser_screenshot",
        )
        skills = [*leading_browser_skills, *skills]

    # Pinned skills + pack-expanded skills always lead the priority list
    # (they're an explicit user signal, stronger than keyword inference).
    # Filter through _skill_available so we don't claim a skill that
    # isn't installed.
    leading: list[str] = []
    if pinned_skills:
        leading.extend(
            name for name in pinned_skills if _skill_available(registry, name)
        )
    if pack_expanded_skills:
        leading.extend(
            name for name in pack_expanded_skills
            if _skill_available(registry, name)
        )
    if leading:
        skills = [*leading, *skills]
        if "pinned" not in labels:
            labels.append("pinned")

    skills = [
        name for name in _dedupe(skills)
        if _skill_available(registry, name)
    ]
    if skills:
        for name in (
            "search_capabilities",
            "query_capability",
            "use_capability",
            "search_skills",
            "query_skill",
        ):
            if _skill_available(registry, name):
                skills.append(name)

    return CapabilityActivation(
        labels=_dedupe(labels),
        priority_skills=_dedupe(skills),
        matched_terms=_dedupe(terms),
        pinned_skills=pinned_skills,
        pinned_plugins=pinned_plugins,
        pinned_agents=pinned_agents,
        pinned_packs=pinned_packs,
        pinned_surfaces=pinned_surfaces,
    )


def order_skill_names(
    names: Iterable[str],
    *,
    activation: CapabilityActivation | None = None,
    goal: str = "",
    user_context: dict[str, Any] | None = None,
    registry: Any = None,
) -> list[str]:
    original = _dedupe(names)
    if activation is None:
        activation = activate_capabilities(
            goal,
            user_context=user_context,
            registry=registry,
        )
    if not activation.active:
        return list(original)

    available = set(original)
    pinned_plugin_actions: list[str] = []
    if activation.pinned_plugins and registry is not None:
        wanted_sources = tuple(
            f"plugin://{plugin_id}/"
            for plugin_id in activation.pinned_plugins
            if plugin_id
        )
        for name in original:
            try:
                source = str(getattr(registry.get(name), "trusted_source", "") or "")
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
            if source.startswith(wanted_sources):
                pinned_plugin_actions.append(name)
    anchors = (
        "search_capabilities",
        "query_capability",
        "use_capability",
        "todo_write",
        "search_skills",
        "query_skill",
    )
    front = [
        name for name in (*anchors, *pinned_plugin_actions, *activation.priority_skills)
        if name in available
    ]
    ordered_front = _dedupe(front)
    front_set = set(ordered_front)
    return [*ordered_front, *(name for name in original if name not in front_set)]
