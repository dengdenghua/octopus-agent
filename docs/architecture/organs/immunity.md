# 🛡️ Immunity · 免疫系统

**生物原型**：免疫系统是**内生**的安全能力，不是外挂：
- **先天免疫**（Innate）：物理屏障、巨噬细胞 —— 先存在，无需学习
- **适应免疫**（Adaptive）：B/T 细胞、抗体 —— 从经历中学习
- **免疫记忆**（Memory）：二次感染反应更快
- **自我耐受**（Tolerance）：不攻击"自己"

**抽象原则**：**安全必须参与决策过程，而非事后拦截**。

## 为什么独立于 Mantle / Ink
- `Mantle`（外套膜）= 物理屏障 —— 先天免疫的一部分
- `Ink`（墨囊）= 紧急熔断 —— 炎症反应的一部分
- `Immunity` = **学习/记忆/识别** —— 这是前两者没有的适应性能力

三者配合才构成完整免疫：

```
Mantle（皮肤） + Ink（炎症） + Immunity（B/T 细胞）
    ↓
完整免疫系统
```

## 子目录
```
immunity/
├── innate/       先天屏障（签名校验、来源白名单）
├── adaptive/     行为评分模型（在线学习）
├── memory/       攻击/失败模式库
└── tolerance/    自我耐受（受信任 skill 允许名单）
```

## 四大能力

### 1. Self vs Non-self（自我识别）
- 每个 Sucker / MCP 服务器 / 外部 API 有**来源签名**
- 未知来源默认不信任，先进入"观察期"
- 对应生物：MHC 分子

### 2. Memory（抗体记忆）
- 每次失败的调用模式入库：`{caller, args_pattern, failure_type}`
- 二次遇到相似模式：立即拒绝 + 广播 `alert.immune`
- 对应生物：记忆 B 细胞

### 3. Adaptive（行为评分）
- 每次调用后根据结果更新"危险性分数"
- 高分 Sucker → 自动限流、限额
- 对应生物：亲和力成熟（affinity maturation）

### 4. Tolerance（自我耐受）
- 明确的"自己人"白名单不触发免疫（避免自身免疫病）
- 每条 Arm 自己的工具链不被自己的免疫系统攻击
- 对应生物：胸腺阴性选择

## 与 Ink 的分工

| 场景 | 由谁处理 |
|---|---|
| 预算超限 | Ink（成本维度）|
| 连续失败 | Ink（循环检测）|
| 未知签名工具 | Immunity（身份维度）|
| 已知攻击模式 | Immunity（记忆维度）|
| 行为异常但无先例 | Immunity.adaptive（学习维度）|

## 接口
```python
class Immunity:
    def check(self, call: ToolCall) -> ImmuneVerdict:
        # ImmuneVerdict = allow | quarantine | reject
        ...
    def learn(self, call, outcome): ...
    def remember(self, attack_pattern): ...
```

## 进化关联
- **补位 Agent OS 最大的空白**：现有主流 agent 框架都缺适应免疫
- 与 **⑤ 自进化** 对称：Regeneration 让系统**学着做得更好**；Immunity 让系统**学着不做什么**

## 一句话原则
> 安全不是事后拦截，而是内生于每一次决策。
> 没有免疫系统的 Agent 系统，在生产环境必定翻车。
