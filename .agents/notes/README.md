# Agent Notes 制度

**目的**: 记录重要的设计决策，确保可追溯性和团队理解

---

## 目录结构

```
.agents/notes/
├── implemented/    # 已实施的设计决策
├── proposed/       # 提议中的设计
└── archived/       # 已废弃或过时的决策（不要编辑）
```

---

## 何时需要 Agent Note

**必须写 Agent Note 的情况**：
- 添加新的架构组件或系统
- 重大的性能优化或算法改进
- API 或接口的破坏性变更
- 安全或隐私相关的决策
- 架构权衡和取舍
- 从外部项目吸收设计（如 DSH）

**可以豁免的情况**：
- 纯粹的 bug 修复
- 代码格式或重构（不改变行为）
- 文档更新
- 测试补充

---

## Agent Note 模板

### implemented/ 模板

```markdown
# ADR-XXX: [简短标题]

**状态**: Implemented  
**日期**: YYYY-MM-DD  
**作者**: [GitHub 用户名]  
**相关 PR**: #[PR 编号]

## 背景

[描述问题或需求的上下文]

## 决策

[描述做出的决策和选择的方案]

## 理由

[解释为什么选择这个方案]

### 考虑的替代方案

1. **方案 A**: [描述] - 拒绝原因：[...]
2. **方案 B**: [描述] - 拒绝原因：[...]

## 影响

**正面影响**:
- [列出好处]

**负面影响**:
- [列出代价或权衡]

**影响的组件**:
- [列出受影响的模块]

## 实现细节

[关键的实现要点]

## 相关文档

- [链接到相关的 ADR]
- [链接到外部参考]
```

### proposed/ 模板

```markdown
# PROPOSAL-XXX: [简短标题]

**状态**: Proposed  
**日期**: YYYY-MM-DD  
**作者**: [GitHub 用户名]  
**讨论**: #[Issue 编号]

## 问题陈述

[描述要解决的问题]

## 提议的解决方案

[描述提议的方案]

## 替代方案

1. **方案 A**: [描述]
   - 优点: [...]
   - 缺点: [...]

2. **方案 B**: [描述]
   - 优点: [...]
   - 缺点: [...]

## 开放问题

- [ ] [需要回答的问题 1]
- [ ] [需要回答的问题 2]

## 下一步

[描述需要做什么来推进这个提议]
```

---

## 编号规则

### implemented/
- 格式: `ADR-XXX-short-title.md`
- 示例: `ADR-001-reflex-layer.md`
- 从 001 开始递增

### proposed/
- 格式: `PROPOSAL-XXX-short-title.md`
- 示例: `PROPOSAL-001-config-layering.md`
- 从 001 开始递增

### archived/
- 从 implemented/ 或 proposed/ 移动过来
- 保持原文件名
- 在文件头部添加归档原因

---

## 工作流程

### 1. 提议新设计
```bash
# 创建提议
vim .agents/notes/proposed/PROPOSAL-001-feature-name.md

# 提交 PR，团队讨论
git add .agents/notes/proposed/PROPOSAL-001-feature-name.md
git commit -m "proposal: add design for feature X"
```

### 2. 实施设计
```bash
# 提议被接受后，移动到 implemented/
mv .agents/notes/proposed/PROPOSAL-001-feature-name.md \
   .agents/notes/implemented/ADR-001-feature-name.md

# 更新状态为 Implemented
# 添加实施细节和 PR 链接

# 与实现代码一起提交
git add .agents/notes/implemented/ADR-001-feature-name.md
git add [实现文件]
git commit -m "feat: implement feature X (ADR-001)"
```

### 3. 归档过时的决策
```bash
# 设计被新方案替代时，移动到 archived/
mv .agents/notes/implemented/ADR-001-old-feature.md \
   .agents/notes/archived/ADR-001-old-feature.md

# 在文件头部添加归档原因
echo "**归档原因**: 被 ADR-015 替代" >> .agents/notes/archived/ADR-001-old-feature.md

# 提交归档
git add .agents/notes/archived/ADR-001-old-feature.md
git commit -m "docs: archive ADR-001 (replaced by ADR-015)"
```

---

## 索引

维护一个 `INDEX.md` 列出所有 Agent Notes：

```markdown
# Agent Notes 索引

## 已实施 (Implemented)

- [ADR-001: Reflex Layer](implemented/ADR-001-reflex-layer.md) - 反射层设计
- [ADR-002: Swarm Mesh](implemented/ADR-002-swarm-mesh.md) - Mesh 网络架构

## 提议中 (Proposed)

- [PROPOSAL-001: Config Layering](proposed/PROPOSAL-001-config-layering.md) - 配置分层

## 已归档 (Archived)

- [ADR-000: Old Design](archived/ADR-000-old-design.md) - 被 ADR-015 替代
```

---

## 最佳实践

1. **简洁明了**: 一个 ADR 一个决策，不要混杂多个主题
2. **说明理由**: 重点解释"为什么"，而不只是"是什么"
3. **记录权衡**: 诚实记录负面影响和代价
4. **保持更新**: 实施后补充实际遇到的问题和解决方案
5. **不要编辑归档**: archived/ 中的文件是历史记录，不可修改
6. **链接相关 ADR**: 使用相对链接连接相关的决策

---

## PR 检查清单

非琐碎变更的 PR 必须包含：
- [ ] Agent Note 已创建或更新
- [ ] Agent Note 链接在 PR 描述中
- [ ] Agent Note 状态正确（Proposed/Implemented）
- [ ] 索引已更新（如果是新的 ADR）

---

## 示例

参考已有的 Agent Notes：
- `.agents/notes/implemented/ADR-001-reflex-layer.md`
- `.agents/notes/implemented/ADR-002-swarm-mesh.md`

---

**建立时间**: 2026-08-14  
**灵感来源**: DeepSeek Harness Agent Notes 制度
