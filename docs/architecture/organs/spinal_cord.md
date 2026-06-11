# ⚡ Spinal Cord · 脊髓（反射通路）

**生物原型**：脊髓不经过大脑就能完成"缩手反射" —— 延迟毫秒级，不耗脑力。
**抽象原则**：**Reactive + Deliberative 双通路决策**。不是所有事情都该走 LLM。

## 为什么独立于 Cerebrum
- Cerebrum 是"深思熟虑"通路：大模型、高成本、高延迟
- Spinal Cord 是"反射"通路：规则 / cache / 小模型，几乎零成本
- 二者**并列于命令链顶端**，由 Meta-Control 路由决定走哪条

## 四种反射实现（由易到难）

| 机制 | 适用 | 成本 |
|---|---|---|
| **Regex / Keyword** | 固定模式指令（"停"、"撤销"、"继续"）| 近零 |
| **Cache Hit** | 重复 query 的结果命中 | 近零 |
| **Rule Engine** | 形式化规则（if-else 可表达）| 近零 |
| **Edge SLM** | 小模型本地推理（分类/意图识别）| 低 |

## 路由决策（Meta-Control）

```
用户输入
    │
    ├─→ spinal_cord.try_reflex(input)
    │       ├─ 命中 → 直接返回（旁路 Cerebrum）
    │       └─ 未命中 → 继续
    │
    └─→ Cerebrum.plan(input)   (慢路径)
```

**默认顺序**：反射先试，未命中才走思考。
**例外**：用户显式标记 `--deep` 或任务类型属于"规划密集型"时，直接走 Cerebrum。

## 接口
```python
class SpinalCord:
    def try_reflex(self, input: Perception) -> ReflexResult | None: ...
    def register(self, matcher, handler, cost: str = "low"): ...
    def stats(self) -> ReflexStats:  # hit rate / saved cost
        ...
```

## 与其他器官的关系
- **Eyes** 把输入喂给它（先于 Cerebrum）
- **Ink** 订阅它的 `hit_rate` 指标：命中率低说明反射没价值，可下线
- **Regeneration** 会自动把"高频+稳定"的 Cerebrum 决策**下沉**成反射规则
- **Genome/memory** 存反射规则库（可热更新）

## 进化关联
- 直接对应 **⑥ 成本治理** 的最强杠杆（反射几乎零成本）
- 与 **⑤ 自进化** 双向互动：Regeneration 源源不断把学会的模式沉淀为反射

## 一句话原则
> 任何只依赖大模型的 Agent 架构，都是不稳定且低效的。
> 反射是 Agent OS 的"本能"，不可或缺。
