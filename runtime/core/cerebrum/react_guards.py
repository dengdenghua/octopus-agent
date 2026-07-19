"""ReAct trajectory guards: post-step / pre-Final-Answer quality gates.

╔══════════════════════════════════════════════════════════════════════════╗
║ react_guards.py · navigation map (2762 lines, ~80 guards).               ║
║                                                                          ║
║ Every guard takes a ``GuardContext`` (steps + final_answer + flags) and  ║
║ returns either ``None`` (let the Final Answer through) or a message      ║
║ string explaining why the model must keep working. The guard registry    ║
║ at the bottom (``GuardSpec`` + ``evaluate_guards``) wires named guards   ║
║ to the predicates above and applies user-controlled disables.            ║
║                                                                          ║
║   §1  Help-request / no-tool-claim detectors        ~L63                 ║
║   §2  Code-mode completion gates                    ~L242                ║
║   §3  Todo-protocol gate                            ~L440                ║
║   §4  Unverified-write follow-up gate               ~L619                ║
║   §5  Language-specific verification gate           ~L723                ║
║   §6  Path-policy verification gate                 ~L816                ║
║   §7  New-public-symbol-without-test gate           ~L878                ║
║   §8  Signature-changed-without-typecheck gate      ~L936                ║
║   §9  Wire-schema-without-compat-test gate          ~L989                ║
║   §10 Third-party-import-without-dep-manifest gate  ~L1033               ║
║   §11 False-verification-claim gate                 ~L1082               ║
║   §12 Commented-out-as-fix gate                     ~L1117               ║
║   §13 Broad-except suppression gate                 ~L1158               ║
║   §14 Frontend-outside-tsconfig gate                ~L1200               ║
║   §15 Oversized-edit gate                           ~L1258               ║
║   §16 Secret-in-payload gate                        ~L1313               ║
║   §17 Destructive-call gate                         ~L1377               ║
║   §18 Sleep-in-production gate                      ~L1441               ║
║   §19 Full-file-rewrite gate                        ~L1499               ║
║   §20 Weak-test-assertion gate                      ~L1563               ║
║   §21 Print-in-production gate                      ~L1664               ║
║   §22 Hardcoded-personal-path gate                  ~L1717               ║
║   §23 Mock-only-test gate                           ~L1773               ║
║   §24 Undocumented-skip gate                        ~L1832               ║
║   §25 Deleted-test gate                             ~L1885               ║
║   §26 Generic-test-name gate                        ~L1944               ║
║   §27 No-assertion-test gate                        ~L2003               ║
║   §28 Async-without-await gate                      ~L2061               ║
║   §29 Exception-swallow-via-log gate                ~L2121               ║
║   §30 Long-function gate                            ~L2175               ║
║   §31 Dynamic exec / eval gate                      ~L2235               ║
║   §32 Shell injection gate                          ~L2292               ║
║   §33 Unsafe deserialization gate                   ~L2346               ║
║   §34 Network-in-loop gate                          ~L2399               ║
║   §35 Repeated-literal gate                         ~L2451               ║
║   §36 Magic-number gate                             ~L2509               ║
║   §37 GuardContext + GuardSpec + evaluate_guards    ~L2573               ║
║                                                                          ║
║ Each guard has a paired ``_trajectory_*_hits(steps)`` predicate above    ║
║ (in this file) and a ``_step_introduces_*`` detector in react_parsing.   ║
║ Tests in tests/test_react_guards_*.py exercise both layers directly.    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from runtime.core.cerebrum.react_parsing import (
    _TEST_FUNC_RE,
    _detect_destructive_calls_in_payload,
    _detect_dynamic_exec_in_payload,
    _detect_no_assertion_tests_in_payload,
    _detect_secrets_in_payload,
    _detect_shell_injection_in_payload,
    _detect_unsafe_deser_in_payload,
    _detect_weak_tests_in_payload,
    _extract_step_payloads,
    _final_answer_claims_verification,
    _has_code_verification,
    _has_code_write,
    _has_language_specific_verification,
    _has_successful_verification_observation,
    _has_test_write,
    _has_wire_contract_test_write,
    _is_code_write_step,
    _is_test_path,
    _latest_todo_items,
    _latest_verification_observation_is_red,
    _parse_action,
    _path_language,
    _payload_has_ambiguous_inflight_leader_election,
    _payload_has_destructive_waiter_result_pop,
    _payload_has_inflight_identity_comparison,
    _payload_has_loader_barrier_deadlock,
    _payload_has_stale_immutable_waiter_snapshot,
    _payload_has_terminal_pending_entry_leak,
    _step_changed_public_signature,
    _step_command_text,
    _step_deleted_test_functions,
    _step_edits_frontend_outside_tsconfig,
    _step_edits_wire_schema,
    _step_introduces_async_without_await,
    _step_introduces_broad_except_suppression,
    _step_introduces_destructive_call,
    _step_introduces_generic_test_name,
    _step_introduces_hardcoded_path,
    _step_introduces_log_swallow,
    _step_introduces_long_function,
    _step_introduces_mock_only_test,
    _step_introduces_no_assertion_test,
    _step_introduces_print,
    _step_introduces_python_public_symbol,
    _step_introduces_secret,
    _step_introduces_sleep,
    _step_introduces_third_party_imports,
    _step_introduces_undocumented_skip,
    _step_introduces_weak_test,
    _step_is_full_file_rewrite_attempt,
    _step_is_oversized_edit,
    _step_is_surgical_edit_on,
    _step_replaced_code_with_comment,
    _step_writes_dep_manifest,
)
from runtime.core.cerebrum.react_types import ReActStep
from runtime.core.cerebrum.verification_policy import (
    classify_path,
    command_satisfies_requirement,
    summarize_requirements,
    verification_requirements_for_paths,
)


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
    markers = (
        "implement",
        "change",
        "modify",
        "rename",
        "update",
        "create",
        "add ",
        "remove",
        "delete",
        "write",
        "patch",
        "fix",
        "build",
        "migrate",
        "refactor",
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
    return any(marker in lowered for marker in markers)


def _final_answer_claims_no_tool_access(final_answer: str) -> bool:
    lowered = (final_answer or "").lower()
    denial_markers = (
        "no tool",
        "no available",
        "not available",
        "cannot access",
        "can't access",
        "cannot read",
        "can't read",
        "unable to access",
        "unable to read",
        "cannot execute",
        "can't execute",
        "do not have access",
        "don't have access",
        "do not have available",
        "don't have available",
        "not have access",
        "没有可用",
        "无可用",
        "没有工具",
        "无法访问",
        "不能访问",
        "无法读取",
        "不能读取",
        "无法执行",
        "不能执行",
        "不能实际执行",
    )
    tool_markers = (
        "tool",
        "list_cwd",
        "read_file",
        "file",
        "workspace",
        "project",
        "工具",
        "文件",
        "项目",
    )
    return any(marker in lowered for marker in denial_markers) and any(
        marker in lowered for marker in tool_markers
    )


def _has_real_react_action(steps: list[ReActStep]) -> bool:
    for step in steps:
        action = (step.action or "").strip().lower()
        if action and action not in {"none", "n/a", "na"}:
            return True
    return False


def _has_successful_tool_observation(
    steps: list[ReActStep],
    *,
    tool_name: str | None = None,
) -> bool:
    for step in steps:
        action = (step.action or "").strip().lower()
        if not action or action in {"none", "n/a", "na"}:
            continue
        parsed = _parse_action(step.action)
        if tool_name is not None and (parsed is None or parsed[0] != tool_name):
            continue
        observation = (step.observation or "").strip()
        if not observation or observation == "N/A":
            continue
        lowered = observation.lower()
        if (
            "未执行观察" in observation
            or "not executed" in lowered
            or "tool-availability guard" in lowered
            or "工具失败" in observation
            or "工具执行异常" in observation
        ):
            continue
        return True
    return False


def _has_successful_code_write(steps: list[ReActStep]) -> bool:
    """Return True only for a write tool with a successful execution receipt."""

    for step in steps:
        if not _is_code_write_step(step):
            continue
        if step.action_results:
            if any(result.get("ok") is True for result in step.action_results):
                return True
            continue
        # Older/replayed trajectories predate action receipts.  Preserve
        # compatibility, but still require a non-error observation.
        if _has_successful_tool_observation([step]):
            return True
    return False


def _code_mode_missing_write_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    goal: str,
) -> str | None:
    """Reject an implementation final when no real workspace write succeeded."""

    if not _goal_requests_code_mutation(goal):
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if _has_successful_code_write(steps):
        return None
    return (
        "Code mode cannot finish this implementation task yet: no successful "
        "file write/edit execution is recorded. Plans, reasoning, todo status, "
        "and remembered results are not workspace changes. Inspect the supplied "
        "workspace, call a real write/edit tool for the requested change, read "
        "the changed files back, and then run an appropriate verifier."
    )


def _final_answer_claims_tool_was_not_executed(final_answer: str) -> bool:
    lowered = (final_answer or "").lower()
    markers = (
        "not actually executed",
        "was not executed",
        "wasn't executed",
        "only recorded",
        "merely recorded",
        "no real tool",
        "no actual tool",
        "no verifiable",
        "not verifiable",
        "未实际执行",
        "没有实际执行",
        "没有真正执行",
        "只是被记录",
        "仅被记录",
        "没有真实执行",
        "没有可验证",
    )
    return any(marker in lowered for marker in markers)


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
                normalized
                for value in raw_paths
                if (normalized := _normalize_evidence_path(value))
            )
    return paths


def _code_mode_missing_inspection_tool_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    goal: str,
    file_tools_visible: bool,
    grounded_source_paths: frozenset[str] | set[str] = frozenset(),
) -> str | None:
    """Reject project-inspection finals that did not use file evidence."""
    if not file_tools_visible:
        return None
    if not _goal_requests_project_inspection(goal):
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    requested_paths = _explicit_source_paths(goal)
    if requested_paths:
        observed_paths = {
            _normalize_evidence_path(path)
            for path in grounded_source_paths
            if _normalize_evidence_path(path)
        }
        observed_paths.update(_successful_read_paths(steps))
        missing_paths = [
            path
            for path in requested_paths
            if not any(_path_evidence_matches(path, observed) for observed in observed_paths)
        ]
        if missing_paths:
            return (
                "Code mode cannot finish this project-inspection task yet: "
                "the user explicitly named source files that are not covered "
                "by successful read_file evidence or exact source grounding: "
                + ", ".join(missing_paths)
                + ". Read every missing file before answering, then base the "
                "comparison only on those observations."
            )
        return None
    if not _has_successful_tool_observation(steps):
        return (
            "Code mode cannot finish this project-inspection task yet: no "
            "successful file tool observation is recorded. Call "
            'list_cwd({"path":"."}) first, then read_file on the smallest '
            "relevant file set."
        )
    if _goal_requires_file_content(goal) and not _has_successful_tool_observation(
        steps,
        tool_name="read_file",
    ):
        return (
            "Code mode cannot finish this project-inspection task yet: the "
            "request asks for file/config evidence, but no successful "
            "read_file observation is recorded. Read at least one relevant "
            "file before producing the report."
        )
    return None


_SOURCE_FRAGMENT_ONLY_RE = re.compile(
    r"^(?:"
    r"(?:export\s+)?(?:const|let|var|type)\s+[A-Za-z_$][\w$]*\s*(?::[^=]+)?=.+"
    r"|[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\s*(?::[^=]+)?=.+"
    r"|(?:async\s+)?def\s+[A-Za-z_]\w*\s*\([^\n]*\)\s*(?:->[^:]+)?\s*:"
    r"|(?:export\s+)?(?:interface|class|type)\s+[A-Za-z_$][\w$]*(?:\s*[={].*)?"
    r"|return\s+.+"
    r")$",
    re.IGNORECASE,
)


def _code_mode_inspection_answer_fragment_guard(
    final_answer: str,
    *,
    goal: str,
    file_tools_visible: bool,
) -> str | None:
    """Reject a raw source line masquerading as an inspection report.

    Read-only code analysis often ends immediately after a large file result.
    Weak providers occasionally echo the last visible declaration (for
    example ``str = ""``) as plain prose.  The evidence gate proves the files
    were read, but not that the model actually answered the question.  Keep
    genuine concise conclusions valid; only source-shaped, explanation-free
    fragments are rejected.
    """

    if not file_tools_visible or not _goal_requests_project_inspection(goal):
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    visible = str(final_answer or "").strip()
    visible = re.sub(r"^```[A-Za-z0-9_+-]*\s*|\s*```$", "", visible).strip()
    visible = visible.strip("`").strip().rstrip(";")
    if not visible or "\n" in visible or len(visible) > 180:
        return None
    if not _SOURCE_FRAGMENT_ONLY_RE.fullmatch(visible):
        return None
    return (
        "Code mode cannot finish this project-inspection task with a bare source-code "
        "fragment. Explain what the observed declaration means and answer the user's "
        "actual comparison or architecture question using the completed read evidence."
    )


def _incomplete_final_answer_guard(final_answer: str) -> str | None:
    """Reject placeholder/preparatory prose presented as a terminal answer."""

    raw = str(final_answer or "").strip()
    visible = re.sub(r"</?[a-z_][^>]*>", " ", raw, flags=re.IGNORECASE)
    visible = re.sub(r"\s+", " ", visible).strip()
    if not visible:
        return (
            "The proposed Final Answer is empty or only contains an internal "
            "control marker. Produce the actual user-facing result now."
        )
    preparatory_start = re.match(
        r"^(?:我(?:会|将|先|接下来)|接下来|下一步|先来|准备|"
        r"let me|i(?:'ll| will| first)|next[,：:]?)",
        visible,
        re.IGNORECASE,
    )
    evidence_action = re.search(
        r"\b(?:grep|read|inspect|check|verify|search|open)\b|"
        r"(?:核对|检查|读取|再读|查看|搜索|检索|调研|打开|确认|探清|定位|查找)"
        r"(?:[^。.!！；;\n]{0,16})",
        visible,
        re.IGNORECASE,
    )
    result_signal = re.search(
        r"(?:结论|结果|区别|差异|一致|不同|表明|因此|所以|答案)|"
        r"\b(?:result|conclusion|difference|same|therefore|because|answer)\b",
        visible,
        re.IGNORECASE,
    )
    negated_completion = re.search(
        r"(?:还|尚|仍)?(?:没有|未|没能)(?:给出|得到|形成|完成|确认|核对)?"
        r"[^。.!！；;\n]{0,24}(?:结论|结果|答案|比较|差异)|"
        r"\b(?:not\s+yet|no\s+(?:result|conclusion|answer)\s+yet|"
        r"have\s+not\s+(?:finished|completed|verified|checked))\b",
        visible,
        re.IGNORECASE,
    )
    future_action = re.search(
        r"(?:^|[。.!！；;]\s*)(?:我)?(?:会|将|先|接下来|下一步|准备)|"
        r"(?:我)?先[^。.!！；;\n]{0,32}(?:再读|读取|查看|核对|检查|探清|定位|查找|搜索)|"
        r"\b(?:i(?:'ll| will)|let me|next)\b",
        visible,
        re.IGNORECASE,
    )
    failed_attempt = re.search(
        r"(?:失败|路径不对|未找到|找不到|无法读取|没有读到)|"
        r"\b(?:failed|not found|could not read|unable to read)\b",
        visible,
        re.IGNORECASE,
    )
    if (
        evidence_action
        and (preparatory_start or future_action)
        and (failed_attempt or negated_completion or not result_signal)
    ):
        return (
            "The proposed Final Answer only announces a future inspection or "
            "search. It is not a completed answer. Execute the stated read/search "
            "action, use its observation, and then answer the user's question "
            "with concrete findings."
        )
    return None


def _code_mode_false_no_tool_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    goal: str,
    tools_active: bool,
) -> str | None:
    """Reject code-mode finals that hallucinate missing file tools."""
    if not tools_active:
        return None
    if not _goal_requests_project_inspection(goal):
        return None
    if _has_real_react_action(steps):
        return None
    if not _final_answer_claims_no_tool_access(final_answer):
        return None
    return (
        "Tools are available in this ReAct session. Do not claim that "
        "project/file tools are unavailable before trying a listed tool. "
        'For this code-mode inspection task, call list_cwd({"path":"."}) '
        "first, then read_file on the smallest relevant file set. If a "
        "specific tool call fails, report that concrete failure."
    )


def _code_mode_false_tool_result_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    tools_active: bool,
) -> str | None:
    """Reject finals that deny a successful real tool observation."""
    if not tools_active:
        return None
    if not _has_successful_tool_observation(steps):
        return None
    if not (
        _final_answer_claims_tool_was_not_executed(final_answer)
        or _final_answer_claims_no_tool_access(final_answer)
    ):
        return None
    return (
        "A real tool execution already succeeded in this ReAct session. "
        "Use the Observation data as evidence; do not claim the action was "
        "only recorded, not actually executed, unavailable, or inaccessible. "
        "Continue the task with additional read-only tools or produce a report "
        "grounded in the successful observations."
    )


# ── Research / chat citation grounding ────────────────────────
# Non-code turns otherwise reach Final Answer with only the security
# cluster gating them. The check that pays off with the fewest false
# positives is a fabricated citation: if the turn actually fetched
# external content and the answer presents a markdown link ``[t](url)``
# whose URL never appeared in any observation, the model is citing a
# source it never consulted — a real, serious research failure.
# Deliberately narrow: only markdown-link citations (not bare URL
# mentions), only when a fetch/search/browser tool actually ran (so there
# is ground truth), and the nudge offers a clean escape (drop the link) so
# a rare false positive can't wedge the loop.
_MD_CITATION_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_FETCH_TOOL_HINTS = (
    "search",
    "fetch",
    "browse",
    "browser",
    "web",
    "retrieve",
    "scrape",
    "wiki",
    "crawl",
)


def _turn_fetched_external_content(steps: list[ReActStep]) -> tuple[bool, str]:
    """Return ``(a fetch/search/browser tool ran, all observation text)``."""
    fetched = False
    blobs: list[str] = []
    for step in steps:
        names = list(step.actions) if step.actions else ([step.action] if step.action else [])
        for res in step.action_results:
            tool = res.get("tool_name")
            if isinstance(tool, str):
                names.append(tool)
            obs = res.get("observation")
            if isinstance(obs, str):
                blobs.append(obs)
        for name in names:
            if any(hint in str(name).lower() for hint in _FETCH_TOOL_HINTS):
                fetched = True
        if step.observation:
            blobs.append(step.observation)
    return fetched, "\n".join(blobs)


def _fabricated_citation_guard(steps: list[ReActStep], final_answer: str) -> str | None:
    """Reject a research/chat final that cites source links it never fetched."""
    cited = _MD_CITATION_RE.findall(final_answer or "")
    if not cited:
        return None
    fetched, observations = _turn_fetched_external_content(steps)
    if not fetched:
        # No research happened this turn — any links are the model's own
        # knowledge, not sources claimed from this turn. Don't police them.
        return None
    seen = observations.lower()
    fabricated = [u for u in cited if u.rstrip("/").lower() not in seen and u.lower() not in seen]
    if not fabricated:
        return None
    return (
        f"Your answer cites {len(fabricated)} source link(s) that never "
        f"appeared in this turn's tool results (e.g. {fabricated[0]}). Do not "
        "present a URL as a source unless you actually fetched it. Either "
        "fetch/verify the link now, cite only URLs that appear in your "
        "search/fetch observations, or drop the link and state the point as "
        "your own reasoning."
    )


def _code_mode_completion_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    todo_protocol_required: bool = True,
) -> str | None:
    """Reject premature code-mode Final Answer attempts."""
    if _final_answer_requests_user_help(final_answer):
        return None

    todos = _latest_todo_items(steps)
    if todo_protocol_required and not todos and len(steps) >= 3:
        return (
            "Code mode cannot finish yet: no todo_write checklist is recorded. "
            "Create a complete todo list, execute it, "
            "and only finish after all items are completed."
        )

    incomplete: list[str] = []
    for item in todos:
        status = str(item.get("status") or "").lower()
        if status != "completed":
            title = str(
                item.get("title")
                or item.get("content")
                or item.get("text")
                or item.get("task")
                or "untitled"
            )
            incomplete.append(title)
    if incomplete:
        preview = "; ".join(incomplete[:5])
        if len(incomplete) > 5:
            preview += f"; +{len(incomplete) - 5} more"
        return (
            "Code mode cannot finish yet: unfinished todos remain: "
            f"{preview}. Keep working, update todo_write, "
            "or explicitly ask the user for help if blocked."
        )

    completed_todo_text = "\n".join(
        str(item.get("title") or item.get("content") or item.get("text") or item.get("task") or "")
        for item in todos
        if str(item.get("status") or "").lower() == "completed"
    )
    claims_persistent_test_write = bool(
        re.search(
            r"(?:create|add|write|新增|创建|添加|编写|写)"
            r".{0,32}(?:tests?/|test_|tests?\b|测试文件|回归测试)",
            completed_todo_text,
            re.IGNORECASE,
        )
    )
    if claims_persistent_test_write and not _has_test_write(steps):
        return (
            "Code mode cannot finish yet: a completed todo claims that a "
            "persistent test/regression file was created, but no test-file "
            "write is recorded in the trajectory. Inline one-off checks do "
            "not satisfy that checklist item. Write the promised tests under "
            "the repository test directory, read them back, and run them."
        )

    if _has_code_write(steps) and not _has_code_verification(steps):
        return (
            "Code mode cannot finish yet: files were changed "
            "but no verification step is recorded. "
            "Run an appropriate test, typecheck, lint, compile, "
            "or clearly ask the user for help if verification is impossible."
        )

    return None


def _has_tool_work_after_latest_todo(steps: list[ReActStep]) -> bool:
    """Whether a real action happened after the latest checklist update."""

    for step in reversed(steps):
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        name, _args = parsed
        if name == "todo_write":
            return False
        if name.lower() not in {"none", "n/a", ""} and step.observation:
            return True
    return False


def _todo_protocol_completion_guard(
    steps: list[ReActStep],
    final_answer: str,
) -> str | None:
    """Reject finals that skip or stale the visible checklist protocol."""

    if _final_answer_requests_user_help(final_answer):
        return None

    todos = _latest_todo_items(steps)
    if not todos:
        return (
            "This task cannot finish yet: no todo_write checklist is recorded. "
            "Create a complete user-visible checklist before the final answer."
        )

    incomplete: list[str] = []
    for item in todos:
        status = str(item.get("status") or "").lower()
        if status != "completed":
            title = str(
                item.get("title")
                or item.get("content")
                or item.get("text")
                or item.get("task")
                or "untitled"
            )
            incomplete.append(title)
    if incomplete:
        preview = "; ".join(incomplete[:5])
        if len(incomplete) > 5:
            preview += f"; +{len(incomplete) - 5} more"
        return (
            "This task cannot finish yet: unfinished checklist items remain: "
            f"{preview}. Keep working, update todo_write, or ask the user for "
            "help if blocked."
        )

    if _has_tool_work_after_latest_todo(steps):
        return (
            "This task used tools after the latest todo_write update. Call "
            "todo_write again with the complete list marked accurately before "
            "the final answer."
        )

    return None


# ──────────────────────────────────────────────────────────────────
# In-flight guards — fire DURING the loop, not at Final Answer time.
# ──────────────────────────────────────────────────────────────────

# Phrases that suggest the model believes some unit of work just
# completed. Matched in the latest step's Thought / Observation
# heading. Triggers the "now update todo_write" reminder when the
# next action isn't already todo_write.
#
# Keep tight — false positives waste a turn nudging the model to call
# todo_write when the work isn't actually complete. Each entry should
# be unambiguously "I just finished a thing", not "I'm working on a
# thing".
_COMPLETION_PHRASE_RE = re.compile(
    r"(?:"
    # English: completion sentences
    r"\b(?:done|completed|finished|implemented|fixed|resolved)\b[^.\n]{0,40}"
    r"\b(?:successfully|now|the\s+(?:fix|change|edit|implementation))?|"
    r"\bthat'?s\s+(?:done|all|everything)\b|"
    r"\ball\s+(?:done|tests\s+pass|checks\s+pass)\b|"
    # Chinese: 完成 / 修好了 / 改好了 / 写好了 / 都搞定
    r"已[完成完成搞定修好改好写好]|"
    r"全部完成|都[完成搞定]|"
    r"[完修改写]好了|搞定了"
    r")",
    re.IGNORECASE,
)


def _looks_like_completion_phrase(text: str) -> bool:
    if not text:
        return False
    return bool(_COMPLETION_PHRASE_RE.search(text))


def _completion_phrase_without_todo_guard(
    steps: list[ReActStep],
    *,
    todo_protocol_required: bool,
) -> str | None:
    """Detect "I just finished X" claims that aren't immediately followed
    by a ``todo_write`` update.

    Fires DURING the loop (before the next action runs), not at Final
    Answer time. Goal: catch the model when it narrates a completion
    in its Thought but its actual next planned action is something
    other than updating the visible checklist. Quietly returns None
    when the next action IS ``todo_write`` — that's the desired
    behaviour and shouldn't generate noise.

    ``todo_protocol_required`` lets the loop turn this off for
    free-form chat where checklists aren't expected.
    """
    if not todo_protocol_required or not steps:
        return None
    todos = _latest_todo_items(steps)
    if not todos:
        # Caller's job to surface "no todo_write yet" via the existing
        # completion guard at Final Answer time. Mid-flight we don't
        # nag if no checklist exists — the model may just be warming up.
        return None

    last = steps[-1]
    last_thought = str(getattr(last, "thought", "") or "")
    last_obs = str(getattr(last, "observation", "") or "")
    if not (_looks_like_completion_phrase(last_thought) or _looks_like_completion_phrase(last_obs)):
        return None

    # Did the model just call todo_write? Then it already did the
    # right thing — don't pile on.
    parsed = _parse_action(last.action)
    if parsed is not None and parsed[0] == "todo_write":
        return None

    # Are there still incomplete todos? Otherwise the completion
    # phrase is plausibly the wrap-up at the end and the existing
    # final-answer guard takes over.
    incomplete = [item for item in todos if str(item.get("status") or "").lower() != "completed"]
    if not incomplete:
        return None

    return (
        "Detected a completion phrase ('done' / 'finished' / "
        "'已完成' / '搞定' / similar) but the latest action was not "
        "todo_write. Update the visible checklist NOW: mark the "
        "just-finished item completed before moving on. The user can "
        "only see your progress through the checklist."
    )


# Verification "tools" — anything in this set counts as a real
# verification action for the §18 post-write guard. Not the same as
# ``_has_code_verification`` (which scans across all steps); here we
# care about whether a verification is queued in the next slot.
_SHELL_VERIFICATION_TOOLS: frozenset[str] = frozenset(
    {
        "exec_shell",
        "shell_command",
        "bash",
        "run_tests",
        "run_checks",
        "verify",
    }
)

# How many steps after a code-write action we tolerate before
# expecting a verification step. Tuned empirically: long edit
# sequences (multi_edit_file × N then run tests once) need slack;
# anything beyond ~6 steps is "the model forgot to verify".
_POST_WRITE_VERIFY_WINDOW = 6


def _is_static_web_artifact_path(path: str | None) -> bool:
    return classify_path(path) == "static-web"


def _action_path(step: ReActStep) -> str | None:
    parsed = _parse_action(step.action)
    if parsed is None:
        return None
    _name, args = parsed
    value = args.get("path") or args.get("file") or args.get("file_path")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().replace("\\", "/")


def _is_followup_verification_step(
    step: ReActStep,
    *,
    written_path: str | None,
) -> bool:
    parsed = _parse_action(step.action)
    if parsed is None:
        return False
    name, _args = parsed
    if _is_static_web_artifact_path(written_path):
        action_text = _step_command_text(step)
        if name == "read_file" and written_path:
            read_path = _action_path(step)
            return read_path == written_path
        if name.startswith("browser_"):
            return True
        if name in _SHELL_VERIFICATION_TOOLS:
            return any(
                marker in action_text
                for marker in (
                    "node -c",
                    "html validate",
                    "htmlhint",
                    "browser regression",
                    "playwright",
                    "npm run build",
                    "pnpm build",
                )
            )
    if name in _SHELL_VERIFICATION_TOOLS:
        return _has_code_verification([step])
    if name == "read_file" and written_path:
        read_path = _action_path(step)
        return read_path == written_path
    return False


def _unverified_write_followup_guard(
    steps: list[ReActStep],
    *,
    is_code_mode: bool,
) -> str | None:
    """Detect code writes that don't get a follow-up verification.

    Fires DURING the loop. Looks at the last write step within the
    sliding window: if more than ``_POST_WRITE_VERIFY_WINDOW`` steps
    have happened since AND no verification action ran in that
    window, nudge the model to verify before stacking more changes.

    Only active in code mode — chat / research turns have no
    "verify" semantics.

    Returns ``None`` when:
      * not code mode
      * no write actions in history
      * the last write is still within the tolerance window
      * a verification action ran after the last write
    """
    if not is_code_mode or not steps:
        return None

    # Find the last write index.
    last_write_idx = -1
    written_path: str | None = None
    for idx in range(len(steps) - 1, -1, -1):
        if _is_code_write_step(steps[idx]):
            last_write_idx = idx
            written_path = _action_path(steps[idx])
            break
    if last_write_idx < 0:
        return None

    # How many steps since the last write?
    distance = (len(steps) - 1) - last_write_idx
    if distance < _POST_WRITE_VERIFY_WINDOW:
        return None  # still within tolerance

    # Was there a verification step after the last write?
    for follow in steps[last_write_idx + 1 :]:
        if _is_followup_verification_step(follow, written_path=written_path):
            return None  # already verified

    if _is_static_web_artifact_path(written_path):
        return (
            "You wrote a static web artifact "
            f"{distance} step(s) ago without a smoke check. "
            "Before making more changes, verify the artifact with one "
            "of: read_file the written HTML/CSS path, run a small "
            "HTML/embedded-JS syntax check, or use a browser smoke "
            "check/screenshot if a preview URL is available. Do not "
            "default to TypeScript typecheck unless this is actually a "
            "TS/React project file."
        )

    return (
        "You have written or edited code "
        f"{distance} step(s) ago without running verification. "
        "Before making more changes, run an appropriate check: "
        "ruff/pytest/tsc/eslint/test on the affected files (use "
        "exec_shell), or read_file the result back to confirm the "
        "edit landed as intended. Stacking more edits without "
        "verification compounds errors."
    )


def _failed_verification_followup_guard(
    steps: list[ReActStep],
    *,
    is_code_mode: bool,
) -> str | None:
    """Keep a red verifier focused on repair instead of toolchain detours."""
    if not is_code_mode or not steps or not _latest_verification_observation_is_red(steps):
        return None

    latest_verify_idx = -1
    for idx in range(len(steps) - 1, -1, -1):
        if _has_code_verification([steps[idx]]):
            latest_verify_idx = idx
            break
    if latest_verify_idx < 0:
        return None
    if any(_is_code_write_step(step) for step in steps[latest_verify_idx + 1 :]):
        return None

    return (
        "The latest verification is red. Read the preserved tail diagnostic and fix the underlying "
        "source/test/config (or run the targeted formatter) before launching another verifier. "
        "Do not install dependencies, probe alternate Python environments, or create ad-hoc runner "
        "scripts to bypass a registered verifier. For a concurrency-test timeout, audit lock ownership "
        "and wait/notify paths as a likely deadlock before retrying."
    )


def _redundant_green_verification_guard(
    steps: list[ReActStep],
    *,
    is_code_mode: bool,
) -> str | None:
    """Stop code agents from repeatedly re-running an already-green suite."""
    if not is_code_mode or not steps:
        return None

    last_write_idx = -1
    for idx in range(len(steps) - 1, -1, -1):
        if _is_code_write_step(steps[idx]):
            last_write_idx = idx
            break
    if last_write_idx < 0:
        return None

    green_rounds = sum(
        1
        for step in steps[last_write_idx + 1 :]
        if _has_successful_verification_observation([step])
    )
    if green_rounds < 2:
        return None

    return (
        f"Verification is already green in {green_rounds} separate rounds with no intervening code "
        "write. Do not run tests, lint, shell probes, or another verifier again. If the checklist is "
        "stale, call todo_write once with accurate completed statuses; otherwise emit the concise "
        "Final Answer now with the recorded test/lint evidence."
    )


# ──────────────────────────────────────────────────────────────────
# §19 — language-mismatched verification guard
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model edits Foo.tsx but only runs
# pytest, then claims "verified". The legacy ``_has_code_verification``
# is language-agnostic so it returns True; this guard cross-checks
# against the language(s) actually written and surfaces the gap.
#
# Reaches Final Answer time only — at mid-flight a nudge here would
# fight the §18 post-write-verify guard (which doesn't care about
# language). At final-answer the cost of false-claim is highest, so
# we add the strict cross-check there.

# How recent a write must be for the language-mismatch check to fire
# at Final Answer time. Captures the trailing slice of the trajectory
# — long sessions may have already verified earlier-language edits;
# we focus on what the model touched last.
_LANG_MISMATCH_LOOKBACK = 12


def _languages_recently_written(steps: list[ReActStep]) -> set[str]:
    languages: set[str] = set()
    window = steps[-_LANG_MISMATCH_LOOKBACK:] if steps else []
    for step in window:
        if not _is_code_write_step(step):
            continue
        path = _action_path(step)
        lang = _path_language(path)
        if lang is not None:
            languages.add(lang)
    return languages


def _language_mismatched_verification_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals that ran verifiers in the wrong language.

    Triggers when:
      * code mode is active
      * a code-write step happened in the recent window
      * the written file's language has known verifiers
      * NO verifier in that language ran in the trajectory
      * the agent isn't punting the task to the user

    Stays silent when no recognised language was written (e.g. only
    Markdown or YAML edits) — those are handled by the broader §18
    post-write guard.
    """
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None

    languages = _languages_recently_written(steps)
    if not languages:
        return None

    missing = [
        lang
        for lang in sorted(languages)
        if not _has_language_specific_verification(steps, language=lang)
    ]
    if not missing:
        return None

    suggestions = {
        "python": "pytest / ruff / py_compile",
        "typescript": "tsc / eslint / vitest / npm run typecheck",
        "rust": "cargo check / cargo test / cargo clippy",
        "go": "go build / go test / go vet",
    }
    hints = "; ".join(
        f"{lang}: {suggestions.get(lang, 'language-appropriate verifier')}" for lang in missing
    )
    langs_repr = ", ".join(missing)
    return (
        f"Cannot finish yet: edits in {langs_repr} are not verified by a "
        "matching verifier. Running a verifier in a different language "
        "does not count as verification for these files. Run one before "
        f"reporting completion — {hints}."
    )


# ──────────────────────────────────────────────────────────────────
# §20 — new-Python-code-without-test guard
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model adds a new public top-level
# function or class to non-test .py code AND the trajectory contains
# no edit to any test file. Conservative on purpose:
#
#   * Only fires for top-level `def NAME(` / `class NAME` introductions
#     (private `_NAME` and nested defs are skipped).
#   * Only fires for non-test paths.
#   * Stays silent when ANY test file was touched in the trajectory —
#     we don't try to verify the test actually covers the new symbol;
#     a manual edit of a test file is enough signal that the agent is
#     thinking about coverage.
#   * Stays silent when the agent is punting (help-request short-circuit).
#
# False-negative cases we accept:
#   * Renaming an existing public symbol (looks like a new symbol).
#     Tolerated because rename refactors usually touch tests anyway.
#   * Pure additions hidden inside private helpers. Out of scope.
#
# Same lookback window as §19 for consistency.

_VERIFICATION_POLICY_LOOKBACK = 16


def _recent_policy_written_paths(steps: list[ReActStep]) -> tuple[list[str], int]:
    paths: list[str] = []
    last_write_idx = -1
    start_idx = max(0, len(steps) - _VERIFICATION_POLICY_LOOKBACK)
    for idx, step in enumerate(steps[start_idx:], start=start_idx):
        if not _is_code_write_step(step):
            continue
        path = _action_path(step)
        if not path:
            continue
        last_write_idx = idx
        if path not in paths:
            paths.append(path)
    return paths, last_write_idx


def _path_verification_policy_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals that skip path-specific verification obligations."""

    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None

    written_paths, last_write_idx = _recent_policy_written_paths(steps)
    if last_write_idx < 0 or not written_paths:
        return None

    requirements = verification_requirements_for_paths(written_paths)
    if not requirements:
        return None

    followup_texts = [
        f"{step.action or ''}\n{step.observation or ''}" for step in steps[last_write_idx + 1 :]
    ]
    missing = [
        req
        for req in requirements
        if req.required
        and not any(command_satisfies_requirement(text, req) for text in followup_texts)
    ]
    if not missing:
        return None

    return (
        "Cannot finish yet: the touched files require specific verification "
        "after the latest edit. Missing: "
        f"{summarize_requirements(missing)}. Run one of the suggested checks "
        "or explicitly ask the user for help if verification is impossible."
    )


_NEW_SYMBOL_LOOKBACK = 12


def _trajectory_added_public_python_symbol(steps: list[ReActStep]) -> bool:
    window = steps[-_NEW_SYMBOL_LOOKBACK:] if steps else []
    return any(_step_introduces_python_public_symbol(step) for step in window)


def _new_python_code_without_test_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals that introduce new public Python symbols without
    touching any test file in the trajectory.

    Returns ``None`` when:
      * not code mode
      * no recent new-public-symbol introduction
      * any test file was edited in the trajectory
      * agent is asking for user help
    """
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if not _trajectory_added_public_python_symbol(steps):
        return None
    if _has_test_write(steps):
        return None
    return (
        "Cannot finish yet: a new public Python function or class was "
        "added to runtime code, but no test file was edited or created. "
        "Add a focused test under tests/ that exercises the new symbol "
        "(happy path + at least one edge case), or — if a test truly "
        "isn't applicable — say so explicitly in the Final Answer and "
        "explain why."
    )


# ──────────────────────────────────────────────────────────────────
# §21 — public-signature change without typecheck guard
# ──────────────────────────────────────────────────────────────────
# Editing ``def public_thing(a, b)`` → ``def public_thing(a, b, c)`` is a
# silent breaker for every caller. We require the trajectory to run a
# typechecker (mypy / pyright / ruff with PYI rules) when a public sig
# changed. ``ruff`` alone is borderline — it catches some cases but not
# parameter-count breaks. We treat mypy / pyright / pyrefly as the
# canonical typecheckers; basic ``ruff check`` does NOT count.

_PYTHON_TYPECHECK_MARKERS: tuple[str, ...] = (
    "mypy",
    "pyright",
    "pyrefly",
    "pyre",
)

_SIG_CHANGE_LOOKBACK = 12


def _trajectory_changed_public_signature(steps: list[ReActStep]) -> bool:
    window = steps[-_SIG_CHANGE_LOOKBACK:] if steps else []
    return any(_step_changed_public_signature(step) for step in window)


def _has_python_typecheck_run(steps: list[ReActStep]) -> bool:
    for step in steps:
        haystack = (step.action or "").lower()
        parsed = _parse_action(step.action)
        if parsed is not None:
            _name, args = parsed
            haystack += " " + str(args.get("command") or args.get("cmd") or "").lower()
        if any(marker in haystack for marker in _PYTHON_TYPECHECK_MARKERS):
            return True
    return False


def _signature_changed_without_typecheck_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals that change a public Python signature without
    running mypy/pyright/pyrefly in the trajectory."""
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if not _trajectory_changed_public_signature(steps):
        return None
    if _has_python_typecheck_run(steps):
        return None
    return (
        "Cannot finish yet: a public function/method signature changed in "
        "non-test Python code without running a typechecker. ruff alone "
        "doesn't catch parameter-count breaks. Run mypy / pyright / "
        "pyrefly on the affected module before reporting completion, or "
        "explicitly note that no typechecker is configured for the project."
    )


# ──────────────────────────────────────────────────────────────────
# §22 — wire-schema change without compat-test guard
# ──────────────────────────────────────────────────────────────────
# octopus has no DB migrations, but it DOES expose wire-shape schemas
# that external SDKs talk to (anthropic_compat / openai_gateway /
# protocol/items.py). Mutating those without touching a wire-shape
# contract test is a silent break for downstream clients.

_WIRE_SCHEMA_LOOKBACK = 12


def _trajectory_edits_wire_schema(steps: list[ReActStep]) -> bool:
    window = steps[-_WIRE_SCHEMA_LOOKBACK:] if steps else []
    return any(_step_edits_wire_schema(step) for step in window)


def _wire_schema_change_without_compat_test_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals that mutate wire-shape protocol/SDK-compat code
    without editing or adding a wire-shape contract test."""
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if not _trajectory_edits_wire_schema(steps):
        return None
    if _has_wire_contract_test_write(steps):
        return None
    return (
        "Cannot finish yet: a wire-shape schema (protocol/items.py, "
        "anthropic_compat, or openai_gateway) was modified without "
        "editing a wire-shape contract test (e.g. tests/...openai_compat... "
        "or tests/...anthropic_compat...). External SDK clients will break "
        "silently if these contracts shift untested. Add or update a "
        "contract test, or note explicitly that the change is internal-only "
        "and explain why no client is affected."
    )


# ──────────────────────────────────────────────────────────────────
# §23 — third-party import without dependency declaration guard
# ──────────────────────────────────────────────────────────────────
# Adding ``import requests`` to runtime code without putting
# ``requests`` in pyproject.toml ships a code path that ImportErrors
# on a clean install. We detect new third-party imports across the
# trajectory; if none of the trajectory's writes touched a dependency
# manifest (pyproject.toml etc.), the guard fires.

_NEW_IMPORT_LOOKBACK = 12


def _trajectory_new_third_party_imports(steps: list[ReActStep]) -> set[str]:
    out: set[str] = set()
    window = steps[-_NEW_IMPORT_LOOKBACK:] if steps else []
    for step in window:
        out.update(_step_introduces_third_party_imports(step))
    return out


def _has_dep_manifest_write(steps: list[ReActStep]) -> bool:
    return any(_step_writes_dep_manifest(step) for step in steps)


def _new_third_party_import_without_dep_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals that add ``import X`` for a third-party package
    without writing to pyproject.toml / requirements / etc."""
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    new_imports = _trajectory_new_third_party_imports(steps)
    if not new_imports:
        return None
    if _has_dep_manifest_write(steps):
        return None
    pkgs = ", ".join(sorted(new_imports))
    return (
        f"Cannot finish yet: new third-party import(s) added — {pkgs} — "
        "but no dependency manifest (pyproject.toml / requirements.txt) "
        "was updated in this trajectory. The code will ImportError on a "
        "clean install. Either declare the package(s) properly or remove "
        "the import."
    )


# ──────────────────────────────────────────────────────────────────
# §24 — false-verification-claim guard
# ──────────────────────────────────────────────────────────────────
# The Final Answer says "tests pass / 已通过测试 / build succeeded" but
# the trajectory has no successful verifier observation. This is a
# different failure shape than §18 (no verifier ran at all): here the
# model DID issue a verifier call, but it failed (ModuleNotFoundError,
# command not found, traceback) — and the model ignored the failure
# and claimed success anyway.


def _false_verification_claim_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if not _final_answer_claims_verification(final_answer):
        return None
    if _has_successful_verification_observation(steps):
        return None
    return (
        "Cannot finish yet: the Final Answer claims tests/typecheck/build "
        "passed, but no successful verifier observation is recorded in "
        "this trajectory. Either the verifier failed (ModuleNotFoundError, "
        "command-not-found, traceback) or it never ran. Re-run the verifier, "
        "fix any errors, and only claim success after a clean run — or "
        "remove the unsupported claim from the Final Answer."
    )


def _red_verification_observation_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Block a code-mode Final Answer when the model's own most recent
    verification run is red. The false-verification guard only fires when
    the answer *claims* success; this one fires on the recorded failure
    itself — you cannot declare done while your latest test/type/lint/build
    run is failing, whether or not you claimed otherwise. Gated on an
    actual code write so read-only turns that merely surface a red run
    aren't blocked."""
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if not _has_code_write(steps):
        return None
    if not _latest_verification_observation_is_red(steps):
        return None
    return (
        "Cannot finish yet: your most recent verification run is failing "
        "(failing tests / type errors / lint errors / build error in the "
        "last verifier observation). Diagnose and fix the underlying cause, "
        "then re-run the verifier until it is clean before finishing. Do not "
        "finish on a red verification, and do not silence it by deleting or "
        "skipping the failing check."
    )


# ──────────────────────────────────────────────────────────────────
# §28 — commented-out-as-fix guard
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" a problem by deleting
# or commenting out the offending code rather than diagnosing it.
# Heuristic at the parsing layer: an edit pair where old_string had
# executable Python and new_string has none.

_COMMENT_OUT_LOOKBACK = 12


def _trajectory_replaced_code_with_comment(steps: list[ReActStep]) -> bool:
    window = steps[-_COMMENT_OUT_LOOKBACK:] if steps else []
    return any(_step_replaced_code_with_comment(step) for step in window)


def _commented_out_as_fix_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals where a code chunk was replaced with comment/blank
    only — a classic sign of "I made the error go away by deleting the
    code that triggered it"."""
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if not _trajectory_replaced_code_with_comment(steps):
        return None
    return (
        "Cannot finish yet: an edit replaced executable Python with "
        "comments / blank lines / pure docstring. If the code was genuine "
        "dead code, restate that explicitly in the Final Answer and "
        "explain why nothing called it. Otherwise revert the deletion "
        "and diagnose the underlying problem — commenting out a failing "
        "call doesn't fix the bug, it hides it."
    )


# ──────────────────────────────────────────────────────────────────
# §30 — broad-except suppression guard
# ──────────────────────────────────────────────────────────────────
# Reject finals that introduce a NEW ``except Exception: pass`` /
# ``except: ...`` / ``except BaseException: # ignore`` pattern.
# Existing suppressions being moved around are NOT flagged because
# the parsing helper compares new_string to old_string.

_BROAD_EXCEPT_LOOKBACK = 12


def _trajectory_introduces_broad_except(steps: list[ReActStep]) -> bool:
    window = steps[-_BROAD_EXCEPT_LOOKBACK:] if steps else []
    return any(_step_introduces_broad_except_suppression(step) for step in window)


def _broad_except_suppression_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals that introduced a new bare-except / Exception
    suppression in non-test runtime code."""
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    if not _trajectory_introduces_broad_except(steps):
        return None
    return (
        "Cannot finish yet: a new broad-except suppression was added "
        "(``except Exception: pass`` / ``except: ...`` / silent body). "
        "Catching all exceptions and discarding them hides bugs and "
        "makes future debugging much harder. Either narrow the except "
        "to the specific exception type you can recover from, log the "
        "error explicitly, or remove the try/except wrapper entirely "
        "if the operation should propagate failures."
    )


# ──────────────────────────────────────────────────────────────────
# §32 — frontend outside tsconfig.json `include` guard
# ──────────────────────────────────────────────────────────────────
# tsconfig.json's `include` is a hand-maintained list. Editing a
# .ts/.tsx that isn't in that list means tsc never sees the change.
# This guard fires at Final Answer time when a recent edit lands
# outside the include set AND (heuristic) no successful TypeScript
# verifier ran since.

_TSCONFIG_LOOKBACK = 12


def _trajectory_edits_outside_tsconfig(steps: list[ReActStep]) -> list[str]:
    """Return paths that were edited but live outside tsconfig.include.

    Each path appears at most once; we use the LAST edit's path so the
    error message points at the most recent surface area.
    """
    window = steps[-_TSCONFIG_LOOKBACK:] if steps else []
    seen: list[str] = []
    for step in window:
        if not _step_edits_frontend_outside_tsconfig(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        tool_name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str) and path not in seen:
            seen.append(path)
    return seen


def _frontend_outside_tsconfig_include_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    paths = _trajectory_edits_outside_tsconfig(steps)
    if not paths:
        return None
    preview = "; ".join(paths[:3])
    if len(paths) > 3:
        preview += f"; +{len(paths) - 3} more"
    return (
        "Cannot finish yet: edit(s) landed on TypeScript file(s) NOT listed "
        f"in frontend/tsconfig.json's `include`: {preview}. tsc will silently "
        "skip these — the change won't be type-checked. Either add the file(s) "
        "to `include`, or move the change into a file already covered. If the "
        "edit is intentionally outside the type-check surface (e.g. a script), "
        "say so explicitly in the Final Answer."
    )


# ──────────────────────────────────────────────────────────────────
# §33 — oversized single-edit guard
# ──────────────────────────────────────────────────────────────────
# A single edit step that writes more than _OVERSIZED_EDIT_LINE_THRESHOLD
# lines of NEW content is high-blast-radius. We don't reject these
# outright — the agent may legitimately need to rewrite a file — but
# we require a verification step to follow within the same trajectory.

_OVERSIZED_EDIT_LOOKBACK = 12


def _trajectory_has_oversized_edit(steps: list[ReActStep]) -> tuple[int, str | None]:
    """Return (line_count, path) for the latest oversized edit, or
    ``(0, None)`` if none in the lookback window."""
    window = steps[-_OVERSIZED_EDIT_LOOKBACK:] if steps else []
    for step in reversed(window):
        if not _step_is_oversized_edit(step):
            continue
        from runtime.core.cerebrum.react_parsing import _step_payload_line_count

        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        tool_name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        return (_step_payload_line_count(step), path if isinstance(path, str) else None)
    return (0, None)


def _oversized_single_edit_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    line_count, path = _trajectory_has_oversized_edit(steps)
    if line_count <= 0:
        return None
    if _has_code_verification(steps):
        return None
    target = path or "an unknown file"
    return (
        f"Cannot finish yet: a single edit wrote {line_count} new lines to "
        f"{target} — well above the 200-line threshold for safe single-shot "
        "changes — without a verification step in this trajectory. Run the "
        "appropriate verifier (pytest / ruff / tsc / lint) on the affected "
        "file before reporting completion. Large rewrites are exactly where "
        "errors hide, and 'looks right to me' is not enough at this size."
    )


# ──────────────────────────────────────────────────────────────────
# §34 — secret-in-payload guard
# ──────────────────────────────────────────────────────────────────
# Editing a runtime file with an embedded secret (sk-..., ghp_...,
# AKIA..., private key block, ``api_key="..."``) is a serious leak.
# We fire on ANY new secret-shaped string in any code-write trajectory
# step — secrets in non-code files (env templates) are caught by the
# generic pattern set, which is correct.

_SECRET_LOOKBACK = 12


def _trajectory_secret_hits(steps: list[ReActStep]) -> dict[str, str]:
    """Map ``path -> secret-label`` for any step that introduced a
    new secret pattern. Last write wins for a given path."""
    out: dict[str, str] = {}
    window = steps[-_SECRET_LOOKBACK:] if steps else []
    for step in window:
        labels = _step_introduces_secret(step)
        if not labels:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = ", ".join(labels)
    return out


def _secret_in_payload_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals where a write introduced a credential-shaped string.

    No help-request short circuit — leaking a secret while asking for
    help is still a leak. The guard always fires when a hit lands.
    """
    if not steps:
        return None
    hits = _trajectory_secret_hits(steps)
    if not hits:
        return None
    items = list(hits.items())
    preview = "; ".join(f"{path} ({label})" for path, label in items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        "Cannot finish yet: a write step introduced a credential-shaped "
        f"value in: {preview}. Hard-coding API keys, GitHub PATs, AWS "
        'access keys, private-key blocks, or `api_key="..."` literals '
        "into source is a security incident. Move the value to an "
        "environment variable or local config (gitignored), or — if the "
        "string is genuinely a non-secret fixture — make that explicit "
        "(e.g. wrap with a clearly-marked test helper) and try again."
    )


# ──────────────────────────────────────────────────────────────────
# §37 — destructive-call guard
# ──────────────────────────────────────────────────────────────────
# Adding ``shutil.rmtree`` / ``os.remove`` / ``Path.unlink`` / shell
# ``rm -rf`` to non-test runtime code is a high-blast-radius change.
# We don't reject outright — sometimes the agent legitimately needs to
# clean up — but we require explicit acknowledgement: either the code
# is wrapped in safe_rm helpers (the existing octopus tooling at
# runtime/execution/arms/safe_rm.py handles this), OR the trajectory
# touched a test that exercises the destructive path.

_DESTRUCTIVE_LOOKBACK = 12


def _trajectory_destructive_hits(steps: list[ReActStep]) -> dict[str, str]:
    """Map ``path -> labels`` for any step that introduced a new
    destructive call. Last write wins per path."""
    out: dict[str, str] = {}
    window = steps[-_DESTRUCTIVE_LOOKBACK:] if steps else []
    for step in window:
        labels = _step_introduces_destructive_call(step)
        if not labels:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = ", ".join(labels)
    return out


def _new_destructive_call_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals where a write step introduced a new destructive
    filesystem/shell call without a paired test edit."""
    if not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_destructive_hits(steps)
    if not hits:
        return None
    if _has_test_write(steps):
        return None  # Tests touched in trajectory — assume coverage.
    items = list(hits.items())
    preview = "; ".join(f"{path} ({label})" for path, label in items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        "Cannot finish yet: a destructive filesystem/process call was "
        f"added without a paired test edit: {preview}. "
        "rm -rf / shutil.rmtree / Path.unlink / os.remove are easy to "
        "get catastrophically wrong (wrong path, race conditions, "
        "permission loops). Either wrap the call in the project's "
        "safe_rm helper (runtime/execution/arms/safe_rm.py), add a "
        "test that exercises the cleanup with proper fixtures, or "
        "explicitly justify why this code path can't be tested."
    )


# ──────────────────────────────────────────────────────────────────
# §38 — time.sleep in production-path guard
# ──────────────────────────────────────────────────────────────────
# Adding ``time.sleep(...)`` to non-test runtime code is almost always
# a "wait for race condition" anti-pattern. Reject unless the same
# trajectory contains explicit acknowledgement (a clear comment in the
# new content explaining WHY a sleep is the right primitive — e.g.
# rate-limit cooperation, polling-with-backoff, retry).

_SLEEP_LOOKBACK = 12


def _trajectory_sleep_hits(steps: list[ReActStep]) -> list[str]:
    """Paths where new time.sleep / asyncio.sleep was added."""
    out: list[str] = []
    window = steps[-_SLEEP_LOOKBACK:] if steps else []
    for step in window:
        if not _step_introduces_sleep(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str) and path not in out:
            out.append(path)
    return out


def _sleep_in_production_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    paths = _trajectory_sleep_hits(steps)
    if not paths:
        return None
    preview = "; ".join(paths[:3])
    if len(paths) > 3:
        preview += f"; +{len(paths) - 3} more"
    return (
        f"Cannot finish yet: time.sleep / asyncio.sleep was added to non-test "
        f"runtime code: {preview}. Bare sleeps in production are almost "
        "always 'wait for the race condition to resolve itself' — they "
        "mask bugs and make tests flaky. Use the appropriate primitive "
        "(asyncio.Event, threading.Event, retry helper, explicit poll "
        "with cancel) or — if the sleep is deliberately part of a rate "
        "limiter / backoff / cooperative yield — add a comment explaining "
        "WHY and remove this nag by re-running."
    )


# ──────────────────────────────────────────────────────────────────
# §40 — full-file rewrite guard
# ──────────────────────────────────────────────────────────────────
# ``write_text_file`` overwriting an existing >100-line file silently
# drops anything the model "forgot" — common with imports, helpers,
# and docstrings. We allow the rewrite ONLY when the same trajectory
# previously edited the same file with edit_file/multi_edit_file
# (proving the model has surveyed the existing content) OR the file
# is brand new (doesn't exist on disk).

_FULL_REWRITE_LOOKBACK = 12


def _trajectory_full_rewrite_hits(
    steps: list[ReActStep],
    *,
    repo_root: str | None = None,
) -> list[tuple[str, int]]:
    """Return ``[(path, existing_line_count)]`` for full-rewrite attempts
    that lack a prior surgical edit on the same path within the lookback."""
    window = steps[-_FULL_REWRITE_LOOKBACK:] if steps else []
    bad: list[tuple[str, int]] = []
    for idx, step in enumerate(window):
        is_rewrite, path, line_count = _step_is_full_file_rewrite_attempt(
            step,
            repo_root=repo_root,
        )
        if not is_rewrite or not path:
            continue
        # Has any earlier step in the trajectory edited this file
        # surgically?
        prior = window[:idx]
        if any(_step_is_surgical_edit_on(s, target_path=path) for s in prior):
            continue
        bad.append((path, line_count))
    return bad


def _full_file_rewrite_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    bad = _trajectory_full_rewrite_hits(steps)
    if not bad:
        return None
    preview = "; ".join(f"{path} ({lines} existing lines)" for path, lines in bad[:3])
    if len(bad) > 3:
        preview += f"; +{len(bad) - 3} more"
    return (
        "Cannot finish yet: write_text_file overwrote existing file(s) without "
        f"first surveying them via edit_file or read_file: {preview}. "
        "Full-file rewrites silently drop imports, helpers, comments, and "
        "edge-case branches the model forgot. Use edit_file for surgical "
        "changes, OR read_file the existing content first and then "
        "write_text_file with full coverage. If the rewrite truly is "
        "deliberate (e.g. you scrubbed the file from a known-good "
        "template), add an explicit edit_file step earlier in the "
        "trajectory or note the intent in the Final Answer."
    )


def _ambiguous_inflight_leader_election_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject a common single-flight race that local smoke tests can miss."""
    if not is_code_mode or not steps or _final_answer_requests_user_help(final_answer):
        return None
    affected: set[str] = set()
    for step in steps:
        if not _is_code_write_step(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        tool_name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str) or _is_test_path(path):
            continue
        new_text, old_text = _extract_step_payloads(step)
        old_hit = _payload_has_ambiguous_inflight_leader_election(old_text)
        new_hit = _payload_has_ambiguous_inflight_leader_election(new_text)
        full_clean_rewrite = (
            tool_name in {"write_text_file", "write_file", "create_file"}
            and path in affected
            and bool(new_text)
            and not new_hit
        )
        removed_identity_election = _payload_has_inflight_identity_comparison(
            old_text
        ) and not _payload_has_inflight_identity_comparison(new_text)
        if (old_hit or removed_identity_election or full_clean_rewrite) and not new_hit:
            affected.discard(path)
        elif new_hit:
            affected.add(path)
    if not affected:
        return None
    preview = ", ".join(sorted(affected)[:3])
    return (
        "Cannot finish yet: the single-flight implementation in "
        f"{preview} tries to distinguish leader from follower by re-reading the pending map and "
        "comparing object identity after the lock. Creator and followers all observe the same "
        "pending object, so multiple callers can execute the loader. Capture an explicit leader "
        "boolean inside the locked `pending is None` branch (or keep the loader branch tied to "
        "entry creation), make followers wait outside the map lock, then rerun a contention test "
        "whose loader stays in-flight until followers have joined."
    )


def _destructive_waiter_result_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject single-flight state that only one of many waiters can consume."""
    if not is_code_mode or not steps or _final_answer_requests_user_help(final_answer):
        return None
    affected: set[str] = set()
    for step in steps:
        if not _is_code_write_step(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        tool_name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str) or _is_test_path(path):
            continue
        new_text, old_text = _extract_step_payloads(step)
        old_hit = _payload_has_destructive_waiter_result_pop(old_text)
        new_hit = _payload_has_destructive_waiter_result_pop(new_text)
        removed_pop = ".pop(" in old_text and ".pop(" not in new_text
        full_clean_rewrite = (
            tool_name in {"write_text_file", "write_file", "create_file"}
            and path in affected
            and bool(new_text)
            and not new_hit
        )
        if (old_hit or removed_pop or full_clean_rewrite) and not new_hit:
            affected.discard(path)
        elif new_hit:
            affected.add(path)
    if not affected:
        return None
    preview = ", ".join(sorted(affected)[:3])
    return (
        "Cannot finish yet: follower waiters in "
        f"{preview} read the shared loader result with `pop`. With multiple waiters, the first "
        "follower consumes that result and later followers can miss it, retry the loader, or "
        "return no value. Store result/exception on the per-flight pending object (or read the "
        "fresh cache entry non-destructively) until every waiter has observed it; only remove the "
        "in-flight map entry after wake-up state is durable. Then run a contention test with at "
        "least eight callers and a loader held in-flight long enough for followers to join."
    )


def _stale_immutable_waiter_snapshot_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject tuple-based pending state that becomes stale across wait()."""
    if not is_code_mode or not steps or _final_answer_requests_user_help(final_answer):
        return None
    affected: set[str] = set()
    for step in steps:
        if not _is_code_write_step(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        tool_name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str) or _is_test_path(path):
            continue
        new_text, old_text = _extract_step_payloads(step)
        old_hit = _payload_has_stale_immutable_waiter_snapshot(old_text)
        new_hit = _payload_has_stale_immutable_waiter_snapshot(new_text)
        full_clean_rewrite = (
            tool_name in {"write_text_file", "write_file", "create_file"}
            and path in affected
            and bool(new_text)
            and not new_hit
        )
        removed_stale_fallback = (
            ".get(" in old_text
            and ", pending" in old_text
            and not (
                ".get(" in new_text
                and ", pending" in new_text
            )
        )
        if (old_hit or removed_stale_fallback or full_clean_rewrite) and not new_hit:
            affected.discard(path)
        elif new_hit:
            affected.add(path)
    if not affected:
        return None
    preview = ", ".join(sorted(affected)[:3])
    return (
        "Cannot finish yet: follower waiters in "
        f"{preview} capture an immutable pending tuple before waiting, while the leader later "
        "replaces and deletes the map entry. The post-wait fallback therefore reads the stale "
        "tuple and can return `None` or lose the loader exception. Store result/exception on a "
        "mutable per-flight object that every waiter shares, or keep a durable completed entry "
        "until all waiters can read it. Then run an eight-caller test whose loader remains "
        "blocked until every follower has joined."
    )


def _terminal_pending_entry_leak_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject completed in-flight entries that permanently shadow TTL reloads."""
    if not is_code_mode or not steps or _final_answer_requests_user_help(final_answer):
        return None
    affected: set[str] = set()
    for step in steps:
        if not _is_code_write_step(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        tool_name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str) or _is_test_path(path):
            continue
        new_text, old_text = _extract_step_payloads(step)
        old_hit = _payload_has_terminal_pending_entry_leak(old_text)
        new_hit = _payload_has_terminal_pending_entry_leak(new_text)
        full_clean_rewrite = (
            tool_name in {"write_text_file", "write_file", "create_file"}
            and path in affected
            and bool(new_text)
            and not new_hit
        )
        if (old_hit or full_clean_rewrite) and not new_hit:
            affected.discard(path)
        elif new_hit:
            affected.add(path)
    if not affected:
        return None
    preview = ", ".join(sorted(affected)[:3])
    return (
        "Cannot finish yet: the completed single-flight entry in "
        f"{preview} remains in the pending/in-flight map after the event is signalled. Future "
        "calls therefore keep taking the follower branch; an expired TTL value can never reload "
        "and a failed load can poison every retry. Publish result/exception on a mutable flight "
        "object retained by existing waiters, then remove the key from the in-flight map before "
        "returning. Add a regression that loads, advances the clock past TTL, and proves a new "
        "loader invocation occurs."
    )


def _loader_barrier_deadlock_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject concurrency tests whose loader can never clear its barrier."""
    if not is_code_mode or not steps or _final_answer_requests_user_help(final_answer):
        return None
    affected: set[str] = set()
    for step in steps:
        if not _is_code_write_step(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        tool_name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str) or not _is_test_path(path):
            continue
        new_text, old_text = _extract_step_payloads(step)
        old_hit = _payload_has_loader_barrier_deadlock(old_text)
        new_hit = _payload_has_loader_barrier_deadlock(new_text)
        full_clean_rewrite = (
            tool_name in {"write_text_file", "write_file", "create_file"}
            and path in affected
            and bool(new_text)
            and not new_hit
        )
        if (old_hit or full_clean_rewrite) and not new_hit:
            affected.discard(path)
        elif new_hit:
            affected.add(path)
    if not affected:
        return None
    preview = ", ".join(sorted(affected)[:3])
    return (
        "Cannot finish yet: the single-flight test in "
        f"{preview} waits on a threading.Barrier inside the loader, but only the elected leader "
        "enters that loader; followers wait on the flight event, so the barrier can never fill. "
        "Move the barrier to each worker immediately before get_or_load. If the loader must stay "
        "in flight, have it wait on a separate Event that the test thread releases after callers "
        "have started, and use bounded waits/joins."
    )


def _concurrency_semantic_followup_guard(
    steps: list[ReActStep],
    *,
    is_code_mode: bool,
) -> str | None:
    """Surface deterministic concurrency defects immediately after a write."""
    for guard in (
        _ambiguous_inflight_leader_election_guard,
        _destructive_waiter_result_guard,
        _stale_immutable_waiter_snapshot_guard,
        _terminal_pending_entry_leak_guard,
        _loader_barrier_deadlock_guard,
    ):
        message = guard(steps, "implementation complete", is_code_mode=is_code_mode)
        if message is not None:
            return message.replace("Cannot finish yet: ", "Before verification: ", 1)
    return None


# ──────────────────────────────────────────────────────────────────
# §42 — weak-test-assertion guard
# ──────────────────────────────────────────────────────────────────
# After §20 forced "no new public symbol without a test edit", the
# obvious cheat is to write a test that asserts nothing meaningful.
# This guard catches: ``assert True``, ``pass``, ``...``, ``assert
# obj is not None``, ``assert obj`` (truthiness only). One weak test
# in a multi-test file is tolerated; we only fire when EVERY new test
# function added is a no-op.

_WEAK_TEST_LOOKBACK = 12


def _trajectory_weak_test_hits(steps: list[ReActStep]) -> dict[str, list[tuple[str, str]]]:
    """Map ``test_path -> [(test_name, weakness_label)]`` for steps
    that introduced new weak tests."""
    out: dict[str, list[tuple[str, str]]] = {}
    window = steps[-_WEAK_TEST_LOOKBACK:] if steps else []
    for step in window:
        weak = _step_introduces_weak_test(step)
        if not weak:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out.setdefault(path, []).extend(weak)
    return out


def _trajectory_added_strong_test(steps: list[ReActStep]) -> bool:
    """Whether any test edit in trajectory added at least ONE function
    that ISN'T classified as weak. Lets a file with one weak + one
    strong test pass."""
    window = steps[-_WEAK_TEST_LOOKBACK:] if steps else []
    for step in window:
        if not _is_code_write_step(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str) or not _is_test_path(path):
            continue
        new_chunks: list[str] = []
        for key in ("content", "new_string", "new_str"):
            value = args.get(key)
            if isinstance(value, str):
                new_chunks.append(value)
        edits = args.get("edits")
        if isinstance(edits, list):
            for edit in edits:
                if not isinstance(edit, dict):
                    continue
                for key in ("new_string", "new_str", "content"):
                    value = edit.get(key)
                    if isinstance(value, str):
                        new_chunks.append(value)
        new_text = "\n".join(new_chunks)
        all_funcs = {match.group("name") for match in _TEST_FUNC_RE.finditer(new_text)}
        weak_funcs = {name for name, _label in _detect_weak_tests_in_payload(new_text)}
        if all_funcs - weak_funcs:
            return True
    return False


def _weak_test_assertion_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    """Reject finals where every new test function added is a no-op."""
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_weak_test_hits(steps)
    if not hits:
        return None
    # If at least one added test is non-weak, accept the trajectory.
    if _trajectory_added_strong_test(steps):
        return None
    items = [
        f"{path} :: {name} ({label})"
        for path, weak_list in hits.items()
        for name, label in weak_list
    ]
    preview = "; ".join(items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        "Cannot finish yet: every new test added in this trajectory has "
        f"a no-op body — {preview}. ``assert True`` / ``pass`` / "
        "``assert x is not None`` doesn't actually exercise the code "
        "under test. Replace each weak assertion with a real comparison "
        "(expected output, exception type, side-effect on a fixture), "
        "or remove the test if it can't be made meaningful."
    )


# ──────────────────────────────────────────────────────────────────
# §44 — print() in production guard
# ──────────────────────────────────────────────────────────────────
# octopus runs on ``logging`` everywhere. Adding a bare ``print(...)``
# to non-CLI runtime code is a debug leftover. CLI/script paths
# (runtime/cli.py, scripts/, tools/) are exempt at the parsing layer.

_PRINT_LOOKBACK = 12


def _trajectory_print_hits(steps: list[ReActStep]) -> list[str]:
    out: list[str] = []
    window = steps[-_PRINT_LOOKBACK:] if steps else []
    for step in window:
        if not _step_introduces_print(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str) and path not in out:
            out.append(path)
    return out


def _print_in_production_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    paths = _trajectory_print_hits(steps)
    if not paths:
        return None
    preview = "; ".join(paths[:3])
    if len(paths) > 3:
        preview += f"; +{len(paths) - 3} more"
    return (
        "Cannot finish yet: print(...) was added to non-test, non-CLI "
        f"runtime code: {preview}. octopus uses ``logging`` everywhere "
        "(``_logger = logging.getLogger(__name__)`` + ``_logger.info(...)`` "
        "etc.). Bare prints leak debug output to stdout, can't be filtered "
        "by level, and break log scrapers. Replace with the appropriate "
        "log call — or, if the print was a debugging leftover, remove it "
        "entirely."
    )


# ──────────────────────────────────────────────────────────────────
# §45 — hardcoded personal path guard
# ──────────────────────────────────────────────────────────────────
# Catch hardcoded ``C:\Users\<name>``, ``/Users/<name>``,
# ``/home/<name>`` paths in committed code. These are user-specific
# and break on every other developer's machine.

_HARDCODED_PATH_LOOKBACK = 12


def _trajectory_hardcoded_path_hits(steps: list[ReActStep]) -> dict[str, str]:
    out: dict[str, str] = {}
    window = steps[-_HARDCODED_PATH_LOOKBACK:] if steps else []
    for step in window:
        labels = _step_introduces_hardcoded_path(step)
        if not labels:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = ", ".join(labels)
    return out


def _hardcoded_personal_path_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_hardcoded_path_hits(steps)
    if not hits:
        return None
    items = list(hits.items())
    preview = "; ".join(f"{path} ({label})" for path, label in items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        "Cannot finish yet: a user-specific path was hardcoded into "
        f"committed code: {preview}. ``C:\\Users\\<name>`` / "
        "``/Users/<name>`` / ``/home/<name>`` are machine-local and will "
        "break on every other developer's environment. Use ``Path.home()``, "
        "``os.path.expanduser('~')``, an environment variable, or read "
        "the location from config.yaml. If this really is a path that "
        "must point to a specific user dir at runtime, accept it via "
        "config / CLI flag rather than baking it into source."
    )


# ──────────────────────────────────────────────────────────────────
# §47 — mock-only test guard
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where §20 + §42 are both satisfied but the
# new test only asserts ``mock.called`` / ``mock.call_count == 1`` —
# proving the mock was hit, not that it was hit with the RIGHT args.

_MOCK_ONLY_LOOKBACK = 12


def _trajectory_mock_only_hits(steps: list[ReActStep]) -> dict[str, list[str]]:
    """``test_path -> [test_name, ...]`` for new mock-only tests."""
    out: dict[str, list[str]] = {}
    window = steps[-_MOCK_ONLY_LOOKBACK:] if steps else []
    for step in window:
        names = _step_introduces_mock_only_test(step)
        if not names:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out.setdefault(path, []).extend(names)
    return out


def _mock_only_test_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_mock_only_hits(steps)
    if not hits:
        return None
    items = [f"{path} :: {name}" for path, names in hits.items() for name in names]
    preview = "; ".join(items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        "Cannot finish yet: new test(s) only assert mock truthiness without "
        f"checking call arguments — {preview}. ``assert mock.called`` proves "
        "the function was invoked but not that it received the right args. "
        "Use ``mock.assert_called_with(...)`` / ``mock.call_args`` / "
        "``mock.assert_called_once_with(...)`` to verify the actual call "
        "shape, or replace the mock-only assertion with a real-output check."
    )


# ──────────────────────────────────────────────────────────────────
# §48 — undocumented pytest skip guard
# ──────────────────────────────────────────────────────────────────
# ``@pytest.mark.skip`` and ``pytest.skip()`` without an explicit
# reason longer than 8 chars (and not just "TODO" / "FIXME") is
# almost always papering over a real failure.

_SKIP_LOOKBACK = 12


def _trajectory_undocumented_skip_hits(steps: list[ReActStep]) -> list[str]:
    out: list[str] = []
    window = steps[-_SKIP_LOOKBACK:] if steps else []
    for step in window:
        if not _step_introduces_undocumented_skip(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str) and path not in out:
            out.append(path)
    return out


def _undocumented_skip_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    paths = _trajectory_undocumented_skip_hits(steps)
    if not paths:
        return None
    preview = "; ".join(paths[:3])
    if len(paths) > 3:
        preview += f"; +{len(paths) - 3} more"
    return (
        f"Cannot finish yet: pytest.skip / @pytest.mark.skip was added to "
        f"test(s) without a meaningful reason: {preview}. A skip without "
        "a clear explanation ('requires GPU', 'covered by integration "
        "test foo', etc.) is hiding a real failure. Either give the skip "
        "a specific, non-placeholder reason of at least 8 characters, "
        "fix the underlying test, or remove the skip entirely."
    )


# ──────────────────────────────────────────────────────────────────
# §49 — deleted-test guard
# ──────────────────────────────────────────────────────────────────
# Removing test functions in the same trajectory that adds runtime
# code is a textbook "make the failing test go away" cheat. We list
# the deleted test names; the model has to either restore them or
# explicitly justify the deletion in the Final Answer.

_DELETED_TEST_LOOKBACK = 12


def _trajectory_deleted_tests(steps: list[ReActStep]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    window = steps[-_DELETED_TEST_LOOKBACK:] if steps else []
    for step in window:
        names = _step_deleted_test_functions(step)
        if not names:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out.setdefault(path, []).extend(names)
    return out


def _deleted_test_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_deleted_tests(steps)
    if not hits:
        return None
    items = [f"{path} :: {name}" for path, names in hits.items() for name in names]
    preview = "; ".join(items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        f"Cannot finish yet: existing test function(s) were deleted in this "
        f"trajectory: {preview}. Removing a failing test instead of fixing "
        "the cause is a textbook cheat. Either restore the test and fix the "
        "underlying issue, OR — if the test really is obsolete (covers "
        "removed functionality, replaced by a better test elsewhere) — "
        "explicitly state in the Final Answer which test was removed and "
        "why no coverage was lost."
    )


# ──────────────────────────────────────────────────────────────────
# §52 — generic test name guard
# ──────────────────────────────────────────────────────────────────
# Catch test functions named ``test_basic`` / ``test_works`` /
# ``test_x`` / ``test_1`` etc. — placeholder names that tell the next
# reader nothing about what the test guards.

_GENERIC_NAME_LOOKBACK = 12


def _trajectory_generic_test_hits(steps: list[ReActStep]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    window = steps[-_GENERIC_NAME_LOOKBACK:] if steps else []
    for step in window:
        names = _step_introduces_generic_test_name(step)
        if not names:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out.setdefault(path, []).extend(names)
    return out


def _generic_test_name_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_generic_test_hits(steps)
    if not hits:
        return None
    items = [f"{path} :: {name}" for path, names in hits.items() for name in names]
    preview = "; ".join(items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        "Cannot finish yet: new test function(s) have placeholder names "
        f"that don't describe the behavior under test: {preview}. Names "
        "like ``test_basic`` / ``test_works`` / ``test_x`` / ``test_1`` "
        "give the next reader zero hints about what the test guards. "
        "Rename each to describe the BEHAVIOR being asserted "
        "(``test_handles_empty_input``, ``test_retries_on_timeout``, "
        "``test_rejects_negative_count`` …)."
    )


# ──────────────────────────────────────────────────────────────────
# §54 — no-assertion test guard
# ──────────────────────────────────────────────────────────────────
# Test body has substantive code (more than 1 line, dodging §42) but
# zero ``assert`` / ``assert_called_*`` / ``pytest.raises`` etc. Such
# a test passes if the call doesn't raise — almost never the intent.

_NO_ASSERT_LOOKBACK = 12


def _trajectory_no_assertion_test_hits(steps: list[ReActStep]) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    window = steps[-_NO_ASSERT_LOOKBACK:] if steps else []
    for step in window:
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str):
            continue

        new_text, _old_text = _extract_step_payloads(step)
        touched_test_names = {
            match.group("name") for match in _TEST_FUNC_RE.finditer(new_text)
        }
        if touched_test_names:
            # A later rewrite of the same test function supersedes the earlier
            # defect. Keeping every historical hit forever made a repaired
            # test impossible to finish: the guard still rejected the final
            # answer after the new body added a concrete assertion.
            out.setdefault(path, set()).difference_update(touched_test_names)

        names = set(_step_introduces_no_assertion_test(step))
        if names:
            out.setdefault(path, set()).update(names)
        elif touched_test_names:
            current_bad = set(_detect_no_assertion_tests_in_payload(new_text))
            out.setdefault(path, set()).update(current_bad)

        if path in out and not out[path]:
            del out[path]
    return {path: sorted(names) for path, names in out.items()}


def _no_assertion_test_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_no_assertion_test_hits(steps)
    if not hits:
        return None
    items = [f"{path} :: {name}" for path, names in hits.items() for name in names]
    preview = "; ".join(items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        "Cannot finish yet: new test function(s) execute code but don't "
        f"actually assert anything — {preview}. A test that just calls the "
        "function under test passes whenever the call doesn't raise — that "
        "verifies almost nothing. Add an explicit ``assert`` on the return "
        "value, an ``assert_called_with(...)`` on the mock, a "
        "``pytest.raises(...)`` block, or some other concrete check."
    )


# ──────────────────────────────────────────────────────────────────
# §57 — async-without-await guard
# ──────────────────────────────────────────────────────────────────
# Catches ``async def foo():`` whose non-trivial body never awaits,
# yields, or uses async-with / async-for. The function returns a
# coroutine the caller likely never awaits — a silent bug.

_ASYNC_NO_AWAIT_LOOKBACK = 12


def _trajectory_async_no_await_hits(steps: list[ReActStep]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    window = steps[-_ASYNC_NO_AWAIT_LOOKBACK:] if steps else []
    for step in window:
        names = _step_introduces_async_without_await(step)
        if not names:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out.setdefault(path, []).extend(names)
    return out


def _async_without_await_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_async_no_await_hits(steps)
    if not hits:
        return None
    items = [f"{path} :: {name}" for path, names in hits.items() for name in names]
    preview = "; ".join(items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        f"Cannot finish yet: new ``async def`` function(s) never await, "
        f"yield, or use async-with/async-for in their body: {preview}. "
        "An async function with a synchronous body returns a coroutine "
        "the caller likely never awaits — meaning the body never runs. "
        "Either drop the ``async`` keyword (make it a normal def), or add "
        "the ``await`` you intended. If the function is genuinely an "
        "abstract / protocol stub, mark it ``@abstractmethod`` or use a "
        "``...`` body."
    )


# ──────────────────────────────────────────────────────────────────
# §59 — exception-swallow-via-log guard
# ──────────────────────────────────────────────────────────────────
# ``except SomeError: log.error(...)`` without re-raising silently
# discards the failure. Looks like proper handling; isn't. This is
# the more deceptive sibling of §30 broad-except-pass.

_LOG_SWALLOW_LOOKBACK = 12


def _trajectory_log_swallow_paths(steps: list[ReActStep]) -> list[str]:
    out: list[str] = []
    window = steps[-_LOG_SWALLOW_LOOKBACK:] if steps else []
    for step in window:
        if not _step_introduces_log_swallow(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str) and path not in out:
            out.append(path)
    return out


def _exception_swallow_via_log_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    paths = _trajectory_log_swallow_paths(steps)
    if not paths:
        return None
    preview = "; ".join(paths[:3])
    if len(paths) > 3:
        preview += f"; +{len(paths) - 3} more"
    return (
        "Cannot finish yet: ``except: log.error(...)`` without a re-raise "
        f"was added to runtime code: {preview}. Logging an error and then "
        "continuing silently swallows the failure — the next reader sees "
        "the log call and assumes it's handled, but the program just "
        "marches on with bad state. Either re-raise after logging "
        "(``raise``), narrow the except to a specific type you can "
        "actually recover from, or remove the try/except wrapper "
        "entirely if propagation is the right behavior."
    )


# ──────────────────────────────────────────────────────────────────
# §61 — long-function guard
# ──────────────────────────────────────────────────────────────────
# A new function whose substantive body exceeds 150 lines is too
# long to test, read, or reason about cohesively. We don't flag
# refactors that move existing long functions — only fresh additions.

_LONG_FUNCTION_LOOKBACK = 12


def _trajectory_long_function_hits(steps: list[ReActStep]) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    window = steps[-_LONG_FUNCTION_LOOKBACK:] if steps else []
    for step in window:
        hits = _step_introduces_long_function(step)
        if not hits:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out.setdefault(path, []).extend(hits)
    return out


def _long_function_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _final_answer_requests_user_help(final_answer):
        return None
    hits = _trajectory_long_function_hits(steps)
    if not hits:
        return None
    items = [
        f"{path} :: {name} ({lines} lines)"
        for path, fn_hits in hits.items()
        for name, lines in fn_hits
    ]
    preview = "; ".join(items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        f"Cannot finish yet: new function(s) exceed the 150-line "
        f"complexity threshold: {preview}. Long functions are hard to "
        "test, hard to read, and tend to bundle multiple responsibilities. "
        "Split into smaller helpers organised around a single concept "
        "each. If the length is fundamentally necessary (state machine, "
        "long switch dispatch), state that explicitly in the Final "
        "Answer so the next reviewer knows it was a deliberate choice."
    )


# ──────────────────────────────────────────────────────────────────
# §63, §65-§67, §69-§70 — Security + quality guards (EXTRACTED 2026-06-06)
# ──────────────────────────────────────────────────────────────────
# The following guards have been extracted to react_security_guards.py
# to reduce this file's size. Re-exported here for backward compatibility.

from .react_security_guards import (  # noqa: E402, F401 — re-exported for backward compatibility
    _dynamic_exec_guard,
    _magic_number_guard,
    _network_in_loop_guard,
    _repeated_literal_guard,
    _shell_injection_guard,
    _trajectory_dynamic_exec_hits,
    _trajectory_magic_number_hits,
    _trajectory_network_in_loop_paths,
    _trajectory_repeated_literal_hits,
    _trajectory_shell_injection_hits,
    _trajectory_unsafe_deser_hits,
    _unsafe_deser_guard,
)


def _browser_goal_required_evidence(goal: str) -> set[str]:
    """Translate an explicit browser task into observable completion facts."""

    lowered = str(goal or "").lower()
    required: set[str] = set()
    if any(
        marker in lowered for marker in ("native select", "select ", "dropdown", "下拉", "选择")
    ):
        required.add("select")
    if any(marker in lowered for marker in ("rich-text", "rich text", "contenteditable", "富文本")):
        required.add("rich_text")
    if any(marker in lowered for marker in ("upload", "上传")):
        required.add("upload")
    if any(marker in lowered for marker in ("submit", "提交")):
        required.add("submit")
    if any(marker in lowered for marker in ("iframe", "confirmation", "confirmed", "确认状态")):
        required.add("confirmation")
    if any(marker in lowered for marker in ("delete", "remove", "删除")):
        required.add("delete")
    if any(marker in lowered for marker in ("create", "edit", "update", "新增", "编辑", "更新")):
        required.update(("type", "click"))
    return required


def _browser_action_evidence(steps: list[ReActStep]) -> tuple[set[str], int]:
    """Collect successful UI actions and post-submit confirmation evidence."""

    evidence: set[str] = set()
    submit_attempts = 0
    submitted = False
    confirmation_markers = (
        "onboarding complete",
        "confirmation.html",
        'id="confirmed"',
        "'confirmed'",
        '"confirmed"',
    )
    for step in steps:
        actions = step.actions or ([step.action] if step.action else [])
        for index, raw_action in enumerate(actions):
            parsed = _parse_action(raw_action)
            if parsed is None:
                continue
            name, args = parsed
            name = name.lower()
            target = " ".join(f"{key} {value}" for key, value in args.items()).lower()
            action_ok = True
            if index < len(step.action_results):
                action_ok = bool(step.action_results[index].get("ok"))
            else:
                observation = (step.observation or "").lower()
                action_ok = not any(
                    marker in observation
                    for marker in ("(工具失败)", "(工具执行异常)", '"error":', "timed_out")
                )

            if name in {"browser_type", "live_browser_type"} and action_ok:
                evidence.add("type")
                if any(marker in target for marker in ("role", "select", "dropdown", "option")):
                    evidence.add("select")
                if any(marker in target for marker in ("bio", "rich", "contenteditable")):
                    evidence.add("rich_text")
            elif name == "browser_upload" and action_ok:
                evidence.add("upload")
            elif name in {"browser_click", "live_browser_click"}:
                if "submit" in target:
                    # Count attempts, not only successful receipts: a click may
                    # mutate the page before a transport error is reported and
                    # must never be automatically repeated for "exactly once".
                    submit_attempts += 1
                    submitted = True
                    if action_ok:
                        evidence.add("submit")
                if action_ok:
                    evidence.add("click")
                    if any(marker in target for marker in ("delete", "remove", "删除")):
                        evidence.add("delete")

        if submitted:
            observation = (step.observation or "").lower()
            if any(marker in observation for marker in confirmation_markers):
                evidence.add("confirmation")
    return evidence, submit_attempts


def _browser_interaction_completion_guard(ctx: GuardContext) -> str | None:
    if not ctx.browser_operation_mode or _final_answer_requests_user_help(ctx.final_answer):
        return None
    required = _browser_goal_required_evidence(ctx.goal)
    if not required:
        return None
    evidence, submit_attempts = _browser_action_evidence(ctx.steps)
    missing = sorted(required - evidence)
    if not missing:
        return None
    labels = {
        "select": "native select interaction",
        "rich_text": "rich-text entry",
        "type": "form entry",
        "upload": "browser_upload receipt",
        "click": "UI click",
        "submit": "successful submit click",
        "delete": "delete click",
        "confirmation": "post-submit iframe confirmation observation",
    }
    missing_text = ", ".join(labels[item] for item in missing)
    once_note = (
        " A submit click was already attempted; do not click Submit again. Observe the current "
        "page with browser_get(wait_ms=300) or browser_state instead."
        if submit_attempts
        else ""
    )
    return (
        "Cannot finish this explicit browser task yet. Missing executed UI evidence: "
        f"{missing_text}.{once_note} Continue with the persistent browser page; for delayed "
        "iframe results, read the child-frame evidence returned in the frames field."
    )


def _mixed_mode_completion_guard(ctx: GuardContext) -> str | None:
    """Require evidence from every lane in explicit browser-plus-code work."""

    if (
        not ctx.browser_operation_mode
        or not ctx.is_code_mode
        or _browser_goal_is_ui_only(ctx.goal)
        or _final_answer_requests_user_help(ctx.final_answer)
    ):
        return None
    lowered = str(ctx.goal or "").lower()
    browser_requested = any(
        marker in lowered
        for marker in ("browser", "browser ui", "web ui", "浏览器", "页面", "界面")
    )
    code_requested = any(
        marker in lowered
        for marker in (
            "source code",
            "codebase",
            "repository",
            "repo",
            "patch",
            "pytest",
            "run tests",
            "源代码",
            "代码仓库",
            "修改代码",
            "运行测试",
        )
    )
    if not (browser_requested and code_requested):
        return None

    missing: list[str] = []
    if not _has_successful_browser_action(ctx.steps):
        missing.append("executed browser reproduction or inspection")
    if not _has_code_write(ctx.steps):
        missing.append("workspace code edit")
    if not _has_code_verification(ctx.steps):
        missing.append("code verification command")
    if not missing:
        return None
    return (
        "Cannot finish this mixed browser-and-code task yet. Missing lane evidence: "
        f"{', '.join(missing)}. Complete each requested lane in the same turn; "
        "do not treat a code-only or browser-only result as completion."
    )


def _has_successful_browser_action(steps: list[ReActStep]) -> bool:
    for step in steps:
        actions = step.actions or ([step.action] if step.action else [])
        for index, raw_action in enumerate(actions):
            parsed = _parse_action(raw_action)
            if parsed is None:
                continue
            name = parsed[0].lower()
            if not (name.startswith("browser_") or name.startswith("live_browser_")):
                continue
            if name in {"browser_close", "live_browser_close"}:
                continue
            if index < len(step.action_results):
                if bool(step.action_results[index].get("ok")):
                    return True
                continue
            observation = (step.observation or "").lower()
            if not any(
                marker in observation
                for marker in ("(工具失败)", "(工具执行异常)", '"error":', "timed_out")
            ):
                return True
    return False


@dataclass
class GuardContext:
    """Everything a guard might need to evaluate a candidate final answer.

    Bundles the trajectory, the proposed final answer, and the loop-level
    flags that previously gated each guard inline (is_code_mode, the
    todo-protocol visibility pair, tool-availability flags, and the goal
    string for the inspection guards).
    """

    steps: list[ReActStep]
    final_answer: str
    is_code_mode: bool
    todo_protocol_required: bool = False
    todo_protocol_visible: bool = False
    file_inspection_tools_visible: bool = False
    tools_active: bool = False
    goal: str = ""
    browser_operation_mode: bool = False
    grounded_source_paths: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GuardSpec:
    """One registry entry: a guard plus its metadata.

    * ``label`` — the bracketed tag shown to the model ("secret-leak guard").
    * ``category`` — coarse grouping for telemetry / future enable flags
      ("security" / "verification" / "test-quality" / "code-smell" / "protocol").
    * ``invoke`` — takes a GuardContext, returns a guard message or None.
    * ``enabled`` — soft switch; disabled specs are skipped entirely.
    """

    label: str
    category: str
    invoke: Callable[[GuardContext], str | None]
    enabled: bool = True


def _spec_code_mode(
    label: str,
    category: str,
    fn: Callable[..., str | None],
) -> GuardSpec:
    """Build a GuardSpec for the common A-class guard signature
    ``fn(steps, final_answer, *, is_code_mode)`` that only runs in
    code mode."""

    def _invoke(ctx: GuardContext) -> str | None:
        if not ctx.is_code_mode:
            return None
        return fn(ctx.steps, ctx.final_answer, is_code_mode=ctx.is_code_mode)

    return GuardSpec(label=label, category=category, invoke=_invoke)


def _spec_security(
    label: str,
    category: str,
    fn: Callable[..., str | None],
) -> GuardSpec:
    """Build a GuardSpec for security gates that must run in every mode."""

    def _invoke(ctx: GuardContext) -> str | None:
        return fn(ctx.steps, ctx.final_answer, is_code_mode=ctx.is_code_mode)

    return GuardSpec(label=label, category=category, invoke=_invoke)


# ── B/C-class invoke wrappers (non-standard signatures) ───────────


def _browser_goal_is_ui_only(goal: str) -> bool:
    """Whether browser mode is operating only on the app under test.

    Browser mode also covers mixed workflows such as "reproduce in the
    browser, then patch the repository".  Those turns still owe normal
    workspace evidence; only explicit UI goals without development language
    receive the browser-specific exemption.
    """

    lowered = (goal or "").lower()
    ui_markers = (
        "browser ui",
        "browser interface",
        "through the ui",
        "using the ui",
        "use the browser",
        "using the browser",
        "in the browser",
        "浏览器界面",
        "浏览器 ui",
        "仅使用 ui",
        "通过 ui",
        "在浏览器中",
    )
    workspace_markers = (
        "source code",
        "codebase",
        "workspace file",
        "project file",
        "implementation",
        "patch the",
        "modify code",
        "edit code",
        "update code",
        "fix the bug",
        "run tests",
        "test suite",
        "typecheck",
        "frontend component",
        "backend module",
        "git diff",
        "commit the",
        "源代码",
        "代码库",
        "代码仓库",
        "项目文件",
        "工作区文件",
        "修改代码",
        "编辑代码",
        "修复 bug",
        "修复缺陷",
        "运行测试",
        "单元测试",
        "提交代码",
    )
    workspace_patterns = (
        # Word boundaries cover punctuation and start/end positions without
        # treating app copy such as "repository settings" as a code task.
        r"\b(?:patch|fix|refactor)\s+(?:the\s+)?(?:repo|repository|codebase)\b",
        r"\b(?:inspect|read|modify|edit|update|change)\b.{0,32}"
        r"\b(?:source code|codebase|workspace files?|project files?|"
        r"frontend|backend|component|module|implementation)\b",
        r"\b(?:repo|repository)\s+(?:code|files?|implementation)\b",
        r"\b(?:run|execute|rerun)\s+(?:the\s+)?"
        r"(?:tests?|test suite|pytest|ruff|eslint|vitest|typecheck|tsc)\b",
        r"\b(?:add|write|update)\s+(?:unit\s+|integration\s+)?tests?\b",
        r"\b(?:pytest|ruff|eslint|vitest|typecheck|git diff)\b",
    )
    has_ui_marker = any(marker in lowered for marker in ui_markers)
    has_workspace_marker = any(marker in lowered for marker in workspace_markers) or any(
        re.search(pattern, lowered) for pattern in workspace_patterns
    )
    return has_ui_marker and not has_workspace_marker


def _invoke_missing_inspection(ctx: GuardContext) -> str | None:
    if not ctx.is_code_mode:
        return None
    if ctx.browser_operation_mode and _browser_goal_is_ui_only(ctx.goal):
        # Browser turns inspect the app through browser_state/browser_get;
        # the file-inspection requirement belongs to workspace code tasks.
        return None
    return _code_mode_missing_inspection_tool_guard(
        ctx.steps,
        ctx.final_answer,
        goal=ctx.goal,
        file_tools_visible=ctx.file_inspection_tools_visible,
        grounded_source_paths=ctx.grounded_source_paths,
    )


def _invoke_inspection_answer_fragment(ctx: GuardContext) -> str | None:
    if not ctx.is_code_mode:
        return None
    return _code_mode_inspection_answer_fragment_guard(
        ctx.final_answer,
        goal=ctx.goal,
        file_tools_visible=ctx.file_inspection_tools_visible,
    )


def _invoke_incomplete_final(ctx: GuardContext) -> str | None:
    return _incomplete_final_answer_guard(ctx.final_answer)


def _invoke_false_no_tool(ctx: GuardContext) -> str | None:
    if not ctx.is_code_mode:
        return None
    return _code_mode_false_no_tool_guard(
        ctx.steps,
        ctx.final_answer,
        goal=ctx.goal,
        tools_active=ctx.file_inspection_tools_visible,
    )


def _invoke_false_tool_result(ctx: GuardContext) -> str | None:
    if not ctx.is_code_mode:
        return None
    return _code_mode_false_tool_result_guard(
        ctx.steps,
        ctx.final_answer,
        tools_active=ctx.tools_active,
    )


def _invoke_missing_write(ctx: GuardContext) -> str | None:
    if not ctx.is_code_mode or not ctx.tools_active:
        return None
    if ctx.browser_operation_mode and _browser_goal_is_ui_only(ctx.goal):
        # A browser turn proves its work through browser-action evidence
        # (see _browser_interaction_completion_guard) — its goal wording
        # ("create/edit/delete …") matches the mutation markers, but the
        # mutations land in the app under test, not in workspace files.
        # Demanding a file write here derails the model into writing
        # throwaway files just to appease this guard.
        return None
    return _code_mode_missing_write_guard(
        ctx.steps,
        ctx.final_answer,
        goal=ctx.goal,
    )


def _invoke_todo_protocol(ctx: GuardContext) -> str | None:
    if not (ctx.todo_protocol_required and ctx.todo_protocol_visible):
        return None
    return _todo_protocol_completion_guard(ctx.steps, ctx.final_answer)


def _invoke_code_mode_completion(ctx: GuardContext) -> str | None:
    if not ctx.is_code_mode:
        return None
    return _code_mode_completion_guard(
        ctx.steps,
        ctx.final_answer,
        todo_protocol_required=ctx.todo_protocol_required,
    )


def _invoke_fabricated_citation(ctx: GuardContext) -> str | None:
    # Research / chat only — code turns cite files, not URLs, and have
    # their own verification cluster.
    if ctx.is_code_mode:
        return None
    return _fabricated_citation_guard(ctx.steps, ctx.final_answer)


def _invoke_browser_completion(ctx: GuardContext) -> str | None:
    return _browser_interaction_completion_guard(ctx)


def _invoke_mixed_mode_completion(ctx: GuardContext) -> str | None:
    return _mixed_mode_completion_guard(ctx)


def _preview_labels(labels: list[str], limit: int = 3) -> str:
    preview = ", ".join(labels[:limit])
    if len(labels) > limit:
        preview += f", +{len(labels) - limit} more"
    return preview


def _final_answer_security_guard(
    ctx: GuardContext,
) -> tuple[str, str] | None:
    """Scan the final answer itself for security-sensitive code snippets.

    Trajectory guards catch unsafe code written via tools. This catches the
    separate failure mode where a chat/research answer contains a fenced code
    block or command snippet with obvious unsafe patterns.
    """
    text = ctx.final_answer or ""
    if not text:
        return None

    secret_hits = _detect_secrets_in_payload(text)
    if secret_hits:
        return (
            "secret-leak guard",
            "Cannot finish yet: the final answer itself contains a "
            f"credential-shaped value ({_preview_labels(secret_hits)}). "
            "Do not reveal API keys, access tokens, private keys, or "
            "password-like literals in the user-visible answer. Redact the "
            "value and explain how to store it safely.",
        )

    dynamic_hits = _detect_dynamic_exec_in_payload(text)
    if dynamic_hits:
        return (
            "dynamic-exec guard",
            "Cannot finish yet: the final answer includes dynamic-execution "
            f"code ({_preview_labels(dynamic_hits)}). Replace it with a safer "
            "pattern such as ast.literal_eval, explicit dispatch, or a "
            "trusted import allowlist, or clearly mark it as unsafe and do "
            "not present it as recommended code.",
        )

    shell_hits = _detect_shell_injection_in_payload(text)
    if shell_hits:
        return (
            "shell-injection guard",
            "Cannot finish yet: the final answer includes shell-injection "
            f"surface(s) ({_preview_labels(shell_hits)}). Prefer argv-list "
            "subprocess calls and avoid shell=True/os.system/os.popen in "
            "recommended code.",
        )

    deser_hits = _detect_unsafe_deser_in_payload(text)
    if deser_hits:
        return (
            "unsafe-deser guard",
            "Cannot finish yet: the final answer includes unsafe "
            f"deserialization ({_preview_labels(deser_hits)}). Recommend "
            "json.loads, yaml.safe_load, or a typed schema validator instead.",
        )

    destructive_hits = _detect_destructive_calls_in_payload(text)
    if destructive_hits:
        return (
            "destructive-call guard",
            "Cannot finish yet: the final answer includes destructive "
            f"filesystem/process calls ({_preview_labels(destructive_hits)}). "
            "Add explicit path validation, dry-run/confirmation semantics, "
            "or avoid presenting the snippet as safe production code.",
        )

    return None


# ── The registry: ordered by precedence (security → quality) ──────
# Order here REPLACES the old if-elif chain order exactly. Security
# guards fire first (highest blast radius), protocol/tool-availability
# next, then test-quality, verification, code-smell, and finally the
# catch-all completion guard.

GUARD_REGISTRY: list[GuardSpec] = [
    # ── Security cluster (highest priority) ──
    _spec_security("secret-leak guard", "security", _secret_in_payload_guard),
    _spec_security("destructive-call guard", "security", _new_destructive_call_guard),
    _spec_security("dynamic-exec guard", "security", _dynamic_exec_guard),
    _spec_security("shell-injection guard", "security", _shell_injection_guard),
    _spec_security("unsafe-deser guard", "security", _unsafe_deser_guard),
    # ── Tool-availability / inspection-evidence ──
    GuardSpec("final-answer completeness guard", "protocol", _invoke_incomplete_final),
    GuardSpec("inspection-evidence guard", "protocol", _invoke_missing_inspection),
    GuardSpec(
        "inspection-answer-fragment guard",
        "protocol",
        _invoke_inspection_answer_fragment,
    ),
    GuardSpec("tool-availability guard", "protocol", _invoke_false_no_tool),
    GuardSpec("tool-result guard", "protocol", _invoke_false_tool_result),
    GuardSpec("implementation-write guard", "protocol", _invoke_missing_write),
    GuardSpec("todo-protocol guard", "protocol", _invoke_todo_protocol),
    GuardSpec("mixed-mode completion guard", "protocol", _invoke_mixed_mode_completion),
    GuardSpec("browser-completion guard", "protocol", _invoke_browser_completion),
    # ── Research / chat quality (non-code turns) ──
    GuardSpec("citation-grounding guard", "research", _invoke_fabricated_citation),
    # ── Verification completeness ──
    _spec_code_mode(
        "language-verification guard", "verification", _language_mismatched_verification_guard
    ),
    _spec_code_mode("path-verification guard", "verification", _path_verification_policy_guard),
    _spec_code_mode("test-coverage guard", "verification", _new_python_code_without_test_guard),
    # ── Test-quality cluster ──
    _spec_code_mode("weak-test guard", "test-quality", _weak_test_assertion_guard),
    _spec_code_mode("mock-only-test guard", "test-quality", _mock_only_test_guard),
    _spec_code_mode("undocumented-skip guard", "test-quality", _undocumented_skip_guard),
    _spec_code_mode("deleted-test guard", "test-quality", _deleted_test_guard),
    _spec_code_mode("generic-test-name guard", "test-quality", _generic_test_name_guard),
    _spec_code_mode("no-assertion-test guard", "test-quality", _no_assertion_test_guard),
    # ── Interface / dependency safety ──
    _spec_code_mode(
        "signature-typecheck guard", "verification", _signature_changed_without_typecheck_guard
    ),
    _spec_code_mode(
        "wire-schema guard", "verification", _wire_schema_change_without_compat_test_guard
    ),
    _spec_code_mode(
        "dependency-declaration guard", "verification", _new_third_party_import_without_dep_guard
    ),
    _spec_code_mode("false-verification guard", "verification", _false_verification_claim_guard),
    _spec_code_mode("red-verification guard", "verification", _red_verification_observation_guard),
    # ── Code-smell cluster ──
    _spec_code_mode("comment-out-fix guard", "code-smell", _commented_out_as_fix_guard),
    _spec_code_mode("broad-except guard", "code-smell", _broad_except_suppression_guard),
    _spec_code_mode("exception-swallow guard", "code-smell", _exception_swallow_via_log_guard),
    _spec_code_mode(
        "tsconfig-include guard", "code-smell", _frontend_outside_tsconfig_include_guard
    ),
    _spec_code_mode("oversized-edit guard", "code-smell", _oversized_single_edit_guard),
    _spec_code_mode("sleep-in-prod guard", "code-smell", _sleep_in_production_guard),
    _spec_code_mode("async-without-await guard", "code-smell", _async_without_await_guard),
    _spec_code_mode("full-rewrite guard", "code-smell", _full_file_rewrite_guard),
    _spec_code_mode(
        "single-flight leader-election guard",
        "code-smell",
        _ambiguous_inflight_leader_election_guard,
    ),
    _spec_code_mode(
        "single-flight waiter-result guard",
        "code-smell",
        _destructive_waiter_result_guard,
    ),
    _spec_code_mode(
        "single-flight immutable-snapshot guard",
        "code-smell",
        _stale_immutable_waiter_snapshot_guard,
    ),
    _spec_code_mode(
        "single-flight terminal-pending guard",
        "code-smell",
        _terminal_pending_entry_leak_guard,
    ),
    _spec_code_mode(
        "single-flight test-barrier guard",
        "test-quality",
        _loader_barrier_deadlock_guard,
    ),
    _spec_code_mode("print-in-prod guard", "code-smell", _print_in_production_guard),
    _spec_code_mode("hardcoded-path guard", "code-smell", _hardcoded_personal_path_guard),
    _spec_code_mode("long-function guard", "code-smell", _long_function_guard),
    _spec_code_mode("network-in-loop guard", "code-smell", _network_in_loop_guard),
    _spec_code_mode("repeated-literal guard", "code-smell", _repeated_literal_guard),
    _spec_code_mode("magic-number guard", "code-smell", _magic_number_guard),
    # ── Catch-all completion guard (lowest priority) ──
    GuardSpec("code-mode guard", "protocol", _invoke_code_mode_completion),
]


def evaluate_guards(
    ctx: GuardContext,
    *,
    registry: list[GuardSpec] | None = None,
    recorder: Callable[[str, str], None] | None = None,
    disabled_labels: frozenset[str] | set[str] | None = None,
    categories: frozenset[str] | set[str] | None = None,
) -> tuple[str, str] | None:
    """Walk the registry in priority order; return the first
    ``(label, message)`` that fires, or ``None`` if all pass.

    Mirrors the old chain's short-circuit semantics exactly: the
    highest-priority guard that returns a non-empty message wins.

    ``recorder`` (optional) is called as ``recorder(label, category)``
    for the firing guard — this is the P1 evolution-loop telemetry
    hook. It is wrapped so a recorder failure can never break the
    ReAct loop. Defaults to None (no telemetry) so the hot path and
    tests stay side-effect-free unless a sink is explicitly injected.

    ``disabled_labels`` (optional) is a runtime kill-switch: any guard
    whose ``label`` is in this set is skipped even if its ``enabled``
    field is True. Designed for emergency response — when a guard
    fires false positives in production, an operator can set
    ``OCTOPUS_DISABLED_GUARDS="magic-number guard,long-function guard"``
    and restart the loop without a code release. Disabled hits are NOT
    recorded to telemetry (they didn't actually block anything).

    ``categories`` (optional) narrows evaluation to coarse guard groups.
    Salvage paths use this to skip mutation-specific quality checks while
    retaining security, protocol-completeness, and research-grounding gates.
    """
    specs = registry if registry is not None else GUARD_REGISTRY
    if registry is None and (categories is None or "security" in categories):
        final_answer_hit = _final_answer_security_guard(ctx)
        if final_answer_hit is not None:
            label, message = final_answer_hit
            if not disabled_labels or label not in disabled_labels:
                if recorder is not None:
                    with contextlib.suppress(Exception):
                        recorder(label, "security")
                return (label, message)
    for spec in specs:
        if not spec.enabled:
            continue
        if categories is not None and spec.category not in categories:
            continue
        if disabled_labels and spec.label in disabled_labels:
            continue
        message = spec.invoke(ctx)
        if message:
            if recorder is not None:
                with contextlib.suppress(Exception):
                    recorder(spec.label, spec.category)
            return (spec.label, message)
    return None
