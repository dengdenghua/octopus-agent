"""Goal-intent and evidence-path analysis for ReAct guards.

Extracted from ``react_guards.py`` (Wave 3, cluster 1): the pure
"what did the user ask for / which files did we actually read"
helpers shared by the guard clusters and by react_convergence /
react_explicit_reads / react_prompt_assembly / react_public_updates.
Leaf module: depends only on re / react_parsing / react_types — must
never import react_guards.
"""

from __future__ import annotations

import re

from runtime.core.cerebrum.react_parsing import _parse_action
from runtime.core.cerebrum.react_types import ReActStep


def _inspection_goal_text(goal: str) -> str:
    """Remove negative read-only clauses before finding inspection intent."""
    lowered = (goal or "").lower()
    lowered = re.sub(r"\bread[- ]only\b", " ", lowered)
    lowered = re.sub(
        r"\b(?:do\s+not|don't|must\s+not|never)\b"
        r"[^.!;\n]{0,120}\b(?:files?|code|repo(?:sitory)?|workspace)\b",
        " ",
        lowered,
    )
    return re.sub(
        r"(?:不要|严禁|禁止|不得|不可|不允许)[^。.!！；;\n]{0,120}"
        r"(?:文件|代码|内容|工作区|仓库|项目)",
        " ",
        lowered,
    )


def _goal_requests_project_inspection(goal: str) -> bool:
    lowered = _inspection_goal_text(goal)
    if re.search(
        r"\b(?:list_cwd|read_file)\b|"
        r"\b(?:inspect|read|review|check|open|analy[sz]e)\b[^.!?\n]{0,48}"
        r"\b(?:files?|config(?:uration)?|project|repo(?:sitory)?|workspace|"
        r"codebase|source\s+code)\b|"
        r"(?:检查|查看|读取|分析|调研|审计|梳理|了解|评估|摸清|研究)"
        r"[^。.!！；;\n]{0,48}(?:当前项目|项目目录|本地仓库|工作区|代码库)|"
        r"(?:^|[\s'\"`(])[^\s'\"`()]+\."
        r"(?:py|ts|tsx|js|jsx|json|ya?ml|toml|md|css|html|go|rs)\b",
        lowered,
    ):
        return True
    return any(
        marker in lowered
        for marker in (
            "本地文件",
            "项目文件",
            "配置文件",
            "源代码",
            "源码",
        )
    )


def _goal_requests_code_mutation(goal: str) -> bool:
    """Whether the user asked code mode to change workspace state.

    This is intentionally keyed off explicit action verbs.  Code mode is
    also used for read-only reviews, so merely mentioning a file/repository
    must not force an edit.
    """

    lowered = _inspection_goal_text(goal)
    # A read-only request often names the forbidden action explicitly
    # ("do not modify files" / "不要修改任何文件"). Matching mutation verbs
    # before removing that negated clause turns analysis and research turns
    # into false implementation tasks and blocks their final report behind
    # the write-evidence guard.
    lowered = re.sub(
        r"\b(?:do\s+not|don't|must\s+not|never)\s+"
        r"(?:modify|change|edit|write|create|update|add|remove|delete|patch|fix|refactor)\b",
        " ",
        lowered,
    )
    lowered = re.sub(
        r"\bwithout\s+"
        r"(?:modifying|changing|editing|writing|creating|updating|adding|removing|deleting|patching|fixing|refactoring)\b",
        " ",
        lowered,
    )
    lowered = re.sub(
        r"(?:不要|无需|不需要|禁止|不得|不可|"
        r"不(?=修改|改动|更改|重命名|更新|创建|新增|添加|删除|写入|修复|构建|迁移|重构))\s*"
        r"(?:修改|改动|更改|重命名|更新|创建|新增|添加|删除|写入|修复|构建|迁移|重构)",
        " ",
        lowered,
    )
    # Progress narration is conversation output, not a workspace mutation.
    # Phrases such as “自然更新进展” previously matched the bare 更新 marker
    # and forced read-only analysis turns behind the implementation-write gate.
    lowered = re.sub(
        r"(?:自然|持续|及时|实时|定期)?\s*更新\s*(?:进展|进度|状态|过程|消息|说明)",
        " ",
        lowered,
    )
    lowered = re.sub(
        r"\b(?:update|post|share|provide)\s+(?:the\s+)?"
        r"(?:progress|status)(?:\s+updates?)?\b|"
        r"\b(?:progress|status)\s+updates?\b",
        " ",
        lowered,
    )
    # Match English actions as whole words. Tool/protocol identifiers are not
    # natural-language mutation requests: the old substring check treated the
    # ``write`` part of ``todo_write`` as a request to edit workspace files.
    english_mutation = re.search(
        r"\b(?:implement|change|modify|rename|update|create|add|remove|delete|"
        r"write|rewrite|overwrite|patch|fix|build|migrate|refactor)\b",
        lowered,
    )
    chinese_markers = (
        "实现",
        "修改",
        "改动",
        "更改",
        "重命名",
        "更新",
        "创建",
        "新增",
        "添加",
        "删除",
        "写入",
        "修复",
        "构建",
        "迁移",
        "重构",
    )
    return english_mutation is not None or any(marker in lowered for marker in chinese_markers)


def _explicitly_requested_tool_names(goal: str) -> set[str]:
    """Extract concrete tool calls the user explicitly required.

    This is deliberately narrower than general tool intent. It only captures
    snake_case identifiers attached to an imperative "call/use" verb, and it
    removes negated requests first so "不要调用 todo_write" never becomes a
    completion requirement.
    """

    text = str(goal or "")
    text = re.sub(
        r"(?:不要|无需|不需要|禁止|不得|不可|别)\s*(?:调用|使用)\s*"
        r"[`「『]?([a-z][a-z0-9_]*_[a-z0-9_]+)[`」』]?",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:do\s+not|don't|never)\s+(?:call|use|invoke)\s+(?:the\s+)?"
        r"[`'\"]?([a-z][a-z0-9_]*_[a-z0-9_]+)[`'\"]?",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    names: set[str] = set()
    patterns = (
        r"(?:调用|使用)\s*[`「『]?([a-z][a-z0-9_]*_[a-z0-9_]+)[`」』]?",
        r"\b(?:call|use|invoke)\s+(?:the\s+)?"
        r"[`'\"]?([a-z][a-z0-9_]*_[a-z0-9_]+)[`'\"]?",
    )
    for pattern in patterns:
        names.update(
            match.group(1).lower() for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        )
    return names


def _goal_requires_file_content(goal: str) -> bool:
    lowered = _inspection_goal_text(goal)
    return bool(
        re.search(
            r"\bread_file\b|\b(?:read|inspect|review|check|open|analy[sz]e)\b"
            r"[^.!?\n]{0,48}\b(?:files?|config(?:uration)?|source\s+code)\b|"
            r"(?:^|[\s'\"`(])[^\s'\"`()]+\."
            r"(?:py|ts|tsx|js|jsx|json|ya?ml|toml|md|css|html|go|rs)\b|"
            r"(?:检查|查看|读取|分析)[^。.!！；;\n]{0,48}"
            r"(?:文件|配置|源代码|源码)",
            lowered,
        )
        or any(
            marker in lowered for marker in ("本地文件", "项目文件", "配置文件", "源代码", "源码")
        )
    )


_EXPLICIT_SOURCE_PATH_RE = re.compile(
    r"(?<![\w.-])(?:\.{0,2}/)?(?:[A-Za-z0-9_@.-]+/)*"
    r"[A-Za-z0-9_@.-]+\."
    r"(?:py|tsx|ts|jsx|json|js|ya?ml|toml|md|css|html|go|rs)"
    r"(?::\d+(?::\d+)?)?",
    re.IGNORECASE,
)


def _normalize_evidence_path(value: str) -> str:
    path = str(value or "").strip().strip("`'\"()[]{}.,;，。；")
    path = re.sub(r":\d+(?::\d+)?$", "", path)
    while path.startswith("./"):
        path = path[2:]
    return path.replace("\\", "/").strip("/").lower()


def _explicit_source_paths(goal: str) -> list[str]:
    """Return the concrete source files the user explicitly named."""

    result: list[str] = []
    seen: set[str] = set()
    for match in _EXPLICIT_SOURCE_PATH_RE.finditer(str(goal or "")):
        path = _normalize_evidence_path(match.group(0))
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _path_evidence_matches(requested: str, observed: str) -> bool:
    requested_norm = _normalize_evidence_path(requested)
    observed_norm = _normalize_evidence_path(observed)
    if not requested_norm or not observed_norm:
        return False
    if "/" in requested_norm:
        return observed_norm == requested_norm or observed_norm.endswith("/" + requested_norm)
    return observed_norm.rsplit("/", 1)[-1] == requested_norm


def _successful_read_paths(steps: list[ReActStep]) -> set[str]:
    """Collect file paths backed by successful read-file receipts."""

    paths: set[str] = set()
    read_tools = {
        "read_file",
        "read_file_range",
        "read_files",
        "read_text_file",
        "bb_read",
    }
    for step in steps:
        actions = step.actions or ([step.action] if step.action else [])
        for index, raw_action in enumerate(actions):
            parsed = _parse_action(raw_action)
            if parsed is None:
                continue
            name, args = parsed
            if name.lower() not in read_tools:
                continue
            if index < len(step.action_results):
                succeeded = bool(step.action_results[index].get("ok"))
            else:
                observation = (step.observation or "").lower()
                succeeded = bool(observation.strip()) and not any(
                    marker in observation
                    for marker in (
                        "未执行观察",
                        "not executed",
                        "工具失败",
                        "工具执行异常",
                        '"error":',
                        "timed_out",
                    )
                )
            if not succeeded:
                continue
            raw_paths: list[str] = []
            for key in ("path", "file_path", "filepath", "file"):
                value = args.get(key)
                if isinstance(value, str):
                    raw_paths.append(value)
            values = args.get("paths") or args.get("files")
            if isinstance(values, list):
                raw_paths.extend(str(value) for value in values if isinstance(value, str))
            paths.update(
                normalized for value in raw_paths if (normalized := _normalize_evidence_path(value))
            )
    return paths


def _final_answer_requests_user_help(final_answer: str) -> bool:
    """Whether the final answer is asking the user to do something
    rather than reporting a result.

    The completion guards short-circuit when this returns True so a
    truly blocked agent (missing API key, needs human approval, etc.)
    can hand off cleanly. **The detection has to be conservative** —
    a research report that merely *mentions* "permission" or "token"
    must NOT count as a help request, otherwise the report ends
    prematurely the moment the model emits its first ``Final Answer:``.

    Strategy:
      * Inspect only the tail of the answer (last ~400 chars). Help
        requests live in the closing paragraph, not in body content
        of a long report.
      * Require a marker phrase that pairs an action verb with the
        ask, e.g. ``please confirm`` rather than the bare word
        ``confirm``. Single-word markers (``token``/``permission``)
        are too noisy in technical writing.
      * Or accept a short answer (< 300 chars) with the original
        looser markers — those really are short hand-off messages.
    """

    raw = (final_answer or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    tail = lowered[-400:]

    # Tight markers: action + dependency phrasing. These appear in
    # genuine "I need you to ..." sign-offs and almost never in
    # report prose.
    tight_markers = (
        "需要你",
        "请你",
        "需要用户",
        "用户协助",
        "用户帮忙",
        "无法继续",
        "需要确认",
        "请确认",
        "需要登录",
        "请登录",
        "请提供",
        "请补充",
        "需要您",
        "请您",
        "缺少 api",
        "缺少凭证",
        "缺少权限",
        "需要权限",
        "请授权",
        "需要授权",
        "没有权限",
        "等待批准",
        "等待确认",
        "need your",
        "please confirm",
        "please provide",
        "please grant",
        "please supply",
        "missing api key",
        "missing credential",
        "missing token",
        "permission denied",
        "access denied",
        "please log in",
        "please login",
        "blocked by",
    )
    if any(marker in tail for marker in tight_markers):
        return True

    # Short final → looser markers are still informative because the
    # agent isn't writing a report, just signing off. Threshold is
    # tuned so that a structured Chinese paragraph (which is denser
    # than English by character count) doesn't trip — a real
    # hand-off message is closer to one or two sentences.
    if len(raw) < 150:
        loose_markers = (
            "权限",
            "批准",
            "缺少",
            "api key",
            "credential",
            "blocked",
            "permission",
            "login",
            "token",
        )
        if any(marker in tail for marker in loose_markers):
            return True

    return False
