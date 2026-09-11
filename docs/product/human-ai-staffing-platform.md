# 人机协同任务平台 · 产品方案

> 基于 Echo 已有的 Hub 智能体、数字员工、Project OS 与协作底座。
> 本文只描述**要建什么**，不重复已有能力的实现细节；每节都标注了可直接复用的代码位置。

---

## 0. 一句话定位

把 Echo 已有的「立项 → 组队 → 里程碑执行 → 人工验收」能力，从**单人自用**扩展成**双边市场**：
需求方发布任务，接单方（AI 团队或真人）承接，平台托管资金、**按验收指纹结算**。

---

## 1. 需求澄清

原始描述：*「用户注册后在线接单，重点支持需要真人协同完成的任务，涵盖需求发布、智能匹配、任务协同、进度跟踪、结算与评价。」*

四个必须提前钉死的前提 —— 它们决定架构，不能留到开发中决定：

| 待定项 | 建议 | 理由 |
|---|---|---|
| 履约物是「工时」还是「交付物」 | **交付物** | `acceptance.py` 的 `delivery_fingerprint` 是对里程碑产出算 sha256，天然按交付物结算。按工时结算需要工时审计，现有系统没有也不该有 |
| 结算媒介 | **积分账本（points）**，法币只做充值/提现通道 | `cloud_edge/accounts.py` 已有 `apply_points` / `ledger` 可审计账本 + `SpendBody`/`AdjustBody` 带 `idempotency_key`。直接上法币要处理清结算牌照 |
| 接单方能否是纯 AI | **能**，但必须显式标注 `provider_kind` | `initiation.py` 的 `StaffingNeed.kind` 已是 `ai\|human\|supplier`。AI 与真人混在同一池子里会摧毁信任 |
| 谁对整单负责 | **接单方单一锚点** | 否则真人协同方与 AI 互相推责，验收无法定责 |

> **关键判断：这不是招聘平台，是任务交付平台。**
> 招聘卖的是「人的时间」，交付平台卖的是「验收过的产出」。只有后者能用已有的指纹机制结算，
> 而且它顺带把「AI 能不能替代人」这个争论绕开了 —— 平台不关心谁做，只关心交付物过没过验收。

---

## 2. 目标用户角色

原始描述给了三类（发布方、接单方、协同真人）。建议扩成 **4 类 + 1 个内部角色**，
其中「接单方」必须拆开 —— 这是整个方案最重要的一个抽象决策。

### 2.1 发布方（Buyer / 需求方）

- **是谁**：个人、小团队、中小企业里「这件事没人手做」的人
- **诉求**：把一件做不完或做不了的事交出去，**且能验收**
- **关键动作**：立项 → 出资托管 → 阶段验收 → 终验收 / 拒收
- **已有支撑**：`initiation.py:ProjectProposal`（`scope` / `deliverables` / `acceptance_criteria` / `risks` / `deadline` / `max_tasks_per_phase` / `ai_budget_usd`），
  且由 LLM 先产出**可审批的立项方案**，`questions` 只收阻塞项

### 2.2 接单方（Seller / 承接方）—— 拆成两个子类

| 子类 | 身份 | 能力来源 | 责任边界 |
|---|---|---|---|
| **2.2a 真人接单者** | 自然人 / 工作室 | 技能标签 + 作品集 | 对整单负责 |
| **2.2b AI 接单团队** | Echo 数字员工 | `role_catalog.json`（职场/金融/AI4S/教育 4 组、57 单岗位 + 21 团队模板） + `ECHO-AGT-*` 身份码 | 对整单负责，但**必须挂一个人类验收人** |

> **核心抽象：订单对发布方是同一种东西** —— 不管背后是人还是 AI 团队。
> 这一个决定让平台同时吃到两样东西：AI 交付的成本红利，和真人协同的不可替代性。

### 2.3 协同真人（Co-worker / 履约协作者）

- **是谁**：被接单方（或发布方指定）拉进项目、只完成某一段的人
- **与接单方的区别**：**只对自己那段负责，不对整单验收负责**
- **已有支撑**：`memory/cowork/team_invitation_store.py`（977 行邀请机制）、`group.py` / `group_store.py`、
  `models.py:Assignment`（认领 + 租约）
- **关键设计**：协同真人的报酬**从接单方的分配里出**，不从发布方直接出 —— 否则平台变成三方合同，
  责任与结算同时失控

### 2.4 发布方侧真人（Buyer-side Human）—— 最容易被忽略的一类

- **是谁**：发布方派来提供「只有内部人才知道的信息」的人（内部数据、审批、老系统访问）
- **已有支撑**：`StaffingNeed.kind=supplier`、`involvement`（参与阶段 + 退出条件）、`phases`
- **为什么单列**：这类人**不拿钱但会阻塞进度**。平台需要为他们设计「待办催办」与超时兜底，
  而不是结算流程 —— 现有 `initiation.py` 已把 `involvement` 写成「参与阶段与退出条件」，
  正是为这类角色准备的

### 2.5 平台运营 / 仲裁（Operator，内部角色）

- **已有支撑**：`AccountPrincipal.is_operator`（admin / operator 角色）、`AdjustBody(account_id, amount, reason, idempotency_key)`
- **职责**：争议裁决、强行调账、封禁、AI 冒充真人稽查
- **必须有**：用户只列了三类角色，但**没有裁决人的双边市场会死在第一次纠纷上**

---

## 3. AI 与真人协同的运作机制

### 3.1 四种协同模式（模式决定资金流与责任归属）

| 模式 | 形态 | 典型任务 | 验收锚点 |
|---|---|---|---|
| **M1 人机接力** | AI 出初稿 → 真人审核加工 | 文案、设计、翻译 | 真人签字后的产出 |
| **M2 人机并行** | 同一里程碑拆成 AI 任务 ‖ 真人任务 | 数据清洗（AI）+ 用户访谈（人） | 两条都完成才过里程碑 |
| **M3 人在环卡点** | AI 执行到节点必须等真人确认 | 涉钱、涉法、对外发布 | `governance.py:phase_authorized` + `phase_fingerprint` |
| **M4 人主 AI 辅** | 真人交付，AI 做资料/校验 | 线下服务、上门、需资质的活 | 真人交付物 + AI 校验报告 |

**模式与既有原语的映射**：

- `model.py` 的 `TeamMode = single | swarm | cluster` → **建议扩为 `single | swarm | cluster | hybrid | human`**。
  这是让「真人执行」进入 Task DAG 的**唯一接缝**，不加这个，真人无法成为一个正式的任务节点
- `cowork/models.py:Assignment`（`agent_id` / `claimed_at` / `status` / `artifact_ref` / **`lease_expires_at`**）
  → **已实现认领 + 租约**，真人接单直接复用。「租约到期未交付自动释放」正好防占坑
- `cowork/models.py:Task.required_capabilities` → 能力匹配原语，真人技能标签复用同一套匹配逻辑

### 3.2 四条硬约束（从既有代码推出来，必须继承而不是绕开）

1. **AI 不得自称完成**
   `acceptance.py:has_delivery_content` 已拒绝空产出；`recruitment.py:66` 明令 AI
   「不得自行扩权、付款、聘用真人或**冒充已完成操作**」。这条要原样保留。

2. **真人环节必须由人类指纹确认**
   `delivery_accepted` 事件只能由人发起，且绑定 `delivery_fingerprint`。
   指纹 = sha256(milestone 规格 + 验收标准 + 全部任务状态与产出)。
   **验收后任何任务产出被改动 → 指纹失配 → 验收自动失效。**
   这是**防篡改的结算依据**，是整个平台最值钱的一块既有资产。

3. **资金 fail-closed**
   `governance.py:budget_pause_message` 的原则必须平移到真人侧：
   工时/费用回报缺失 → 暂停结算，且**「提高预算不能解除此暂停」**（原话已在代码里）。
   这条纪律比任何风控规则都重要 —— 它保证「不确定」时系统停下来，而不是猜。

4. **AI 与真人分账，不得互串**
   `initiation.py:120` 已明确「不得把人民币或总人力预算当美元 AI 预算」。反之亦然：
   AI 的 token 费用**不能**从真人的劳务额度里扣。两侧是两本账。

### 3.3 责任分配规则（一句话）

> **谁接单谁对整单负责；协同真人只对自己那一段负责；AI 永远需要一个人类验收人。**

### 3.4 AI 冒充真人的防护

- 接单方档案带 `provider_kind`（`ai` / `human` / `hybrid`），发布方可见
- AI 侧已用 `identity.py:IDENTITY_CODE_PREFIX = "ECHO-AGT"` 身份码：**不可变、无语义、不复用**
- 真人侧建议采用**同构**的 `ECHO-USR-*` 身份码，同一套纪律
  → 这样「换马甲洗评价」必须换身份码，而身份码可被限频与审计。
  **把真人的信任模型设计成和数字员工完全同构，是这个平台能自动治理的原因。**

---

## 4. 核心功能模块

| # | 模块 | 职责 | 落地依据 | 状态 |
|---|---|---|---|---|
| 1 | 账号与身份 | 注册（已有注册码门槛）、角色、实名 | `cloud_edge/accounts.py`（register/authenticate/session） | 已有，需加真人档案 |
| 2 | 需求发布 | 立项方案：范围/交付物/验收标准/风险/预算 | `initiation.py:ProjectProposal` | **已有** |
| 3 | 人员需求建模 | ai / human / supplier + 参与阶段 + 退出条件 | `initiation.py:StaffingNeed` | **已有** |
| 4 | 智能匹配 | 需求 → 候选（Hub 岗位 / 真人 / 新建） | `recruitment.py:hub_candidates`、`cowork/nominate.py` | AI 侧已有，真人侧需建 |
| 5 | 订单与报价 | 询价、报价、接单、改单、取消 | — | **需建** |
| 6 | 资金托管 | 冻结 → 释放 / 退款，全程幂等 | `accounts.py:apply_points` / `SpendBody` / `AdjustBody` | 账本已有，托管需建 |
| 7 | 任务协同 | Project→Milestone→Task DAG + 认领租约 | `projectos/model.py`、`cowork/models.py:Assignment` | **已有** |
| 8 | 进度跟踪 | PM 报告、时间线、在线状态、房间消息 | `pm.py` / `timeline.py` / `presence.py` / `room_messages.py` | **已有** |
| 9 | 验收 | 人工验收绑定交付物指纹 | `acceptance.py:delivery_fingerprint` | **已有** |
| 10 | 结算与分账 | 按指纹放款、AI/真人分账、协同方分配 | `governance.py` 原则 + `accounts.py` 账本 | **需建** |
| 11 | 评价与信誉 | 双向评价、信誉分、能力标签 | — | **需建** |
| 12 | 争议仲裁 | 申诉、举证、裁决、调账 | `accounts.py:AdjustBody(amount, reason, idempotency_key)` | **需建** |

**已有 7 / 12，需建 5** —— 其中 3 个（5、10、11）是真正的 market 部分，无法从既有代码推导。

---

## 5. 关键业务流程

### 5.1 主流程（端到端）

```
发布 → 匹配 → 报价接单 → 资金托管 → 协同执行 → 阶段验收 → 终验收 → 结算 → 评价
```

对应到已有能力：

| 环节 | 对应模块 | 已有？ |
|---|---|---|
| 发布 | `ProjectProposal`（LLM 生成可审批方案） | 是 |
| 匹配 | `hub_candidates` + `nominate` | AI 侧是 |
| 报价接单 | `Assignment` 认领 + 租约 | 骨架是 |
| 资金托管 | `apply_points` 冻结 | 账本是 |
| 协同执行 | Task DAG + `TeamMode`（需扩 hybrid/human） | 大部分是 |
| 阶段验收 | `phase_authorized` + `delivery_fingerprint` | 是 |
| 结算 | 按指纹放款 | 否 |
| 评价 | — | 否 |

### 5.2 订单状态机

```
draft → published → quoted → contracted（资金已托管）→ in_progress
                                                          ↓
                                              delivered → accepted → settled → rated
                                                          ↓
                                                      disputed → resolved | refunded

异常分支：cancelled（托管资金全额退回）、expired（限时无人接单自动关闭）
```

**关键设计**：资金状态与任务状态**必须双轨**。任务 `done` 不等于款项 `released` ——
中间必须隔着「人验收 + 指纹匹配」这一道。这是防止 AI 刷进度骗款的唯一闸门。

### 5.3 一个必须走通的典型订单（人机协同）

需求：*「给 200 条商品写 SEO 标题 + 拍 20 张实物图」*

| 里程碑 | 执行者 | 模式 | 交付物 | 验收方式 |
|---|---|---|---|---|
| M1 关键词调研 | AI（Hub: `wb_seo-expert`） | — | 关键词表 + 依据 | 发布方确认 |
| M2 标题生成 | AI | — | 200 条标题 CSV | AI 初筛 + 发布方抽检 |
| M3 实物拍摄 | **真人** | **M4 人主** | 20 张照片 + 拍摄时间水印 | 发布方逐张确认 |
| M4 质量复核 | AI + 真人抽检 | **M1 接力** | 复核报告 | 真人签字 |

每个里程碑独立验收 → 独立指纹 → 独立释放该阶段款项。
**按里程碑释放而不是终验一次放**，这是防「甲方赖账」的结构性手段，而
已有的里程碑模型天生支持它。

---

## 6. 分期落地

### P0 — 最小闭环：一条真人参与的订单能跑完并结清

- 真人注册 + 技能档案 + 接单（复用 `Assignment` 的认领/租约）
- 把 `StaffingNeed.kind=human` 从「建议」接到「可指派」
- 工时/交付回报采用 `governance.py` 的 fail-closed 原则 —— **先用 points 记账，不碰真钱**
- 人工验收 → 指纹 → 记账放款
- **验收标准：真人参与的订单可端到端结清，且账本可审计**

### P1 — 交易化

- 报价 / 接单 / 改单 / 取消、托管（冻结-释放-退款）幂等
- 双向评价 + 信誉分
- 分账：接单方 → 协同真人的自动分配

### P2 — 规模化与治理

- 争议仲裁与举证流程、履约担保/保险
- AI 冒充真人检测、实名与个税合规
- 信誉分驱动的接单限额与优先推荐

---

## 7. 必须提前定的硬约束

1. **账本只追加，余额只能通过 `apply_points` 变更**
   `SpendBody` / `AdjustBody` 都带 `idempotency_key` 是正确的设计，**任何结算路径都必须走它**，
   不允许任何地方直接改余额。
2. **提现是单向门，KYC 必须早做**
   points → 法币要实名。若留到 P1 再补，会背上历史坏账与合规风险。
3. **甲方赖账**：托管 + 按里程碑释放。不要做「终验一次放款」。
4. **乙方跑路**：`Assignment.lease_expires_at` 到期自动释放 + 信誉分 + 接单限额。
5. **AI 冒充真人**：`provider_kind` 必须由**平台侧**校验，不能由接单方自报。
6. **劳务合规定性**：真人接单者与平台是「承揽/服务」关系还是「劳动」关系，
   直接决定发票与个税处理 —— 必须在 P0 动手前定性，不能边做边想。

---

## 8. 与既有代码的三处必须改动

| 位置 | 现状 | 需要的改动 |
|---|---|---|
| `runtime/projectos/model.py:33` | `TeamMode = Literal["single","swarm","cluster"]` | 增加 `"hybrid"` / `"human"` —— 让真人执行成为合法的任务节点 |
| `runtime/projectos/recruitment.py:47` | `if need.kind != "ai": continue` —— **直接丢弃真人需求** | 新增真人候选匹配分支（按 `required_capabilities` + 技能标签 + 信誉分 + 档期） |
| `runtime/projectos/recruitment.py:66` 与 `initiation.py:88` | 明令「不得…付款、采购或**聘用真人**」 | **不要删除禁令**。改为「默认拒绝 + 经委托单显式授权的付款/聘用路径」。保留默认拒绝是整个平台资金安全的根 |

> 第 3 条尤其重要：现有代码里这两句禁令不是障碍，是**资产**。
> 平台要做的不是拿掉它，而是给它加一条**可审计、可撤销、有额度上限**的授权旁路
> —— 这正是 `phase_fingerprint` / `phase_authorized` 已经在做的事（授权绑定到指纹，
> 阶段一变授权即失效）。把同一套机制用在资金授权上即可。
