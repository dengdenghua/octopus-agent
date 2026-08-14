# Agent Notes 索引

快速导航所有设计决策记录（ADR）和提案（PROPOSAL）。

## 已实施的决策 (Implemented ADRs)

### 生物仿生架构 (Biomimetic Architecture)

- **[ADR-001: Reflex Layer（反射层）](implemented/ADR-001-reflex-layer.md)**  
  零 LLM 成本的快速路径，80% 请求 <10ms 响应

- **[ADR-002: Swarm Mesh（群体智能）](implemented/ADR-002-swarm-mesh.md)**  
  去中心化 Arm-to-Arm 通信，4x 并行加速

### 工具系统 (Tool Systems)

- **[ADR-003: 工具四阶段管线](implemented/ADR-003-tool-four-stage-pipeline.md)**  
  从 DeepSeek Harness 吸收的工具执行设计

### 配置管理 (Configuration Management)

- **[ADR-004: 配置分层系统](implemented/ADR-004-config-layering.md)**  
  基于 extends 的 YAML 配置继承和深度合并

---

## 提议中的方案 (Proposed)

_当前无提议中的方案_

---

## 如何使用

- **查看决策**: 点击上方链接阅读完整 ADR
- **提出新提案**: 复制 `README.md` 中的模板创建 `proposed/PROPOSAL-XXX.md`
- **实施后更新**: 将 `proposed/` 移动到 `implemented/` 并更新状态
- **归档决策**: 将过时的决策移动到 `archived/`

详见 [README.md](README.md) 了解完整流程。
