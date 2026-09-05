# Evolution OS v2：双引擎自进化控制面

状态：已落地核心闭环 · 2026-08-25

## 引擎身份边界

Octopus-Agent 的正式双引擎只有两套：

- **Octopus Native**：项目自研、可持续自进化的主引擎，负责原生运行时、工具、Prompt、Skill、角色、工作流与治理闭环。
- **OpenAI Codex**：独立执行、外部能力基线与影子复核引擎，不被 Octopus 的自进化流程改写。

DeepSeek 是 Octopus Native 可以调用的模型供应方之一，不是第三套运行引擎。仓库内的 DSH / DeepSeek Harness 名称只用于标注历史移植来源、兼容旧插件清单与读取旧会话引用，不得作为现役产品身份、插件类别或新协议命名。新插件使用 `register_octopus` / `contributes.octopus`，新会话引用使用 `octopus-session:`。

## 目标

Evolution OS 不把“模型自己改了点东西”视为进化。一次改进只有同时满足以下条件，才允许进入真实流量：

1. 来源任务可复现，Native 与 Codex 的比较来自同一 `TaskSpec`。
2. 改进对象是可追踪的类型化候选，而不是散落在多个目录里的隐式文件写入。
3. 正确性、安全性、任务完成度等硬门禁全部通过。
4. 独立引擎在只读隔离快照中完成结构化影子复核。
5. 灰度按线程稳定分桶，失败可回滚到父候选或基线。
6. 晋升后的 Prompt、Skill、角色改进真实进入运行时，而不是只改变控制台状态。

## 核心架构

```text
真实任务 / 固定评测 / 失败轨迹
          │
          ▼
TaskSpec ── ExperimentTrial ── PairEvidence
          │                         │
          └──────────┬──────────────┘
                     ▼
        GEPA / deep_evolve / SkillForge
                     │
                     ▼
            EvolutionCandidate
          proposed → validated
                     │
                     ▼
        structured shadow (read-only)
                     │
                     ▼
          shadow → 5% → 25% → 50% → full
                     │                    │
                     ├── failure ── rollback
                     └── pass ───── promoted
                                          │
                                          ▼
                            Runtime Candidate Selector
                            Prompt / Skill / Role overlay
```

Codex 是外部能力基线和独立复核引擎，Octopus Native 是可持续进化的主体。两者不是互相覆盖：Codex 不被本项目修改；项目进化的是 Native 的 Prompt、Skill、角色与后续策略基因。

## 统一身份协议

### TaskSpec

`runtime/safety/evolution/experiment_protocol.py`

一个可配对任务由以下内容共同确定：

- `case_id`、完整目标、领域和角色；
- 环境摘要和工作区夹具摘要；
- 预算策略；
- grader/verifier 版本；
- 候选基因作用域。

`task_spec_hash` 由完整规范生成。只比较目标文本哈希会把不同环境、不同预算甚至不同验证器的回合误配，因此已从权威证据链移除。

### ExperimentTrial

每个 Trial 都保存实验 ID、引擎、trial index、seed、状态、硬门禁、指标和产物。基础设施失败单独标成 `infrastructure_failed`，不会算成某个引擎能力失败。

### PairEvidence

只有同实验、同 case、同 TaskSpec、同 trial index 且两个引擎各一条有效记录时才配对。硬门禁失败和重复引擎记录均会被排除并计数。

## 类型化候选与谱系

`runtime/safety/evolution/candidate_registry.py`

候选类型：

- `prompt`
- `skill`
- `routing`
- `workflow`
- `role`
- `policy`

候选事件追加写入 `data/evolution_candidates.jsonl`。同一个 candidate 的最新事件是当前状态，历史事件构成不可覆盖的审计谱系。

生命周期严格限制为：

```text
proposed → validated → shadow → canary → promoted
    │          │          │         │         │
    └──────────┴──────────┴─────────┴─────────┤
                                               ▼
                                 rejected / rolled_back
```

任何进入 `validated` 及以后阶段的候选都必须携带全部通过的硬门禁。不能跳过验证，也不能让软评分覆盖安全失败。

## 三个生产者已经收敛

| 生产者 | 产物类型 | 新行为 |
|---|---|---|
| GEPA | Prompt | 胜出 Prompt 写入类型化候选；缺回放证据时停在 proposed |
| deep_evolve | Role | 不再默认直接改 `SOUL.md`；产生运行时角色 overlay 候选 |
| SkillForge | Skill | 自主锻造不再直接注册 live skill；先进入候选与影子/灰度流程 |

显式人工教学仍可保留立即生成路径，因为那是用户授权操作；无人值守的自动锻造必须使用 governed rollout。

## 结构化影子复核

`runtime/safety/evolution/dual_helix_shadow.py`

影子复核要求复核引擎返回结构化 JSON：

- `verdict`: pass / fail / inconclusive
- `hard_gates.correctness`
- `hard_gates.verification`
- `hard_gates.safety`
- `hard_gates.task_satisfied`
- `evidence[]`
- `recommendations[]`

所有门禁必须显式为 true。缺字段、自然语言“看起来没问题”或 inconclusive 都不能推进候选。复核工作区使用只读隔离副本，不能污染主任务目录。

## 灰度、晋升与回滚

`runtime/safety/evolution/candidate_canary.py`

候选通过影子复核后从 5% 开始，依次进入 25%、50% 和 full。每阶段达到最小样本和成功率门槛才推进；连续失败触发自动回滚。回滚目标优先使用父候选，否则回到 baseline。

`runtime/safety/evolution/runtime_deployment.py`

运行时选择不是随机每次抽签，而是使用 `deployment_key + thread/conversation` 做稳定分桶：

- 同一线程始终命中同一分支；
- Prompt 以 addendum overlay 进入 Planner；
- Role 以内存 overlay 进入当轮 Soul，不直接修改角色文件；
- Skill 注册为受灰度可见性约束的能力，非命中会话在搜索、规划和执行阶段都看不到；
- rollback 后候选立即不可见；promoted 后对全部流量可见。

`runtime/safety/evolution/runtime_outcomes.py`

灰度证据由真实任务自动归因，不再依赖操作员手工点接口：候选首次实际影响
Planner、角色 Soul 或 Skill 执行时按 `turn_id` 登记，同一候选在一轮里只计一次；
任务完成/失败分别写入成功/失败结果，用户取消、暂停和中断属于不可评价样本，
直接丢弃而不会污染成功率。实时对话和 OpenAI 兼容接口都经过这条结算链路。

当前 fail-closed 范围：`routing`、`workflow`、`policy` 可以进入候选注册表，但在专用运行时 consumer 接入前不能点击进入灰度，避免出现“控制台显示灰度中、真实任务没有变化”的假状态。

## 真实双引擎对照

`benchmarks/run_engine_comparison.py` 使用同一组夹具、Prompt、grader 和隐藏 verifier 调度 Native/Codex，并采用 AB/BA 顺序降低先后偏差。运行结果会同时输出审计 artifact 并写入统一 ExperimentStore。

示例：

```bash
python benchmarks/run_engine_comparison.py \
  --backend native --backend codex \
  --case coding.path-boundary --case coding.concurrent-cache \
  --k 3 \
  --output benchmarks/results/evolution-head-to-head.json
```

若控制器源码、隐藏验证器来源或任务证据在运行中变化，整次 run 会标记为无效，不会生成引擎胜负结论。

## 控制面 API

| API | 用途 |
|---|---|
| `GET /api/evolution/experiments/evidence` | 严格同题配对证据 |
| `GET /api/evolution/candidates` | 类型、谱系、门禁和部署状态 |
| `POST /api/evolution/dual-helix/shadow/run` | 提交结构化影子复核 |
| `POST /api/evolution/candidates/{id}/canary/register` | 进入 5% 灰度；无 runtime consumer 时拒绝 |
| `POST /api/evolution/candidates/{id}/canary/outcome` | 离线评测导入或人工补录；在线任务会自动归因 |
| `POST /api/evolution/candidates/{id}/rollback` | 操作员强制回滚 |

这些接口属于控制面。在共享部署中全部要求 operator/admin 身份。

## UI 信息架构

`/workspace/evolution` 收敛为五个页面：

1. 总览：双引擎位置、受控证据量、候选和系统状态。
2. 实验：严格同题配对、影子复核、进化账本。
3. 候选：按类型和状态查看硬门禁、灰度阶段、真实样本量和成功率。
4. 部署：只展示 shadow/canary/promoted/rolled_back，自动刷新真实结果并提供灰度和回滚操作。
5. 安全治理：保留既有审批、策略和审计能力。

版式使用分割线、数据行和状态点，减少大圆角卡片与胶囊标签，避免 HUB 再增加一个复杂仪表盘。

## 数据与兼容性

| 数据 | 路径 |
|---|---|
| 严格实验 Trial | `data/evolution_experiments.jsonl` |
| 候选与谱系 | `data/evolution_candidates.jsonl` |
| 候选灰度状态 | `data/candidate_canary_states/` |
| 旧 ProposalLedger | `data/proposal_ledger.jsonl`（只做兼容投影） |
| 旧 GEPA addendum/variant | `data/forge_addendums/`（候选不存在时回退） |

迁移阶段保留旧账本和旧 GEPA 读取路径，但它们不再被当成严格实验，也不应成为新功能的写入目标。新生产者必须写 CandidateRegistry。

## 验收不变量

1. 不同 TaskSpec 绝不配对。
2. 基础设施失败不算引擎失败。
3. 硬门禁失败不能 validated、shadow、canary 或 promoted。
4. 候选没有运行时 consumer 时不能进入 canary。
5. 同一线程灰度分支稳定。
6. 角色灰度不改 `SOUL.md`；Prompt 灰度不改基线文件。
7. Skill 在 control cohort 不可发现也不可执行。
8. rollback 后运行时立即不可见。
9. 自动 GEPA/deep_evolve/SkillForge 不绕过统一候选生命周期。
10. 同一候选每个真实 turn 最多记录一个结果；取消、暂停和中断不记失败。

## 下一步扩展顺序

1. 为 `routing` 接账号网关与 Camouflage 的候选 consumer。
2. 为 `workflow` 接 Project/Design DAG overlay。
3. 为 `policy` 接签名策略草案与双人审批。
4. 当受控 paired 数据达到统计门槛后，再开放“Octopus 已超过 Codex”类产品文案。
