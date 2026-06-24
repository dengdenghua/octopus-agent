# 🌱 Regeneration · 再生（★ 自进化核心）

**生物原型**：章鱼断腕可重长，且再生的腕常常比原来更强。
本架构中：失败的执行路径 → 反思 → 长出新 Sucker / 新规则 → 下次更强。

## 子目录
```
regeneration/
├── trajectory/    采集 Arm 执行轨迹（从 Genome/journal 读）
├── evaluator/     离线 Batch API 打分
├── skill_forge/   把高频成功路径锻造成新 Sucker
└── reflection/    失败路径归纳为规避规则
```

## 完整回路
```
Arms 执行 → Genome/journal 落盘
    ↓
trajectory 采集（实时）
    ↓ 夜间 Batch 触发
evaluator 打分（每条 trajectory 一个分数）
    ↓
     ├─→ 高分 + 高频 → skill_forge 锻造新 Sucker → suckers/custom/
     └─→ 低分模式 → reflection 归纳规避规则 → 注入 Cerebrum planner prompt
```

## 关键设计
- **全程走 Batch API**（成本砍半）
- **夜间跑**（不占业务峰值窗口）
- **隔离环境验证**：新 Sucker 先在 mantle/local 跑通才能进 public
- **冷启动期是负 ROI**（反思在烧钱，但产出还没积累）—— 预期 2–4 周才拐头

## Skill Forge 门槛（默认）
- 最小命中次数：5
- 最小成功率：70%
- 成本分布：低于同类中位数 × 1.2

## 接口
```python
class Regeneration:
    def sample_trajectories(self, since) -> list[Trajectory]: ...
    def evaluate_batch(self, trajs) -> list[Score]: ...
    def forge_skill(self, high_score_paths) -> list[Sucker]: ...
    def extract_rules(self, low_score_paths) -> list[Rule]: ...
```

## 进化关联
**⑤ 反思/自进化** 的全部实现。通过喂养 Suckers（③）和 Cerebrum（①）持续提升系统能力。
