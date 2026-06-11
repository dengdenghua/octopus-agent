# 🟤 Skin · 皮肤（纯感知层）

**生物原型**：章鱼皮肤含光感受器，能"看见光" —— 但皮肤**不做决策**，只把信号上报给神经系统。

## 铁律：只上报，不决策

> **Skin 禁止路由、禁止调用、禁止触发行为。**
> 它唯一能做的是**感知 + 上报**。

违反这条的后果：分布式系统里最难调试的 bug 来源 —— **感知层越权决策导致的隐式副作用**。

## 职责边界

| ✅ 允许 | ❌ 禁止 |
|---|---|
| 监听 fs/env/webhook/timer | 判断"要不要告诉 Cerebrum" |
| 规范化信号格式 | 直接调 Arm / Beak |
| 打时间戳、打来源标签 | 汇总/聚合多个信号 |
| 限流（防信号风暴）| 基于信号做路由 |
| Push 到 Hemolymph Blackboard | 跨模块 orchestration |

"要不要响应这个信号"是 **Cerebrum / Spinal Cord** 的事。Skin 只负责"让他们看见"。

## 为什么独立于 Eyes

| | Eyes | Skin |
|---|---|---|
| 方向 | 主动拉（LLM 调、用户输入解析）| 被动推（环境冒泡）|
| 频率 | 每轮请求一次 | 持续流（可能很密）|
| 决策 | 有（选哪个模型、怎么解析）| **无** |

## 接口
```python
class Skin:
    def sense(self) -> Iterator[AmbientSignal]: ...
    def subscribe(self, source: str, handler): ...
    # 注意：没有 act / decide / route 方法
```

## 示例信号源
- `fs.changed`：仓库文件改动
- `env.updated`：环境变量变化
- `webhook.github`：GitHub 事件
- `cron.tick`：定时事件（由 Hearts 驱动）
- `metric.alert`：Prometheus 告警

## 信号打包规范
```python
AmbientSignal = {
    "source": str,         # 来源标签
    "type": str,           # 事件类型
    "payload": dict,       # 原始数据
    "ts": float,           # 时间戳
    "ttl": int,            # 存活期（到期自动从 blackboard 清）
}
```

## 进化关联
作为 **② Swarm + Blackboard** 模式的信号输入端（信号写进 `hemolymph/blackboard`）。
**简洁**是它的美德 —— 越简单的感知层，越不会成为事故源。
