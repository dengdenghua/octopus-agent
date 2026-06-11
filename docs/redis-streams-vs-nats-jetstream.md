# 技术选型对比报告：Redis Streams vs NATS JetStream
> 场景：分布式任务队列 · 生成日期：2026-04-24

---

## 1. 概览

| 维度 | Redis Streams | NATS JetStream |
|------|--------------|----------------|
| 定位 | 内存数据库附带的持久化消息流 | 专为云原生设计的轻量级消息系统 |
| 语言 | C | Go |
| 协议 | RESP3 (TCP) | NATS 自有协议 (TCP) |
| 持久化 | RDB / AOF（磁盘可选） | 基于文件存储（File Store）或内存 |
| 开源协议 | BSD-3 | Apache 2.0 |

---

## 2. 核心能力对比

| 能力 | Redis Streams | NATS JetStream |
|------|:---:|:---:|
| At-least-once 投递 | ✅ XACK 机制 | ✅ AckPolicy |
| Exactly-once 投递 | ❌ 需业务幂等 | ⚠️ 实验性（Deduplication Window） |
| 消费者组 | ✅ XGROUP | ✅ Push/Pull Consumer |
| 消息回溯 / Replay | ✅ 按 ID 或时间 | ✅ DeliverPolicy 灵活配置 |
| 消息 TTL / 自动清理 | ✅ MAXLEN / MINID | ✅ MaxAge / MaxMsgs |
| 延迟消息 | ❌ 原生不支持 | ❌ 原生不支持（需 KV + 调度） |
| 优先级队列 | ❌ | ❌ |
| 多租户隔离 | ⚠️ 靠 key 前缀 | ✅ Account 级别隔离 |
| 水平扩展 | ⚠️ Cluster 分片复杂 | ✅ JetStream Clustering 原生支持 |
| 跨地域复制 | ❌ 需 Redis Enterprise | ✅ Leaf Node + Mirror Stream |

---

## 3. 性能基准（参考值）

| 指标 | Redis Streams | NATS JetStream |
|------|--------------|----------------|
| 吞吐量（单节点） | ~500K msg/s（纯内存） | ~300K msg/s（持久化开启） |
| P99 延迟 | < 1ms（内存模式） | 1–5ms（文件存储） |
| 持久化写入代价 | AOF fsync 影响显著 | 顺序写，影响较小 |
| 内存占用 | 高（所有数据在内存） | 低（流数据落盘） |

> 数据来源：各官方 benchmark + 社区测试，实际结果因硬件和配置差异较大。

---

## 4. 运维复杂度

| 方面 | Redis Streams | NATS JetStream |
|------|--------------|----------------|
| 部署难度 | 低（单二进制，生态成熟） | 低（单二进制，配置简洁） |
| 集群搭建 | 中（Redis Cluster 有坑） | 低（Raft 自动选主） |
| 监控生态 | 丰富（Prometheus exporter 成熟） | 成长中（官方 exporter 可用） |
| 客户端 SDK | 极丰富（几乎所有语言） | 丰富（官方维护主流语言） |
| 已有基础设施复用 | ✅ 若已用 Redis 可零增量 | ❌ 需新增组件 |

---

## 5. 评分矩阵（满分 10）

| 维度 | 权重 | Redis Streams | NATS JetStream |
|------|:----:|:---:|:---:|
| 功能完整性 | 25% | 7 | 8 |
| 性能 | 20% | 9 | 7 |
| 可靠性 / 持久化 | 20% | 7 | 8 |
| 运维友好度 | 15% | 8 | 8 |
| 扩展性 | 10% | 6 | 9 |
| 社区 / 生态 | 10% | 9 | 7 |
| **加权总分** | | **7.65** | **7.90** |

---

## 6. 适用场景建议

**选 Redis Streams，如果：**
- 团队已在用 Redis，不想引入新组件
- 任务量中等（< 10万 msg/s），对延迟极敏感
- 不需要跨地域复制，单机房部署

**选 NATS JetStream，如果：**
- 需要多租户隔离或跨集群/跨地域消息同步
- 任务队列数据量大，希望消息落盘不占内存
- 微服务架构，消息系统需要独立演进
- 未来可能扩展到 Request-Reply、服务发现等场景

---

## 7. 最终推荐

**新项目首选 NATS JetStream**，其原生集群、灵活的消费者模型和多租户支持更适合分布式任务队列的长期演进。

**已有 Redis 的项目**，直接用 Redis Streams 是务实选择——功能够用、运维成本为零增量，等规模真正触及瓶颈再迁移不迟。
