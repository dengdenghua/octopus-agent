---
name: 🌱 Feature / design proposal
about: 想加能力 / 想改架构 · 先讨论再写 PR
title: "[feat] "
labels: enhancement
---

## 要解决的问题

<!-- 你现在**不能**做什么?或者做起来很难? -->

## 建议方案

<!-- 一段自然语言,不需要给代码。 -->

## 拒绝的 alternatives

<!-- 你想过几个方案?哪个更差?为什么? -->

## 边界

- 这条改动会动**哪些器官 / 哪些文件**?
- 会不会触发哪条 [invariant](../docs/invariants.md)?
- 对**未运行这条功能**的用户有啥变化吗?

## 怎么测

<!-- 新测试长什么样?手测场景是什么? -->

---

**注意**:
- `call_agent_parallel` / `deep_evolve` / `Mantle ssh/k8s` 这类已经做完 · 加更多的 variant 先看 [docs/agent-capabilities.md](../docs/agent-capabilities.md) 确认没重复
- 涉及架构改动(`ToolExecutor` / `GraphRuntime` / 不变量)请先开这个 issue,不要直接 PR
