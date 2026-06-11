# HUMAN-AGENT Company Workbench：智能睡眠项目钉钉 AI COO 试点方案

> 第一版不做大而全的公司操作系统，而是先以“智能睡眠创业项目”为真实样板，接入钉钉 CLI / 钉钉开放平台，验证 AI 是否能自动管理项目进度、会议纪要、知识库、风险、专利排查、认证合规、众筹节奏、邮件草稿和公司记忆。

## 1. 产品定位

HUMAN-AGENT Company Workbench 的长期愿景仍然是“人机混合公司工作台”：用户一句话启动一个公司级项目，系统自动生成公司蓝图、预算、团队、技能装配、里程碑、风险和执行计划，并让 Agent、数字分身、真人持续协同推进。

但第一版 MVP 必须收敛，不先做完整 Agent 市场，不先做复杂 UI，也不先做全行业通用平台。第一版先做“智能睡眠项目 AI COO”。

这个试点中的产品分层是：

- **AI COO**：公司级项目管理入口，负责项目事实、会议、任务、风险、知识和提醒的统一编排。
- **专业 Agent**：岗位级能力模块，例如专利/FTO、认证合规、供应链、众筹、用户研究。
- **同事数字分身**：个人级协同助手，代表真人岗位整理上下文、生成草稿、提醒确认，但不能冒充真人。
- **钉钉**：第一版协作入口，承载群聊、会议、待办、日程、文档和提醒。
- **自有项目数据库**：项目事实来源，存储任务、风险、决策、知识、专利、认证、众筹和公司记忆。钉钉不是数据库，只是企业协作界面。

第一版要跑通的闭环：

```text
钉钉群 / 会议 / 文档 / 手动输入
        ↓
AI COO 工作流
        ↓
项目数据库
        ↓
任务 / 风险 / 知识库 / 邮件草稿 / 日报周报
        ↓
钉钉提醒和协同
```

## 1.1 第一试点：智能睡眠创业项目

本项目的第一版试点场景不是抽象创业案例，而是一个正在推进中的智能睡眠创业项目。

### 项目目标

- 12 个月内完成智能睡眠产品 MVP。
- 验证核心睡眠监测 / 助眠价值。
- 完成种子用户测试。
- 建立初步供应链、产品、App、算法和商业验证路径。
- 为后续众筹做好样机、认证、素材、用户预热和发货计划。
- 沉淀一套可复用的 AI 公司项目管理工作流。

### 第一版 AI 工作台职责

AI 工作台要成为该项目的 AI COO / AI 项目经理，重点承担：

- 项目信息记录
- 会议纪要整理
- 行动项抽取
- 钉钉待办创建
- 项目进度跟踪
- 风险识别和预警
- 知识库归档
- 专利 / FTO 初筛
- 认证 / 测试 / 量产合规提醒
- 众筹倒排计划和市场节点提醒
- 邮件草稿生成
- 日报 / 周报生成
- 公司记忆维护

第一版不追求完整 Agent 市场，也不追求复杂 UI。优先打通“钉钉群聊 / 会议 / 文档 / 手动输入 → AI 工作流 → 项目数据库 → 钉钉推送”的闭环。

## 2. 关键概念

### 2.1 Agent

Agent 是可执行的 AI 员工。它有角色、工具、技能包、知识库、行为边界、价格、能力等级和工作记录。

在智能睡眠项目第一版中，Agent 不是“人格市场商品”，而是围绕项目需要配置的岗位能力模块。它们负责信息处理、分析、草稿、提醒和风险预警。

Agent 可以承担：

- AI COO / 项目管理
- 知识库 / 会议纪要
- 用户研究
- 供应链 / BOM
- 医疗合规 / 健康宣称
- 专利 / FTO 初筛
- 认证 / 测试 / 量产合规
- 众筹 / 市场节奏
- 竞品 / 市场研究
- 财务预算
- 投融资 / BP
- 质量测试 / 可靠性
- 客服 / 众筹支持

Agent 的价值不是只由模型决定，而由以下组合决定：

- 基础模型能力
- 已装配工具
- 已装配插件
- 已装配 skill
- 行业知识库
- 历史项目经验
- 评测分数
- 产物质量
- 协作稳定性
- 风险边界清晰度

### 2.2 数字分身

数字分身是“真人岗位接口 + AI 办公代理 + 长期记忆”。

它不是虚构真人，也不能冒充真人做法律、财务、合同、医疗宣称、供应链承诺等最终决策。它用于两种场景：

1. 真人尚未招聘到：先用岗位分身占位，例如数字 COO、数字供应链助理、数字市场助理。
2. 真人已经加入：数字分身成为该真人的 AI 办公助理，帮助整理上下文、起草文档、跟任务、生成日报、同步会议纪要。

数字分身必须有授权边界：

- 可自动处理事项
- 需要本人确认事项
- 禁止处理事项
- 可代表本人回复的语气范围
- 必须回传真人审批的风险场景

## 2.2.1 同事数字分身协同

团队中的真人同事可以绑定自己的数字分身参与项目协同。

同事数字分身不是虚构真人，也不能冒充真人本人。它是“真人授权的 AI 办公代理”，用于帮助该同事整理上下文、跟进任务、生成草稿、同步进度和维护岗位记忆。

### 智能睡眠项目中的典型数字分身

| 真人岗位 | 数字分身 | 主要职责 |
| --- | --- | --- |
| CEO | 数字 CEO / COO 助理 | 汇总项目进度、风险、决策、融资和外部沟通 |
| CTO | 数字 CTO 助理 | 整理技术路线、架构决策、研发风险和跨模块依赖 |
| 电子工程师 | 数字电子分身 | 跟进电路、传感器、PCB、硬件调试和测试问题 |
| 嵌入式工程师 | 数字嵌入式分身 | 跟进固件、功耗、采样、通信和底层控制问题 |
| 软件工程师 | 数字软件分身 | 跟进 App、后端、数据平台、接口和发布计划 |
| 算法工程师 | 数字算法分身 | 跟进睡眠算法、数据采集、模型评估和准确率风险 |
| 产品经理 | 数字产品分身 | 整理 PRD、需求池、用户反馈和版本计划 |
| 结构工程师 | 数字结构分身 | 跟进 ID / 结构设计、打样、可靠性和制造风险 |

### 协同结构

```text
项目 AI COO
   ↓
岗位 Agent / 工作流
   ↓
真人同事数字分身
   ↓
真人确认 / 真人执行
```

### 授权边界

每个同事数字分身必须配置授权边界：

```ts
type DigitalTwinAuthorization = {
  id: string
  twinId: string
  projectId: string
  humanUserId: string
  allowedActions: string[]
  requireConfirmationActions: string[]
  forbiddenActions: string[]
  visibleDataScopes: string[]
  replyStyle?: string
  createdAt: string
  updatedAt: string
}
```

数字分身可以自动处理：

- 整理该同事负责的任务
- 生成该同事日报 / 周报草稿
- 汇总该同事参与会议中的行动项
- 提醒该同事任务到期或延期
- 将该同事负责模块的进展同步给项目 AI COO
- 维护岗位知识库
- 生成钉钉回复草稿
- 生成邮件草稿

数字分身必须请求本人确认：

- 代表本人回复钉钉消息
- 对外发送邮件
- 修改关键项目结论
- 确认供应商价格、交期、MOQ
- 发送投资人或客户沟通内容
- 涉及医疗、法律、财务、合同、招聘等高风险事项

数字分身禁止：

- 冒充真人
- 在未授权情况下读取私人信息
- 自动对外承诺商业条件
- 自动确认医疗 / 健康效果
- 自动签署合同或付款
- 自动进行严肃人事评价

### 钉钉指令

```text
/绑定我的数字分身
/暂停我的数字分身
/我的任务
/我的风险
/生成我的日报
/同步我的进度
/需要我确认什么
```

### 2.3 真人

真人承担 AI 不应或不能完全替代的责任：

- 公司注册、合同签署、税务、银行
- 最终商业决策
- 核心招聘和组织管理
- 真实客户访谈
- 供应商谈判、验厂、质检
- 融资、销售、人脉关系
- 法律、财务、合规高风险判断
- 专利、认证、医疗健康表达的最终专业确认

工作台要明确区分：

- Agent 能直接完成
- 数字分身能协助完成
- 必须真人完成

### 2.4 技能包 Skill

Skill 是 Agent 的可装配能力模块。它让 Agent 从“通用模型”变成“岗位专家”。

第一版智能睡眠项目优先需要：

- 会议纪要解析 skill
- 任务抽取 skill
- 风险扫描 skill
- 项目日报 skill
- 供应商邮件草稿 skill
- 专利 / FTO 初筛 skill
- 认证 / 测试 / 量产合规 skill
- 众筹倒排计划 skill
- 用户访谈和问卷 skill
- BOM / 成本估算 skill

Skill 应该带来可量化属性：

- 适用岗位
- 适用行业
- 输入要求
- 输出格式
- 工具依赖
- 质量评测项
- 使用成本
- 推荐等级
- 高风险边界

### 2.5 插件 Plugin

Plugin 是外部系统或工具能力：

- 钉钉机器人
- 钉钉待办
- 钉钉日程
- 钉钉文档
- 钉钉会议
- Web 搜索
- 浏览器
- 文件系统
- 表格
- 文档
- 邮件草稿
- 专利检索源
- 认证资料库
- 众筹平台资料

Skill 更像“会怎么做”，Plugin 更像“能用什么工具做”。

### 2.6 知识包 Knowledge Pack

知识包提升 Agent 的行业认知和岗位经验：

- 智能睡眠行业报告
- 竞品资料
- 睡眠监测技术资料
- 传感器资料
- 供应商清单
- 认证法规资料
- 专利检索结果
- 用户访谈记录
- 众筹案例
- 产品说明书
- 项目会议纪要

知识包需要标明：

- 来源
- 可信度
- 更新时间
- 适用模块
- 是否可进入模型上下文
- 是否可被检索引用

## 2.7 钉钉 CLI / 开放平台

钉钉是第一版 HUMAN-AGENT Company Workbench 的协作入口。

### 第一版接入目标

- 通过钉钉机器人接收项目群指令。
- 通过钉钉群消息推送日报、周报、风险提醒。
- 通过钉钉待办创建和同步任务。
- 通过钉钉日程读取 / 创建项目会议。
- 通过钉钉文档沉淀会议纪要、项目知识、决策记录。
- 通过钉钉会议内容或人工粘贴文本生成会议纪要。
- 后续通过 DingTalk CLI 把这些能力封装为 AI 可调用的命令行工具。

钉钉在系统中的角色不是数据库，而是企业协作界面。项目事实、任务状态、风险台账、知识索引和长期记忆应存储在 Company Workbench 自己的项目数据层中。

### 钉钉能力映射

| 工作台能力 | 钉钉能力 | 第一版处理方式 |
| --- | --- | --- |
| 项目通知 | 群机器人 / 即时通信 | P0 接入 |
| 任务管理 | 钉钉待办 | P1 接入 |
| 会议管理 | 日程 / 会议 | P1 接入 |
| 会议纪要 | 文档 / 群消息 / 手动输入 | P0 支持手动输入，P1 自动同步 |
| 知识库 | 钉钉文档 / 云盘 / 内部知识库 | P1 接入 |
| 风险提醒 | 群机器人 / 互动卡片 | P0 文本推送，P2 卡片化 |
| 邮件草稿 | 外部邮件系统 / Agent 草稿 | P0 只生成草稿，不自动发送 |
| 审批确认 | 互动卡片 / OA 审批 | P2 接入 |

## 3. 智能睡眠项目人机团队配置

### 已有真人团队

当前智能睡眠项目已有核心真人岗位：

| 岗位 | 类型 | 主要职责 |
| --- | --- | --- |
| CEO | 真人 | 公司方向、融资、资源、商业决策、关键客户与合作 |
| CTO | 真人 | 技术路线、研发架构、关键技术判断 |
| 电子工程师 | 真人 | 电路设计、传感器选型、PCB、硬件调试 |
| 嵌入式工程师 | 真人 | 固件、设备通信、功耗、采样、底层控制 |
| 软件工程师 | 真人 | App、后端、数据平台、接口集成 |
| 算法工程师 | 真人 | 睡眠算法、信号处理、模型评估、数据分析 |
| 产品经理 | 真人 | 用户需求、PRD、产品体验、版本规划 |
| 结构工程师 | 真人 | 工业设计结构、佩戴 / 放置形态、打样与结构可靠性 |

### 第一批推荐 Agent

| Agent | 优先级 | 主要职责 | 边界 |
| --- | --- | --- | --- |
| AI COO / 项目管理 Agent | P0 | 项目进度、会议、任务、风险、日报、周报、需要决策事项 | 可自动整理和提醒，关键决策需真人确认 |
| 知识库 / 会议纪要 Agent | P0 | 会议纪要、项目记忆、决策归档、文档标签、知识检索 | 可自动归档，删除 / 覆盖需确认 |
| 用户研究 Agent | P0 | 访谈提纲、问卷、用户画像、痛点归因、MVP 功能优先级 | 可自动分析，用户结论需产品 / CEO 确认 |
| 供应链 / BOM Agent | P0 | 供应商资料、BOM、报价、MOQ、交期、样品状态、供应链风险 | 可自动整理，价格 / 交期承诺需确认 |
| 医疗合规 / 健康宣称 Agent | P0 | 健康表达边界、隐私、用户授权、医疗器械风险、文案初审 | 只做风险提示，不能替代法务结论 |
| 专利 / FTO 初筛 Agent | P0 | 专利检索、竞品专利、侵权风险初筛、规避建议、专利布局建议 | 不能替代专利代理师 / 律师结论 |
| 认证 / 测试 / 量产合规 Agent | P0 | 认证清单、测试计划、送测进度、量产合规、众筹前认证检查 | 不能替代认证机构或法务意见 |
| 众筹 / 市场节奏 Agent | P0 | 众筹倒排计划、页面素材、视频、FAQ、KOL、预热、上线提醒 | 不能承诺发货、疗效或未经确认的产品能力 |

### 第二批推荐 Agent

| Agent | 优先级 | 主要职责 |
| --- | --- | --- |
| 竞品 / 市场研究 Agent | P1 | 竞品库、价格带、功能对比、用户评价、行业趋势 |
| 增长 / 销售 Agent | P1 | 种子用户招募、渠道测试、内容选题、销售话术、首批订单验证 |
| 财务预算 Agent | P1 | 项目预算、BOM 成本、打样费用、认证费用、众筹成本、现金流、runway |
| 投融资 / BP Agent | P1 | BP、投资人更新、商业模型、融资材料、数据室资料 |
| 质量测试 / 可靠性 Agent | P1 | 长测、老化、跌落、温升、佩戴舒适度、缺陷追踪 |
| 客服 / 众筹支持 Agent | P1 | 众筹上线后 FAQ、评论、用户问题、退款原因和支持者沟通草稿 |

### 协同原则

- 真人负责最终商业、技术、供应链、合规和财务决策。
- Agent 负责信息处理、记录、提醒、分析、草稿和风险预警。
- 对外邮件、供应商承诺、合同、付款、医疗健康表达必须真人确认。
- 每个真人岗位后续都可以绑定数字分身，数字分身负责该岗位上下文和任务协同。

## 4. 专项 Agent 设计

### 4.1 专利 / FTO 初筛 Agent

智能睡眠项目需要新增“专利 / FTO 初筛 Agent”，用于在产品研发早期持续排查专利风险，辅助团队做技术方案规避和自有专利布局。

该 Agent 不替代专利代理师或律师，不能给出最终法律结论。它只负责检索、归纳、风险标记、初步比对和问题清单生成。

#### 主要职责

- 检索智能睡眠相关专利。
- 检索竞品公司及上下游供应商专利。
- 按技术模块建立专利地图。
- 提取高相关专利的核心权利要求。
- 对产品方案做 FTO 初筛。
- 标记潜在侵权风险。
- 生成规避设计建议。
- 生成需要专利代理师确认的问题清单。
- 发现可申请专利点。
- 维护项目专利风险台账。

#### 第一批排查专题

| 专题 | 排查内容 |
| --- | --- |
| 传感器采集 | PPG、加速度计、压力传感、毫米波雷达、呼吸监测 |
| 睡眠分期算法 | 清醒、浅睡、深睡、REM 判断方法 |
| 睡眠评分 | 睡眠质量评分、恢复分、风险提示 |
| 设备形态 | 床旁设备、床垫、枕头、戒指、手环、贴片 |
| 助眠干预 | 声音、光、温度、振动、呼吸引导 |
| App 报告 | 睡眠报告生成、趋势分析、建议生成 |
| 数据闭环 | 采集、上传、分析、反馈、个性化模型 |
| 医疗风险 | 呼吸暂停、心率异常、血氧异常、医疗宣称相关 |

#### 输出格式

```text
专利/FTO 初筛报告

排查主题：
检索范围：
关键词：
高相关专利：
- 标题
- 申请人
- 公开号
- 国家/地区
- 法律状态
- 相关模块
- 相关权利要求摘要
- 与本项目方案相似点
- 风险等级
- 建议动作

初步结论：
- 高风险点
- 中风险点
- 低风险点
- 建议规避方向
- 需要专利代理师确认的问题
- 可考虑申请的自有专利点
```

#### 钉钉指令

```text
/专利排查
/排查传感器专利
/排查睡眠算法专利
/排查竞品专利
/查看专利风险
/生成FTO初筛报告
/生成专利布局建议
```

### 4.2 认证 / 测试 / 量产合规 Agent

智能睡眠硬件项目需要新增“认证 / 测试 / 量产合规 Agent”，用于在研发早期判断产品上市和众筹所需的认证、测试、标签、说明书、隐私和量产合规要求。

该 Agent 不替代认证机构、检测实验室、律师或专业合规顾问。它负责认证路径梳理、资料清单、节点提醒、风险登记和测试进度管理。

#### 主要职责

- 按目标市场生成认证清单。
- 判断产品是否可能涉及 CCC、SRRC、FCC、CE RED、RoHS、REACH、电池运输、隐私合规等要求。
- 根据产品功能、无线模块、电池、传感器、充电方式和销售地区生成测试计划。
- 提醒研发团队哪些设计变更会影响认证。
- 维护送测样机、测试报告、整改记录和复测状态。
- 生成认证资料清单。
- 在众筹上线前做 certification readiness check。
- 标记必须由认证机构或法务确认的事项。

#### 第一版认证检查项

| 类别 | 检查内容 |
| --- | --- |
| 中国市场 | CCC、SRRC、产品标签、说明书、隐私、健康宣称 |
| 美国市场 | FCC、UN38.3、UL / ETL 渠道要求、隐私政策 |
| 欧盟市场 | CE、RED、RoHS、REACH、WEEE、电池法规、GDPR |
| 硬件安全 | 电池、充电、温升、跌落、老化、材料接触安全 |
| 众筹上线 | 样机真实性、认证进度披露、发货时间、风险提示 |
| 健康产品边界 | 不夸大医疗效果，不承诺诊断 / 治疗效果 |

#### 输出格式

```text
认证检查报告

产品版本：
目标市场：
无线能力：
电池/充电：
是否接触人体：
是否涉及健康数据：

需要认证/测试：
- ...

缺失资料：
- ...

高风险项：
- ...

需要真人/认证机构确认：
- ...

建议下一步：
- ...
```

#### 钉钉指令

```text
/认证检查
/查看认证风险
/生成认证资料清单
/查看送测进度
/众筹前认证检查
```

### 4.3 众筹 / 市场节奏 Agent

智能睡眠项目准备众筹，因此需要新增“众筹 / 市场节奏 Agent”。该 Agent 负责从众筹上线日期倒推市场、素材、样机、认证、供应链、价格、权益、FAQ、KOL、媒体和用户预热任务。

它不是普通市场运营，而是众筹 Launch Manager。

#### 主要职责

- 制定众筹上线倒排计划。
- 维护 T-120 / T-90 / T-60 / T-30 / T-14 / T-7 / Launch / Post-launch 节点。
- 提醒样机、视频、图片、页面、价格、权益包、FAQ、风险披露是否准备完成。
- 维护预热名单、KOL 名单、媒体名单、社群名单。
- 生成众筹页面文案草稿。
- 生成视频脚本草稿。
- 生成 FAQ 和评论区回复草稿。
- 跟踪认证、供应链和发货承诺是否支持众筹页面表述。
- 上线后生成每日众筹战报。
- 将用户反馈回传产品和研发团队。

#### 众筹关键节点

| 节点 | 关键任务 |
| --- | --- |
| T-120 | 确认平台、目标市场、产品形态、认证路径、最低众筹金额 |
| T-90 | 完成可拍摄样机、视频脚本、页面大纲、价格权益初稿 |
| T-60 | Landing page、邮件名单、社群、KOL、媒体素材包、FAQ 初稿 |
| T-30 | 页面初稿、视频初剪、产品图、发货时间、物流税费、售后政策 |
| T-14 | 页面审核、预热邮件、KOL 排期、PR 稿、首日支持者名单 |
| T-7 | 最终检查、客服话术、评论区预案、风险披露、上线演练 |
| Launch | 首小时转化、评论、付款、媒体发布、KOL 执行、战报 |
| Post-launch | 每日战报、用户问题、退款原因、生产 / 认证 / 发货更新 |

#### 钉钉提醒指令

```text
/众筹状态
/众筹还差什么
/生成众筹倒排计划
/生成众筹页面大纲
/生成众筹视频脚本
/生成FAQ
/查看上线风险
/生成今日市场任务
/生成众筹战报
```

#### 输出示例

```text
众筹状态：黄色预警

距离计划上线：45 天

已完成：
- 产品定位初稿
- 样机功能 demo
- 目标用户画像

未完成：
- 众筹视频脚本
- Landing page
- 早鸟价格
- 认证进度说明
- FAQ
- KOL 名单

高风险：
1. 认证路径尚未确认，可能影响页面承诺。
2. 发货时间缺少供应链依据。
3. 医疗 / 助眠表达需要合规检查。

本周必须完成：
- 确认目标平台和目标市场
- 输出众筹页面大纲
- 确认首批生产成本
- 确认早鸟价格和权益包
```

## 5. 智能睡眠项目核心数据模型

第一版数据层要先服务真实项目管理闭环，而不是抽象平台化。以下模型是 P0/P1 的候选 wire model，后续可以映射到现有 `team_tasks`、memory、blackboard 和 artifacts。

### 5.1 项目与任务

```ts
type Project = {
  id: string
  name: string
  description: string
  industry: string
  stage: "idea" | "validation" | "prototype" | "pilot" | "commercial"
  ownerId: string
  dingTalkGroupId?: string
  createdAt: string
  updatedAt: string
}

type ProjectMilestone = {
  id: string
  projectId: string
  title: string
  description?: string
  targetDate: string
  status: "not_started" | "in_progress" | "blocked" | "done"
  ownerId?: string
}

type ProjectTask = {
  id: string
  projectId: string
  milestoneId?: string
  title: string
  description?: string
  ownerName?: string
  ownerUserId?: string
  source: "manual" | "meeting" | "risk" | "milestone" | "agent"
  dueDate?: string
  status: "todo" | "doing" | "blocked" | "done" | "cancelled"
  priority: "low" | "medium" | "high" | "urgent"
  dingTodoId?: string
  createdAt: string
  updatedAt: string
}
```

### 5.2 会议、决策、风险、知识、邮件

```ts
type ProjectMeeting = {
  id: string
  projectId: string
  title: string
  startTime?: string
  endTime?: string
  source: "dingtalk" | "manual" | "upload"
  transcript?: string
  summary?: string
  actionItemIds: string[]
  riskIds: string[]
  docUrl?: string
  createdAt: string
}

type ProjectDecision = {
  id: string
  projectId: string
  meetingId?: string
  title: string
  content: string
  decisionMaker?: string
  reason?: string
  impact?: string
  createdAt: string
}

type ProjectRisk = {
  id: string
  projectId: string
  title: string
  description?: string
  category:
    | "product"
    | "hardware"
    | "algorithm"
    | "supply_chain"
    | "compliance"
    | "business"
    | "finance"
    | "team"
    | "patent"
    | "certification"
    | "crowdfunding"
  level: "low" | "medium" | "high" | "critical"
  source: "meeting" | "task" | "manual" | "agent" | "document"
  ownerName?: string
  mitigation?: string
  dueDate?: string
  status: "open" | "monitoring" | "resolved" | "ignored"
  createdAt: string
  updatedAt: string
}

type ProjectKnowledgeItem = {
  id: string
  projectId: string
  title: string
  content?: string
  source: "meeting" | "document" | "chat" | "upload" | "web" | "manual"
  tags: string[]
  relatedTaskIds?: string[]
  relatedRiskIds?: string[]
  relatedDecisionIds?: string[]
  docUrl?: string
  createdAt: string
  updatedAt: string
}

type ProjectEmailDraft = {
  id: string
  projectId: string
  subject: string
  body: string
  recipient?: string
  scenario: "supplier" | "investor" | "advisor" | "customer" | "partner"
  status: "draft" | "approved" | "sent" | "cancelled"
  createdBy: "agent" | "human"
  createdAt: string
}
```

### 5.3 数字分身

```ts
type DigitalTwinProfile = {
  id: string
  projectId: string
  humanUserId: string
  humanName: string
  role: string
  twinName: string
  description?: string
  status: "active" | "paused" | "disabled"
  createdAt: string
  updatedAt: string
}

type DigitalTwinActivityLog = {
  id: string
  twinId: string
  projectId: string
  actionType: string
  inputSummary?: string
  outputSummary?: string
  status: "auto_done" | "waiting_confirmation" | "confirmed" | "rejected" | "failed"
  confirmedBy?: string
  createdAt: string
}
```

### 5.4 专利 / FTO

```ts
type PatentSearchTopic = {
  id: string
  projectId: string
  title: string
  module:
    | "sensor"
    | "algorithm"
    | "hardware_structure"
    | "app_report"
    | "product_intervention"
    | "data_pipeline"
    | "regulated_claim_risk"
  keywordsZh: string[]
  keywordsEn: string[]
  status: "not_started" | "searching" | "reviewing" | "done"
  ownerName?: string
  createdAt: string
  updatedAt: string
}

type PatentRecord = {
  id: string
  projectId: string
  topicId?: string
  title: string
  applicant?: string
  publicationNumber?: string
  applicationNumber?: string
  country?: string
  publicationDate?: string
  legalStatus?: string
  source: "cnipa" | "wipo" | "google_patents" | "uspto" | "other"
  url?: string
  abstract?: string
  keyClaimsSummary?: string
  relatedModule?: string
  relevance: "low" | "medium" | "high"
  riskLevel: "low" | "medium" | "high" | "critical"
  notes?: string
  createdAt: string
  updatedAt: string
}

type PatentRisk = {
  id: string
  projectId: string
  patentRecordId?: string
  title: string
  relatedProductFeature: string
  riskLevel: "low" | "medium" | "high" | "critical"
  reason: string
  suggestedDesignAround?: string
  requiresPatentAttorneyReview: boolean
  status: "open" | "reviewing" | "mitigated" | "accepted" | "closed"
  createdAt: string
  updatedAt: string
}

type InventionDisclosure = {
  id: string
  projectId: string
  title: string
  inventors: string[]
  technicalProblem: string
  technicalSolution: string
  advantages?: string
  relatedTasks?: string[]
  status: "draft" | "internal_review" | "attorney_review" | "filed" | "abandoned"
  createdAt: string
  updatedAt: string
}
```

### 5.5 认证和众筹

```ts
type CertificationRequirement = {
  id: string
  projectId: string
  productVersion: string
  market: "china" | "us" | "eu" | "uk" | "japan" | "other"
  category:
    | "ccc"
    | "srrc"
    | "fcc"
    | "ce_red"
    | "rohs"
    | "reach"
    | "battery"
    | "privacy"
    | "labeling"
    | "health_claim"
    | "other"
  title: string
  description?: string
  status: "unknown" | "needed" | "not_needed" | "in_progress" | "passed" | "failed" | "waived"
  evidenceUrl?: string
  ownerName?: string
  dueDate?: string
  requiresExpertReview: boolean
  createdAt: string
  updatedAt: string
}

type CertificationTestRecord = {
  id: string
  projectId: string
  requirementId?: string
  productVersion: string
  testName: string
  labName?: string
  sampleId?: string
  status: "planned" | "submitted" | "testing" | "passed" | "failed" | "retest_needed"
  reportUrl?: string
  issueSummary?: string
  nextAction?: string
  createdAt: string
  updatedAt: string
}

type CrowdfundingCampaign = {
  id: string
  projectId: string
  platform?: "kickstarter" | "indiegogo" | "jd" | "taobao" | "other"
  targetMarket: string[]
  plannedLaunchDate?: string
  fundingGoal?: number
  currency?: string
  status: "planning" | "prelaunch" | "review" | "live" | "fulfilled" | "cancelled"
  createdAt: string
  updatedAt: string
}

type CrowdfundingMilestone = {
  id: string
  campaignId: string
  phase: "T-120" | "T-90" | "T-60" | "T-30" | "T-14" | "T-7" | "Launch" | "Post-launch"
  title: string
  dueDate?: string
  status: "todo" | "doing" | "blocked" | "done"
  ownerName?: string
  riskLevel: "low" | "medium" | "high" | "critical"
  createdAt: string
  updatedAt: string
}

type CrowdfundingAsset = {
  id: string
  campaignId: string
  type:
    | "landing_page"
    | "video_script"
    | "campaign_page"
    | "product_photo"
    | "faq"
    | "press_kit"
    | "kol_list"
    | "email_sequence"
    | "reward_tier"
    | "risk_disclosure"
  title: string
  status: "not_started" | "draft" | "reviewing" | "approved" | "published"
  url?: string
  ownerName?: string
  createdAt: string
  updatedAt: string
}

type CrowdfundingDailyReport = {
  id: string
  campaignId: string
  date: string
  traffic?: number
  conversionRate?: number
  backers?: number
  pledgedAmount?: number
  refundCount?: number
  topQuestions?: string[]
  risks?: string[]
  nextActions?: string[]
  createdAt: string
}
```

## 6. 与现有架构结合

现有能力可以这样映射：

| 产品概念 | 现有基础 | 第一版处理 |
| --- | --- | --- |
| 智能睡眠项目空间 | team room / workspace | 新增项目数据层，先不重做团队页 |
| 项目任务 | team_tasks | 可映射 ProjectTask，后续同步钉钉待办 |
| 自动执行 | TeamRunner / subagents | 先做 workflow，后续再进入 TeamRunner |
| 技能装配 | skills / plugins | P0 固定内置技能，不做市场 |
| 数字分身 | agents/new 数字分身入口 | P2 增加授权边界和钉钉指令 |
| 公司记忆 | blackboard / memory | P0 先写项目知识、会议、决策 |
| 产物库 | produced_artifacts | 存会议纪要、日报、邮件草稿、报告 |
| 可观测 | Agent Workbench | P4 后再做 Web 控制台和 Agent 电脑集成 |

第一版不要强行把所有东西都塞进聊天右侧栏。先让数据模型、工作流和钉钉入口跑起来，再把 Web 控制台补上。

## 7. MVP 路线：智能睡眠钉钉 AI COO

### P0：本地可运行原型

目标：

- 不依赖复杂 UI。
- 可以用命令行或本地 API 跑通项目管理闭环。

任务：

- 建立项目数据模型。
- 初始化智能睡眠项目。
- 支持手动输入会议文本。
- 生成会议纪要。
- 抽取任务。
- 抽取风险。
- 生成日报。
- 生成邮件草稿。
- 生成专利 / FTO 初筛报告草稿。
- 生成认证检查清单。
- 生成众筹倒排计划。

验收标准：

- 输入一段会议文本后，系统能输出结构化会议纪要、任务、风险和知识库条目。
- 系统能根据已有任务和风险生成项目日报。
- 系统能生成供应商邮件草稿。
- 输入一个技术方案，系统能生成专利排查关键词和 FTO 初筛框架。
- 输入产品版本和目标市场，系统能生成认证检查清单。
- 输入众筹计划上线日期，系统能生成众筹倒排计划。

### P1：钉钉机器人接入

目标：

- 在钉钉项目群中使用 AI COO。

支持指令：

```text
/项目状态
/记录会议纪要
/今日风险
/生成日报
/生成供应商邮件
/专利排查
/认证检查
/众筹状态
/众筹还差什么
```

验收标准：

- 用户在钉钉群输入指令后，AI COO 能返回正确内容。
- 会议纪要能自动生成任务和风险。
- 日报能基于真实项目数据生成。
- 众筹状态能显示当前阶段缺失事项。

### P2：钉钉待办、日程、数字分身接入

目标：

- 把行动项变成真实钉钉待办。
- 把项目会议和里程碑同步到钉钉日程。
- 支持同事绑定自己的数字分身。

支持：

```text
/绑定我的数字分身
/我的任务
/我的风险
/生成我的日报
/需要我确认什么
```

### P3：知识库、专利、认证、众筹资料库

目标：

- 会议纪要、项目决策、风险台账、专利记录、认证记录、众筹素材自动沉淀到知识库。

支持查询：

- 我们为什么选择某个传感器方案？
- 当前最大风险是什么？
- 上次供应链会议决定了什么？
- 当前有哪些专利风险？
- 众筹上线前还缺什么？
- 哪些认证还没确认？

### P4：Web 控制台

页面：

- 项目总览
- 任务
- 风险
- 会议
- 知识库
- 专利/FTO
- 认证/测试
- 众筹计划
- 邮件草稿
- 日报周报
- 数字分身
- 钉钉集成配置

### P5：通用化为 Company Workbench

目标：

- 从智能睡眠项目抽象成通用公司项目模板。

支持：

- 其他创业项目
- 其他行业模板
- 多项目管理
- Agent 装配市场
- 数字分身授权
- 预算联动
- 长期成长系统

## 8. 第一批 Codex 开发任务

### Task 1：创建项目数据模型

实现：

- Project
- ProjectMilestone
- ProjectTask
- ProjectMeeting
- ProjectDecision
- ProjectRisk
- ProjectKnowledgeItem
- ProjectEmailDraft

### Task 2：实现智能睡眠项目初始化脚本

输出：

- 创建 Project。
- 创建默认里程碑。
- 创建默认知识库目录。
- 创建默认风险分类。
- 创建第一批任务。

### Task 3：实现会议纪要解析 workflow

输入：

```ts
{
  projectId: string,
  meetingTitle: string,
  transcript: string
}
```

输出：

- ProjectMeeting
- ProjectDecision[]
- ProjectTask[]
- ProjectRisk[]
- ProjectKnowledgeItem[]

### Task 4：实现项目日报 workflow

输出：

- 今日进展
- 延期事项
- 新增风险
- 需要负责人更新的任务
- 需要 David 决策的事项
- 明日重点

### Task 5：实现风险扫描 workflow

输出：

- 新增风险
- 升级风险
- 已缓解风险
- 需要提醒的负责人

### Task 6：实现邮件草稿 workflow

支持：

- supplier
- investor
- advisor
- customer
- partner

第一版只生成草稿，不自动发送。

### Task 7：实现钉钉机器人 webhook 接入

支持：

```text
/项目状态
/今日风险
/生成日报
/记录会议纪要
/生成供应商邮件
```

### Task 8：实现权限和安全边界

规则：

- AI 可以自动生成纪要、任务、风险、日报。
- AI 可以自动创建内部提醒。
- AI 不能自动发送对外邮件。
- AI 不能自动承诺价格、合同、交期、医疗效果。
- 涉及法律、财务、合同、医疗宣称、融资、供应链签约、专利结论、认证结论、众筹发货承诺的事项必须标记为“需要真人确认”。

### Task 9：实现同事数字分身绑定

支持：

- 创建同事数字分身。
- 设置授权边界。
- 设置可见数据范围。
- 暂停 / 启用数字分身。
- 查询数字分身状态。

### Task 10：实现专利 / FTO 初筛 Agent

支持：

- 创建专利检索专题。
- 为每个专题生成中英文关键词。
- 记录检索来源和检索式。
- 保存高相关专利。
- 摘要核心权利要求。
- 标记与项目方案的相似点。
- 生成风险等级。
- 生成规避设计建议。
- 生成需要专利代理师确认的问题清单。
- 生成可申请专利点草稿。

### Task 11：实现认证 / 测试 / 量产合规 Agent

支持：

- 根据产品版本和目标市场生成认证清单。
- 维护认证要求和测试记录。
- 标记需要专家确认的事项。
- 根据众筹上线日期提醒认证风险。
- 生成认证检查报告。

### Task 12：实现众筹 / 市场节奏 Agent

支持：

- 创建众筹计划。
- 设置计划上线日期。
- 自动生成 T-120 / T-90 / T-60 / T-30 / T-14 / T-7 / Launch / Post-launch 节点。
- 自动生成每个节点的任务。
- 生成众筹页面大纲、视频脚本、FAQ、KOL 列表、邮件预热计划草稿。
- 每天提醒当前阶段还缺什么。
- 上线后生成每日众筹战报。

## 9. 保留但后移的长期愿景

以下内容不删除，但明确标记为 P5 之后的长期愿景，不进入智能睡眠项目钉钉 AI COO 的第一版 MVP：

- 完整 Agent 市场
- Agent 简历页
- 能力评级市场化
- 复杂人格系统
- 星座 / MBTI / 命理标签
- 自进化成长
- 多公司 workspace
- 完整预算商城
- 真人增强复杂招聘体系
- Agent 电脑终端 / 浏览器 / Diff

第一版必须先验证：

> 智能睡眠项目能否通过钉钉 AI COO，把会议、任务、风险、知识、专利、认证、众筹和邮件草稿管理起来。

只要这个闭环跑通，再抽象成通用 HUMAN-AGENT Company Workbench。

## 10. 风险与边界

### 10.1 不能伪装真人

数字分身必须明确标识为 AI 辅助。不能让用户误以为它是真人在亲自执行。

### 10.2 高风险任务必须真人确认

法律、财务、合同、招聘、医疗、安全、融资、供应链签约、专利结论、认证结论、众筹发货承诺等场景必须有真人确认。

### 10.3 人格不能替代能力

MBTI、星座、命理等只能用于沟通风格和产品趣味，不能用于真实能力评分、薪资定价和严肃招聘判断。

### 10.4 知识包必须可追溯

Agent 价值可以来自知识包，但知识来源、更新时间、可信度必须透明。

### 10.5 自进化必须可审计

Agent 的能力变化、失败记录、用户反馈、升级依据需要留痕，避免“黑箱升级”。

## 11. 一句话总结

第一版不是做一个完整 AI 公司操作系统，而是用智能睡眠项目作为真实样板，先让 AI COO 在钉钉里管理会议、任务、风险、知识、专利、认证、众筹和邮件草稿。

这个闭环跑通后，再把项目数据模型、工作流、Agent 装配、数字分身授权和长期记忆抽象成通用 HUMAN-AGENT Company Workbench。
