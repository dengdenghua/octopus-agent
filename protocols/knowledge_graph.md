---
implementation_status: implemented
implemented_in:
  - runtime/memory/knowledge_graph/kg.py
  - runtime/memory/knowledge_graph/sqlite_kg.py
  - runtime/memory/knowledge_graph/kuzu_kg.py
last_verified: 2026-06-25
---

# Protocol · Knowledge Graph (知识图谱升级)

> 缺口 2（SIX_MODULES §4）的完整规范。
> 从当前 `genome/knowledge/` 的 Wiki + FTS5 升级为**结构化三元组 KG**。
>
> 核心判断：**Wiki 查得到但推不动；KG 能查能推**。
>
> 冲突消解复用 [conflict_resolution.md](conflict_resolution.md)，本协议只讲 KG 专属。

---

## 1. 为什么升级

当前 `genome/knowledge/`：
- 存储：Wiki markdown + FTS5 全文检索
- 能力：**模糊查得到**（"alice 是谁"能搜到文档）
- 局限：**推不动**（问"alice 的经理的经理" → 无法图遍历）

KG 加上三个能力：
1. **结构化检索**：按关系/属性精确查
2. **图遍历**：多跳查询（"X 的 Y 的 Z"）
3. **本体推理**：子类继承、等价关系、反向关系

---

## 2. Triple Schema

```python
Triple = {
    "triple_id": uuid,
    "subject": EntityRef,               # 实体
    "predicate": str,                    # 关系或属性名
    "object": EntityRef | Literal,       # 另一实体或字面值
    # ── 元信息（复用 Assertion 字段）──
    "confidence": float,
    "source": Source,
    "evidence_refs": list[str],
    "valid_from": datetime | None,
    "valid_until": datetime | None,
    "ts": datetime,
    "status": "active" | "archived" | "disputed" | "superseded",
    "superseded_by": uuid | None,
}

Entity = {
    "entity_id": str,                    # URI-like: "entity:alice"
    "types": list[str],                  # 可多类型 ["Person", "Employee"]
    "canonical_name": str,
    "aliases": list[str],
    "embedding": list[float] | None,     # 用于模糊匹配
}

Literal = {
    "value": str | int | float | datetime,
    "datatype": str,                     # "xsd:string" / "xsd:date" / ...
    "language": str | None,
}
```

**Triple 就是 Assertion 的特例** —— KG 所有写入直接复用 `conflict_resolution.md` 的消解流水线（CC-C1）。

---

## 3. 存储选型

| 选项 | 优点 | 缺点 | 推荐场景 |
|---|---|---|---|
| **Neo4j** | 生态成熟、Cypher 直观、大规模稳定 | 重量级、License（社区版功能受限）| 生产 / 企业 |
| **Kùzu** | 嵌入式、高性能、Apache 2.0 | 年轻、工具链薄 | 本项目默认 / 边端 |
| 手搓 SQLite | 零依赖 | 图查询代码量大 | 禁止（违反"用现成的"原则）|

**默认 Kùzu**（边端友好 + 开源），生产可切 Neo4j。
通过抽象层 `KnowledgeGraph` 隔离，上层不感知。

```python
class KnowledgeGraph:
    def write(self, triple: Triple) -> uuid: ...
    def query(self, q: Query) -> list[Triple]: ...
    def path(self, start, end, max_hops) -> list[Path]: ...
    def neighbors(self, entity_id, hops=1) -> list[Entity]: ...
```

---

## 4. Ingestion Pipeline

三种入源：

### 4.1 对话/工具返回抽取

```python
def extract_from_trajectory(traj: Trajectory) -> list[Triple]:
    # 仅对成功轨迹做抽取（F-Trajectory >= 0.7）
    if traj.f_trajectory < 0.7: return []

    # 用 Haiku 做抽取（小模型够用）
    prompt = EXTRACT_TRIPLES_PROMPT.fill(
        trajectory=traj.steps,
        existing_entities=hint_entities(traj),
    )
    raw = eyes.call_model("haiku", prompt)
    triples = parse_triples(raw.content)

    # 每条 triple 的 confidence 由 LLM 自评 + 类型校验
    for t in triples:
        t.source = Source(source_type="trajectory", source_id=traj.id)
        t.evidence_refs = [step.id for step in traj.steps]
    return triples
```

### 4.2 文档抽取

```python
def extract_from_doc(doc: Document) -> list[Triple]:
    # 用 Sonnet 做（文档复杂，需要更强理解）
    ...
    for t in triples:
        t.source = Source(source_type="doc", source_id=doc.id)
    return triples
```

### 4.3 用户显式输入

```python
def ingest_user_fact(fact: str, user_id: str) -> Triple:
    triple = parse_structured(fact)
    triple.source = Source(source_type="user", source_id=user_id, trust_score=0.8)
    return triple
```

### 共同路径

```python
def ingest(triples: list[Triple]):
    for t in triples:
        conflicts = conflict_resolver.detect(t)
        resolution = conflict_resolver.resolve(conflicts) if conflicts else None
        if resolution is None or resolution.winner == t.triple_id:
            kg.write(t)
        else:
            archive_as_superseded(t, resolution.winner)
```

**不变量 CC-C1**：KG 所有写入必经 conflict_resolver，没有 bypass。

> ⚠️ **CC-C1 部分成立**:6 策略 conflict_resolver 已实装(`runtime/safety/conflict_resolution/resolver.py`),但 KG 的 `add()` 目前仍用内联 supersede 逻辑(基于 confidence + timestamp),尚未切换到调用 `resolve()`。CC-C1 待 KG 接入后完全成立。

---

## 5. 本体（Ontology）系统

### 5.1 最小本体定义

```yaml
# genome/knowledge/graph/ontology.yaml
classes:
  - id: Person
    parent: Entity
  - id: Employee
    parent: Person
  - id: Company
    parent: Organization

relations:
  - id: worksFor
    domain: Employee
    range: Company
    inverse: employs
  - id: manages
    domain: Employee
    range: Employee
    transitive: false          # 不传递：A 管 B 不代表 A 管 B 管的人

attributes:
  - id: age
    domain: Person
    range: xsd:integer
```

### 5.2 三类推理（简化）

| 推理 | 规则 | 例 |
|---|---|---|
| **Subclass** | (X isa A) ∧ (A ⊂ B) ⇒ (X isa B) | (alice isa Employee) ⇒ (alice isa Person) |
| **Inverse** | (X r Y) ⇒ (Y r⁻¹ X) | (alice worksFor acme) ⇒ (acme employs alice) |
| **Transitive** | (X r Y) ∧ (Y r Z) ⇒ (X r Z) （仅标注 transitive=true 的关系）| (a sub b) ∧ (b sub c) ⇒ (a sub c) |

**不做**：复杂 OWL 推理、SWRL 规则、概率软逻辑 —— 当前阶段不需要。

### 5.3 推理约束

- 推理产出的 triple `source_type = "inference"`，trust 上限 0.5（复用 CFR-I5）
- 推理深度硬顶 3 跳，防止 transitive 爆炸
- 推理结果**不持久化**（每次查询时在线推出），除非被多个路径支持（≥2）才落盘

---

## 6. Query API

```python
class Query:
    # 1. 简单模式匹配
    Query.triples(subject=?, predicate=?, object=?)
    # 2. 多跳路径
    Query.path(start=?, end=?, via=[pred1, pred2], max_hops=3)
    # 3. 邻居
    Query.neighbors(entity=?, rel_types=[?], direction="out"|"in"|"both")
    # 4. 属性聚合
    Query.aggregate(group_by=?, predicate=?, agg="count"|"sum"|"avg")
```

### Hemolymph 调用
```python
# 每次 LLM 调用前，hemolymph 拉相关实体
entities = extract_entities(task.goal)
for e in entities:
    facts = kg.neighbors(e, hops=recipe.kg_recall.depth,
                        max_triples=recipe.kg_recall.max_triples)
    context.kg_facts.extend(facts)
```

---

## 7. 不变量（KG-I 系列）

| ID | 内容 | 执行 |
|---|---|---|
| KG-I1 | 所有 Triple 写入必经 conflict_resolver | **Lint** + Runtime Gate |
| KG-I2 | 推理产出 triple 深度硬顶 3 跳 | Runtime Assert |
| KG-I3 | 推理 triple 默认不落盘，除非 ≥ 2 路径支持 | Runtime Assert |
| KG-I4 | Ontology 修改必 QUORUM（它是全局约束）| gene_lock QUORUM |
| KG-I5 | Entity 合并（别名归一）必审计 | Runtime Assert |
| KG-I6 | 删除 triple 必走 "archive" 路径（超越 status 改）| Schema enforce |
| KG-I7 | Personal 级实体的 triple 不出 Edge | **Lint** (DIS-I1 复用) |
| KG-I8 | Bulk ingest 前必做去重（避免同 assertion 重复写）| Runtime Assert |

---

## 8. 集成点

| 场景 | 调用方 | API |
|---|---|---|
| Trajectory → KG | `regeneration.kg_updater` | `extract_from_trajectory + ingest` |
| 文档 → KG | `eyes.Perception` (处理 PDF 等) | `extract_from_doc + ingest` |
| 用户直接输入 | `siphon` 接口 | `ingest_user_fact` |
| Hemolymph 上下文拉取 | `hemolymph.ContextComposer` | `kg.neighbors / kg.path` |
| Memory 与 KG 互通 | `memory_consolidation` | 见 [memory_consolidation.md](memory_consolidation.md) §6 |

---

## 9. 配置契约

```yaml
knowledge_graph:
  enabled: true
  backend: kuzu                        # kuzu | neo4j
  storage_path: ./genome/knowledge/graph/
  ontology_file: ./genome/knowledge/graph/ontology.yaml

  ingestion:
    from_trajectory:
      f_trajectory_min: 0.7
      extraction_model: claude-haiku-4-5-20251001
    from_doc:
      extraction_model: claude-sonnet-4-6
    dedup_before_write: true

  inference:
    max_hops: 3
    trust_cap: 0.5
    persist_if_paths_min: 2

  recall:
    default_depth: 2
    default_max_triples: 20
    confidence_min: 0.3

  ontology_modification:
    quorum: {m: 2, n: 3}
```

---

## 10. 可观测性

| Metric | 用途 |
|---|---|
| `kg.triples_count{status}` | 各状态三元组数 |
| `kg.ingestion_rate` | 写入速率 |
| `kg.conflict_rate` | 入库遇到冲突占比 |
| `kg.inference_depth_distribution` | 推理深度分布 |
| `kg.query_latency_p99{query_type}` | 查询延迟 |
| `kg.recall_hit_rate` | Hemolymph 拉取命中率（有返回即命中）|

---

## 11. 反模式

| 反模式 | 后果 | 破解 |
|---|---|---|
| 跳过 conflict_resolver 直接写 | 矛盾三元组共存 | KG-I1 强制 |
| 推理无深度限制 | transitive 爆炸 | KG-I2 硬顶 |
| 推理结果无差别落盘 | 垃圾膨胀 | KG-I3 至少 2 路径 |
| 删三元组而非 archive | 审计断链 | KG-I6 只准状态迁移 |
| Entity 合并无审计 | 错误合并后无法溯源 | KG-I5 |
| Bulk ingest 不去重 | 同事实重复多条 | KG-I8 |
