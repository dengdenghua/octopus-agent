# 🎭 Camouflage · 拟态伪装

**生物原型**：章鱼能在不到 1 秒内模仿石头、海藻、比目鱼 —— 不同环境切换不同策略。

## 职责
**策略 A/B 实验与自适应切换**。同一任务并行跑多种 Cerebrum prompt / 模型路由组合，按 ROI 收敛最优。

## 典型策略矩阵
| 策略名 | planner | executor | 适用 |
|---|---|---|---|
| cheap | haiku | haiku | 简单查询 |
| balanced | sonnet | haiku | 日常 90% |
| deep | opus | sonnet | 复杂规划 |

## 收敛算法
- 默认 **Thompson Sampling**（多臂老虎机）
- 指标：完成率 × (1 / 成本)
- 冷启动期：均匀采样 100 次
- 稳态：最优臂占比 > 70%

## 接口
```python
class Camouflage:
    def pick(self, task_type) -> Strategy: ...
    def report(self, strategy, success, cost): ...
```

## 进化关联
**⑥ 成本治理** 的策略维度。是跑过 Regeneration 后找出最优策略组合的工具。

## 警示
不要早期开启 —— 样本量不够时反而烧钱。推荐在阶段 4 Hearts 稳定后开。
