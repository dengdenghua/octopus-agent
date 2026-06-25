# 🔵 Suckers · 吸盘

**生物原型**：章鱼每条腕约 200+ 吸盘，每个吸盘既是抓握器也是味觉器 —— 在执行现场感知与动作一体。

## 定位
本架构中的**技能原子**。一个 Sucker = 一个 SKILL.md + 对应工具/脚本。

## 目录
```
suckers/
├── loader/      [fork] 加载器（SKILL.md frontmatter + 热加载）
├── mcp/         [fork] MCP 客户端吸盘簇
├── public/      公共技能库（内置 + 社区）
└── custom/      用户自定义技能
```

## SKILL.md 扩展格式
```yaml
---
name: run_pytest
description: "在沙箱里跑 pytest 并收集失败用例"
affinity: [code]              # 新增：亲和哪类 Arm
cost_profile: mid             # 新增：low | mid | high（供 Ink 估算）
---
```

## 三条规则
1. **Progressive disclosure** —— 默认只注入 name+description（每个 ≈ 30 tokens）
2. **按 affinity 挂载** —— Arm 只看到自己亲和的 Sucker 子集
3. **Cost profile 必填** —— 让 Ink 能做预算预估

## 进化关联
**③ 技能** 的全部实现。Regeneration 会源源不断"种出"新的 Sucker 放到 `custom/`。
