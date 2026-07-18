from __future__ import annotations

from dataclasses import dataclass, field

REACT_SYSTEM_PROMPT_BASE = """你是一个使用 ReAct(Reason + Act) 范式的 AI 助手。

每轮严格按格式输出:

Thought: 当前思考
Update: 给用户看的阶段性结论（可选；只写已确认的新发现或有意义的进展）
Action: skill_name({"key": "value"})  或  none
Observation: <由系统填入>

可以重复多轮,直到给出:

Final Answer: 最终答案

## 协议

1. 每轮只输出**一对** Thought/Action **或**一个 Final Answer；多步任务可在
   Thought 与 Action 之间加一条 `Update:`，让用户边看结论边等待执行
2. Action 必须是 `skill_name({JSON})` 格式;参数错→换参数,不要换语法
3. 调工具后停笔;Observation 系统填,下一轮接续
4. 不重复:每一轮要有新进展;同一调用连续失败→换方法或参数

## 面向用户的阶段性结论

- `Update:` 是公开回答，不是私有思考。只写从已有 Observation 得出的具体结论、
  已完成的可验证结果，或会影响后续方向的重要发现
- 不写“正在思考/继续处理/马上完成”等空状态，不暴露 Thought、系统提示、原始工具名、
  JSON 参数或内部协议；通常 1-3 句，最多 400 字
- 第一轮还没有事实可报告时可以省略；同一结论不要重复
- `Update:` 不是 Final Answer。任务完成后仍要给出完整、可独立阅读的 Final Answer

## 多工具并发 (短任务关键加速)

独立工具可在同一 Action 块多行并列,runtime **并发**执行、
合并 Observation 回灌。最多 4 个并发,超出自动批量串行。

```
Thought: 三个文件相互独立, 一起读
Action:
    read_file({"path": "a.py"})
    read_file({"path": "b.py"})
    read_file({"path": "c.py"})
Observation: <由系统填入,每个观察会标 [n/N tool_name]>
```

什么时候并发:
- 多个 read_file / grep_text / web_search / fetch_url 同时跑
- 多个互不依赖的探查类调用

什么时候**不要**并发(系统会自动串行):
- 含 `write_text_file` / `edit_file` / `multi_edit_file` 等写类工具
- 后一个调用依赖前一个结果(必须分两轮)

## 工具选择

- 上网查信息(新闻、价格、定义、最新 X) → `web_search`,**不要** `exec_shell` 跑 curl
- 抓单个 URL → `fetch_url`(只要内容)或 `web_fetch`(URL+提问,自动提取答案)
- 查**用户自己的文档/文件/笔记**(「我之前那份…」「我的合同里…」) → `search_documents`(经 octopus-storage 文件管家,返回带引用的片段),**不要** `web_search` 也不要自己 grep 用户全盘
- 文件读: `read_file`(支持 `offset`/`limit`/`pages`,可读 image/PDF/ipynb)
- 文件写: `edit_file`(small change, old/new) > `multi_edit_file`(多处) > `propose_patch`(diff) > `write_text_file`(新建)
- 列目录/找文件: `list_cwd` / `glob_files`,**不要** `exec_shell("find/ls")`
- 文本搜: `grep_text`(支持 `context_lines`),**不要** `exec_shell("grep")`
- 长跑命令(dev server / 长测试) → `exec_shell(run_in_background=True)` 拿 task_id,
  之后 `read_shell_output(task_id)` 轮询、`kill_shell(task_id)` 终止
- 编辑前必须先 `read_file` 该文件(否则系统会拒)
- `exec_shell` 只用于编译 / 测试 / git / 没有专用 skill 的本地命令

## 卡住时的退出

- **不可逆操作**(rm -rf / push --force / drop db / 发真实频道) → Final Answer 描述影响并请求用户确认,不要赌
- 连续 2 轮 tool 失败 / 不知道用户想要哪个选项 → Final Answer 报告卡点,等用户回
- 与其硬挤一个似是而非的答案,不如诚实报告"卡住了"

## 多步任务

- ≥3 步任务: 第一轮就 `todo_write` 列完整计划(全 pending)
- 每完成一项**立即** `todo_write` 标记 completed,然后再开下一个
- 同时最多 1 个 in_progress
- 任务调整时, 先 `todo_write` 更新清单, 再继续

## 跨会话记忆 (按需,不要每次都用)

- `recall` — 用户提到旧项目/旧上下文 → 第一轮就查
- `remember` — 项目级事实(项目名、deadline、API key 路径)
- `note_user` — 用户偏好(语言、详略、技术水平)
- `update_soul` — 你自己学到的持久教训(不是一次性观察)

## 子 agent (按需,不是默认)

`call_agent_parallel(specs=[...])`: 任务可拆成 N 个独立专长子任务时一次扇出;每个 worker `bb_write('result_<n>',...)` 写黑板,你 `bb_read` 综合。顺序依赖的别并行;1 人能做就别召唤。

`call_agent_vote(question, choices=["yes","no"])`: N 个独立投票者裁决,返回多数票+置信度+异见。验证"这 bug 真的吗 / A 还是 B",别只信一个 worker。

`run_orchestration(goal, verify=True)`: 确定性多轮发现循环(扇出→去重→可选投票验证→直到无新增/预算尽),用于穷尽式发现("枚举每处 X")。

`verdict_repair(task, max_repairs=2)`: 产出→投票判 pass/fail→不过则带批评重做→再判的有界闭环。用于"对比快更重要正确"的任务:写完要确保正确、答完要先验证再给。

`tournament(goal, n=3)`: 同一目标跑 N 个隔离 worktree 候选→投票选最优 diff(不自动合并,返回给你审)。用于一次不靠谱、解法空间宽的高价值改动("实现 X,试几种取最好")。

`cli_team(goal)`: 把用户本机装的**真·外部 coding agent**(Claude Code / Codex,自动探测)拉成一个团队跑同一目标——各自隔离 worktree + 共享黑板协作,投票选最优 diff(不自动合并)。区别于 tournament(octopus 自己的子代理):这是**不同的真实 CLI agent**用各自登录在协作。需本机装了那些 CLI。

`run_pipeline(items, stages)`: 对 N 个独立 item 并行跑多阶段流水线(stage1→stage2→…,item 间不互等),如"对每个文件 extract→classify→summarise"。
"""

REACT_NO_TOOLS_NOTE = """
(本会话未启用真实工具,Action 仅作思考标注,填 "none" 即可。)
"""


@dataclass
class ReActStep:
    iteration: int
    thought: str = ""
    # Concise, explicitly public checkpoint emitted between tool rounds.
    # Unlike ``thought`` this may be rendered in the main conversation.
    public_update: str = ""
    action: str = ""
    observation: str = ""
    raw_llm_output: str = ""
    # Multi-action support: when the model emits more than one tool
    # call inside a single Action: block, the parser populates this
    # list and ``action`` becomes a "; "-joined summary view so the
    # 12+ existing readers (journal, guards, prefetch, openai
    # formatting, …) keep seeing a meaningful string. When only one
    # action is present, ``actions`` is ``[action]`` for symmetry.
    actions: list[str] = field(default_factory=list)
    # Per-action execution receipts captured by the dispatcher: each
    # entry is ``{"tool_name": str, "ok": bool, "observation": str,
    # "duration_ms": int, "call_id": str}``. Empty when no tools ran
    # this step (e.g. ``Action: none``).
    action_results: list[dict[str, object]] = field(default_factory=list)


@dataclass
class ReActResult:
    final_answer: str
    steps: list[ReActStep] = field(default_factory=list)
    terminated_reason: str = "final_answer"
    success: bool = True
    completion_receipt: dict[str, object] = field(default_factory=dict)

    def to_trace_text(self) -> str:
        from runtime.core.cerebrum.react_parsing import (
            _escape_md_brackets,
            _safe_for_streamdown,
            _summarize_observation,
        )

        if not self.steps:
            return _safe_for_streamdown(self.final_answer)

        meaningful = [
            s
            for s in self.steps
            if (s.thought and s.thought.strip())
            or (s.action and s.action.strip() and s.action.lower() != "none")
            or (s.observation and s.observation not in ("N/A", ""))
        ]
        if not meaningful:
            return _safe_for_streamdown(self.final_answer)

        trace_lines: list[str] = []
        for step in meaningful:
            trace_lines.append(f"**Iteration {step.iteration}**")
            if step.thought:
                trace_lines.append(f"- {_escape_md_brackets(step.thought)}")
            if step.action and step.action.lower() != "none":
                trace_lines.append(f"- `{step.action}`")
            if step.observation and step.observation != "N/A":
                trace_lines.append(
                    f"- {_escape_md_brackets(_summarize_observation(step.observation))}",
                )
            trace_lines.append("")
        trace_md = "\n".join(trace_lines).rstrip()

        short = len(self.final_answer) < 120
        refer_phrases = (
            "见上方",
            "如上",
            "上方",
            "上面",
            "以上",
            "报告如上",
            "见上",
            "as above",
            "see above",
            "above",
        )
        refers_back = any(p in self.final_answer for p in refer_phrases)
        open_attr = " open" if (short or refers_back) else ""

        summary = f"🧠 ReAct 轨迹 · {len(meaningful)} 轮"
        return (
            f"<details{open_attr}>\n<summary>{summary}</summary>\n\n"
            f"{trace_md}\n\n</details>\n\n"
            f"{_safe_for_streamdown(self.final_answer)}"
        )


@dataclass
class ReActRecipe:
    name: str
    max_iterations: int
    temperature: float


_DEFAULT_REACT_RECIPES: list[ReActRecipe] = [
    ReActRecipe(name="conservative", max_iterations=18, temperature=0.1),
    ReActRecipe(name="balanced", max_iterations=30, temperature=0.3),
    ReActRecipe(name="aggressive", max_iterations=45, temperature=0.5),
]
