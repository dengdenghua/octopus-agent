# 项目质量优化 Spec

## Why

基于全项目代码评价（后端 ~590 模块 / 前端 ~250+ 组件），发现若干可量化的质量改进项：两个超长组件（1759 行 / 2091 行）影响可维护性，前端无 coverage 门槛导致测试覆盖无强制约束，工程化缺失 release 流水线 / Dependabot / SECURITY.md，后端仍有 ~84 条 bandit MEDIUM 债务和未完成的 realtime 协议修复（A2 reasoning contentIndex / B5 兄弟连接扇出）。本轮优化目标：**将评价中的待改进项逐项落地，把"良好"提升到"卓越"**。

## What Changes

### 前端组件拆分

1. **拆分 `chat-input-box.tsx`（1759 行）**：提取 Composer / MentionPicker / ResearchSourcePicker / FileAttachment 为独立文件
2. **拆分 `agent-workbench-panel.tsx`（2091 行）**：7 个内联子组件（MainComputerStatusButton / MachineScopeRail / ComputerScopeSwitch 等）提取为独立文件
3. **清理 `messages/skeleton.tsx` 11 处内联样式**：提取到 Tailwind class

### 前端测试门禁

4. **添加 vitest coverage 阈值**：`vite.config.ts` 的 `test:` 块加 `coverage.thresholds`（lines 80 / branches 75 / functions 80 / statements 80）

### Realtime 协议补全

5. **A2: reasoning contentIndex 分桶存储**：reducer 按 `contentIndex` 分桶存储 reasoning delta，而非无脑 append 到同一 `content` 字段
6. **B5: 兄弟连接扇出 delta**：realtime gateway 扇出时对兄弟连接也发 delta（带节流），而非只发终态快照

### 工程化补全

7. **添加 release 流水线**：`.github/workflows/release.yml`，tag 触发 → 构建 Docker 镜像 → 推送 GHCR
8. **添加 Dependabot 配置**：`.github/dependabot.yml`，监控 pip + npm 依赖
9. **添加 SECURITY.md**：根目录漏洞披露流程文档

### 后端安全债务

10. **清零 bandit MEDIUM 债务**：逐条审计 ~84 条 MEDIUM 告警，修复或标注 `# nosec` + 理由

## Impact

- Affected specs: `stream-ux-synergy-optimization`（A2/B5 与其同属 realtime 协议层，需确认无冲突）
- Affected code:
  - `frontend/src/components/workspace/chat-input-box.tsx` — 拆分
  - `frontend/src/components/workspace/agent-workbench-panel.tsx` — 拆分
  - `frontend/src/components/workspace/messages/skeleton.tsx` — 样式提取
  - `frontend/vite.config.ts` — coverage 阈值
  - `frontend/src/core/realtime/reducer.ts` — A2 contentIndex 分桶
  - `runtime/sensing/gateway/realtime_gateway.py` — B5 兄弟连接扇出
  - `.github/workflows/release.yml` — 新增
  - `.github/dependabot.yml` — 新增
  - `SECURITY.md` — 新增
  - `runtime/` 多文件 — bandit MEDIUM 修复

## ADDED Requirements

### Requirement: 前端组件大小约束
系统 SHALL 保证单个 `.tsx` 组件文件不超过 600 行，超出时 MUST 拆分为子组件文件。

#### Scenario: 超长组件拆分
- **WHEN** 组件文件超过 600 行
- **THEN** 提取内联子组件 / 辅助函数为独立文件，保持 import 路径兼容

### Requirement: 前端测试覆盖率门禁
系统 SHALL 在 vitest 配置中强制 coverage 阈值：lines ≥ 80%、branches ≥ 75%、functions ≥ 80%、statements ≥ 80%。

#### Scenario: 覆盖率不达标
- **WHEN** 测试运行后覆盖率低于阈值
- **THEN** CI 失败，阻止合并

### Requirement: reasoning 多段推理边界保持
系统 SHALL 按 `contentIndex` 分桶存储 reasoning delta，保持多段推理块的边界完整性。

#### Scenario: 交错到达的多段 reasoning delta
- **WHEN** 服务端交错发送 contentIndex=0 和 contentIndex=1 的 reasoning textDelta
- **THEN** 前端按 contentIndex 分桶存储，最终渲染时按 index 顺序拼接，段间边界不丢失

### Requirement: 兄弟连接实时流式体验
系统 SHALL 对同一 thread 的兄弟 WebSocket 连接扇出 delta 事件（带节流），而非仅发终态快照。

#### Scenario: 第二 tab 打开同一 thread
- **WHEN** 用户在第二个浏览器 tab 打开正在流式输出的 thread
- **THEN** 第二 tab 收到节流后的 delta 事件，看到近似实时的流式输出

### Requirement: Release 流水线自动化
系统 SHALL 在 git tag 推送时自动构建 Docker 镜像并推送到 GHCR。

#### Scenario: 发布新版本
- **WHEN** 推送 `v*.*.*` 格式的 tag
- **THEN** CI 构建多阶段 Docker 镜像，推送到 `ghcr.io/<org>/octopus-agent:<tag>`

### Requirement: 依赖更新自动化
系统 SHALL 通过 Dependabot 监控 pip 和 npm 依赖，每周检查更新。

#### Scenario: 依赖有新版本
- **WHEN** pip 或 npm 依赖发布新版本
- **THEN** Dependabot 自动创建 PR，CI 验证通过后等待人工合并

### Requirement: 漏洞披露流程
系统 SHALL 在根目录维护 SECURITY.md，描述漏洞披露流程和响应时间承诺。

#### Scenario: 安全研究员发现漏洞
- **WHEN** 研究员按 SECURITY.md 流程报告漏洞
- **THEN** 维护者在承诺时间内响应，验证后发布修复版本

## MODIFIED Requirements

### Requirement: bandit 安全扫描零 MEDIUM 债务
原状态：~84 条 MEDIUM 告警已记账，逐步 burn down。
修改为：所有 MEDIUM 告警 SHALL 修复或标注 `# nosec` + 理由注释，CI bandit 扫描 SHALL 零 MEDIUM 通过。
