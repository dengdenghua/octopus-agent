# Tasks

- [x] Task 1: 编写立旗文档 `docs/vision/flag-document.md`
  - [x] 1.1 撰写 4 家仿生竞品对比矩阵（OCT-Agent / 明略 Octo / 腾讯 Octop / octopus-agent）
  - [x] 1.2 撰写"谁更仿生"证据清单，每条映射到真实代码路径（用 ls/Grep 抽查核实）
  - [x] 1.3 撰写 5 条超越路径与优先级，标注立旗与可见性为最高优先级
  - [x] 1.4 校验文档无编造事实（未实现的能力必须标注"未实现"）

- [x] Task 2: 后端可见性 trace 采集模块 `runtime/core/cerebrum/_visibility_trace.py`
  - [x] 2.1 定义 `VisibilityTrace` 数据结构与采集接口（决策点、依据、结论、时间戳）
  - [x] 2.2 提供线程安全追加与导出接口
  - [x] 2.3 编写单元测试：记录与导出正确、纯增量不改变原决策结果

- [x] Task 3: 在三个关键决策点接入 trace
  - [x] 3.1 `capability_router.activate_capabilities`：记录每个激活标签 + 命中依据（mode/关键词）
  - [x] 3.2 `_react_context_helpers._delegation_cap`：记录委派工具暴露/隐藏及原因
  - [x] 3.3 `_react_context_helpers._format_skill_catalog`：记录技能总数/保留/截断及依据
  - [x] 3.4 运行相关 pytest（capability_router、react 上下文相关）确认无回归

- [x] Task 4: 可见性事件流与持久化
  - [x] 4.1 事件桥发出 `item/visibility` 通知（`_realtime_react_stream_apply.py` 映射）
  - [x] 4.2 turn 结束时 trace 写入 thread JSONL（EventLog 能力），支持回放
  - [x] 4.3 运行 realtime 流测试确认事件推送不破坏现有 item/* 链路

- [x] Task 5: 前端工作台"可见性"面板
  - [x] 5.1 在工作台右栏新增"可见性"面板组件（默认折叠、小字、透明底）
  - [x] 5.2 消费 `item/visibility` 事件，按时间展示最近一轮 why 链（结论 + 依据）
  - [x] 5.3 运行前端 tsc/typecheck 通过

# Task Dependencies

- [Task 2] 依赖 [Task 1] 无关，可并行；[Task 2] 独立。
- [Task 3] 依赖 [Task 2]。
- [Task 4] 依赖 [Task 3]。
- [Task 5] 依赖 [Task 4]。
- [Task 1] 可独立先行完成。
