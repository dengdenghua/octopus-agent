---
name: octopus-envelope-whitelist-projection-trap
description: _build_parallel_envelope 是白名单投影——新字段不显式列名就被静默丢弃；打桩整个 _call_agent_parallel 的测试永远看不见
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 61a315f7-1be7-498c-8157-ea1ae4ec56a9
  modified: 2026-08-16T16:04:45.160Z
---

`_build_parallel_envelope`（`_delegation_skills_parallel.py`）把 spawn 结果**白名单投影**成 successes/failures 条目：没在 `common` / `success_entry` 里显式列名的字段一律静默丢弃。同理 `_run_agent_graph` 的 per-node `results` dict 也是白名单。

2026-08-16 真机验证一次撞出两个同类 P1（提交 2752a143 + 6f336853）：
1. **resume 零命中**：真 successes 条目**没有 `success` 键**（能进 successes 列表本身就是成功信号），而 `SpawnResultCache.put` 要求 `result.get("success")` 为真 → 生产路径永远存不进缓存。12 条测试全手工构造带 `success: True` 的假信封，齐刷刷放过。
2. **isolate 形同虚设**：`_invoke` 挂的 `isolated`/`branch`/`diff` 没被投影 → worktree 真建真写真清理，但 diff 拿不回来 = "隔离即丢弃"。`files_touched` 因为 `common` 本就投影它而**掩盖**了这个洞。

**Why:** `monkeypatch.setattr(ds, "_call_agent_parallel", fake)` 把整个信封构造跳过了，fake 的字典形状是我自己想象的契约，不是真契约。这正是 [[octopus-agent-subagent-model-routing]] 里"stub-runner 测试给假信心"的同一个病灶换了个位置。

**How to apply:**
- 给 spawn 结果加任何新字段，**先**去 `_build_parallel_envelope` 加投影，再写测试。
- 每个新特性至少留一条测试走**真** `_call_agent_parallel`、只打桩 `call_subagent`（见 `tests/test_spawn_result_cache.py::test_real_parallel_path_stores_and_replays`）。
- 断言写在**信封条目**上，别写在内部 helper 的返回值上。
- 真机验证配方（脚本用完即删,`scratchpad/` 未进 .gitignore 别留）：`load_from_yaml("config.local.yaml")`(**不是** load_config,该函数不存在) → `build_from_config` → `make_llm_ephemeral_runner(stack.planner.router, registry=stack.executor.registry, default_model=stack.planner.planner_model)` → `set_ephemeral_role_runner`。判据要选机器可验的：resume 真命中看 `layers_run=0` 且耗时 0.00s;fan-in 真到达看下游回答里同时含两个上游哨兵词。另:`config.local.yaml` 的 deepseek-v4-flash 会回落到 -pro,不影响验证。
