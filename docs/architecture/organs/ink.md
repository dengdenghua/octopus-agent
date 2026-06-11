# 🖤 Ink · 墨囊（★ 成本治理核心）

**生物原型**：章鱼遭遇威胁时喷墨逃命 —— 本架构的紧急熔断与预算保护层。

## 三大护栏

### 1. `per_task_budget` 任务级预算
每个 task 创建时强制带：
- `max_tokens`
- `max_cost_usd`
超限即冻结，进入人工确认队列。

### 2. `circuit_breaker` 熔断器
触发条件：
- 连续 N 次工具失败（默认 3）
- 连续 M 步零信息增益（默认 5）
触发动作：冻结当前腕 → 广播 `alert.loop` → 回到 Cerebrum 仲裁。

### 3. `skill_cost_profile` 技能成本画像
- 每个 Sucker 记录：调用次数 / 平均 token / 平均延迟 / 平均 $
- 涨价超阈值（默认 2×）→ 广播 `alert.budget`
- 让 Cerebrum 在下次路由时避开

## 接口
```python
class Ink:
    def check_budget(self, task_id) -> BudgetStatus: ...
    def squirt(self, reason: str): ...      # 吐墨
    def profile(self, sucker, cost, tokens, latency): ...
```

## 进化关联
**⑥ 成本治理** 的主体。与 Hearts 配合（Hearts 是节律，Ink 是硬停）。

## 一句话原则
> agent 真正烧钱的姿势不是单次爆炸，而是陷进 loop 反复试错。Ink 的使命就是把这种循环打断。
