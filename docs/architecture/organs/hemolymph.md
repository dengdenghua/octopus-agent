# 🩵 Hemolymph · 血淋巴

**生物原型**：章鱼的"血"是铜基蓝血，主要功能是把氧送到每个器官。
本架构中 Hemolymph 把**上下文 token 预算**送到每次 LLM 调用。

## 双重职责
1. **Context Packet 编排**：每轮循环的上下文流动与预算分配
2. **Blackboard 共享面**：所有器官可读可写的短时工作记忆（swarm 的第三种通信模式）

与 Genome（长时存储）互补：Hemolymph 是流动的、每轮重新打包。
与 Chromatophores（事件广播）互补：Chromatophores 传"状态变化"事件，Blackboard 存"当前是什么"状态。

## Blackboard 区
- `/task/<task_id>/state` — 任务当前状态，Cerebrum 与 Arms 共读共写
- `/arm/<arm_id>/claims` — 腕宣称持有的资源（替代分布式锁）
- `/global/context_stats` — 实时 token 用量，供 Ink 读
- 清理策略：任务结束 TTL 清理；全局键长期保留

## 打包流程
```
每次 LLM 调用前：
  1. 从 Genome/memory 拉相关记忆
  2. 从 Skin 拉环境信号
  3. 从 Suckers 拉技能摘要（progressive disclosure）
  4. 按 config.yaml > hemolymph.quotas 分配预算
  5. 超限时先压缩（小模型摘要）再截断
  6. 打包成 ContextPacket 喷进 Eyes
```

## 预算配比（默认）
```yaml
system:   15%      # system prompt + sucker 注册表前缀
suckers:  10%      # 当前相关吸盘描述
memory:   30%      # 记忆 + 知识检索
history:  45%      # 对话历史
```

## 接口
```python
class Hemolymph:
    def compose(self, arm: Arm, task: ArmTask) -> ContextPacket: ...
    def compress(self, packet, target_tokens) -> ContextPacket: ...
```

## 进化关联
**④ 上下文/记忆** 的短时流动部分。硬顶机制是 **⑥ 成本治理** 的第一道节流阀（比 Ink 的熔断更早触发）。
