---
name: 🛠 New Skill / Channel / Provider
about: 贡献 skill、channel、model router · 模板化流程
title: "[contrib] "
labels: good first issue
---

## 类型

- [ ] 新 Skill(放 `runtime/execution/suckers/`)
- [ ] 新 Channel adapter(Slack / DingTalk / ... 那种)
- [ ] 新 ModelRouter(新 LLM provider)
- [ ] 新 Mantle 后端(隔离执行层)
- [ ] 其他:

## 对应参考文件

<!--
  Skill  · `runtime/execution/suckers/builtins.py` 里挑一个复制
  Channel · `runtime/adapters/channels/slack.py`
  Router · `runtime/sensing/eyes/anthropic_router.py`
  Mantle · `runtime/mantle/subprocess_mantle.py`
-->

## 打算加什么

<!-- 名字 / 签名 / 输入 / 输出 -->

## 特别需要 review 的点

- [ ] 新增的 soft-dep(有 → 哪个 + 为什么不能 inline 实现)
- [ ] 如果是 Channel · 是否过了 constitution gate?(CONTRIBUTING.md "写新 Channel Adapter")
- [ ] 如果是 Skill · tier 属于 atomic 还是非 atomic?(决定是否默认全 agent 可见)

## 测试计划

- [ ] 单元测试:预期至少 _N_ 条(参考同类 skill 的测试规模)
- [ ] 手测场景:___
