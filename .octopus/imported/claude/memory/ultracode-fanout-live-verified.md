---
name: ultracode-fanout-live-verified
description: "ultracode 零扇出真机根因=同一 system prompt 内两处反向指令(单代理声明+\"先理解再扇出\"),已修并实测 0→49 spawns"
metadata: 
  node_type: memory
  type: project
  originSessionId: 95b630e7-4eb6-4c73-9b9e-c430bbdcae71
  modified: 2026-08-16T09:54:35.440Z
---

2026-08-16 真机验证 ultracode 扇出（`scratchpad/ultracode_live_test.py`，deepseek-v4-flash / v4-pro 双模型复现）。

**结论：提示词改「倾向」不够，反向指令会赢。** 35665b1c 把编排写成默认后实测仍是 **0 spawn**——preset 文本完整送达、`run_orchestration` 在 102 个 tool spec 里、`_delegation_cap=True`，模型自己的 reasoning 里提了 13 次扇出，却 25 次全是原子读。根因两处，都在同一份 22k system prompt 内：

1. `<agent-auto-delegation-guidance>`（`_react_prompt_assembly_guidance.py`）在 preset 下方约 14 行，开头写 "Current mode is single-agent Agent/ReAct"，还有 "simple or sequential work: do it yourself" 和 "exactly one `call_agent_parallel` batch for the current turn"。**离得近的具体指令赢。** 已拆成双 variant（ultracode 专用 + 其余原文不动）。
2. preset 自己的阶段措辞（理解→设计→实现→审查）被模型引用为「按照 ultracode 指南，我应该先理解再扇出」——而"理解完一个真实代码库"永远不会在单轮预算内结束。已改成「第一次编排就发生在理解阶段」+ 明确把"先自己通读再扇出"列为禁止项。

修后同配置：iteration 4 调 `run_orchestration(n=5, rounds=3, verify, synthesize)`，**49 spawns**（31 researcher + 18 reviewer）。提交 cde52a7e，5 条新测试在修前全红。

**踩坑（复现必读）**：
- `user_context["mode"]` 必须是真实 scope tier。写 `"react"` 会回落 chat tier，根目录变成 `data/workspaces/<t>/output/final`，仓库不可达，模型整轮在找文件。要 `mode="code"` + `sandbox_mode="full"` + `workspace_path`。
- 子代理走 `run_ephemeral_role`，**绕过 `_RUNNER`**。只 stub `set_sub_agent_runner` 计不到数，必须同时 stub `set_ephemeral_role_runner`。
- stub 输出会被模型识破（"编排通道返回的是占位 stub，不可采信"）然后退回自己读——这是 harness 产物不是回归。
- 配置模型只认 `deepseek-v4-pro` / `deepseek-v4-flash`，传 `volc-kimi` 直接 http_400（见 [[kimi-k3-volcengine-agent-plan]]）。

相关：[[octopus-agent-multiagent-gap]]、[[octopus-agent-subagent-model-routing]]、[[octopus-agent-context-engineering]]
