# ADR-003: 工具四阶段管线 - 从 DeepSeek Harness 吸收

**状态**: Implemented  
**日期**: 2026-08-14  
**作者**: Octopus Team  
**相关 PR**: （今天实施）  
**来源**: DeepSeek Harness (DSH) 工具系统设计

## 背景

在 2026-08-14 之前，Octopus 的工具系统相对简单：
- 工具注册 + 执行
- 基础的错误处理
- 无结构化的输出契约

**问题**：
1. 工具输出格式不一致（有时返回字符串，有时返回对象）
2. 无法在执行前/后插入策略（权限检查、结果过滤）
3. 并发安全性需要工具自己处理
4. 无法强制输出 schema 校验

**发现**：DeepSeek Harness 有完整的四阶段管线设计，解决了这些问题。

## 决策

**完整吸收 DSH 的工具四阶段管线设计**：

```python
# runtime/execution/arms/tool_registry.py
"""
dsh-style pipeline (absorbed from DeepSeek Harness, 2026-08-14)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Canonical output contract: output_schema + render
Four-stage pipeline: pre-execute → execute → post-execute → result
"""
```

### 管线流程

```
model → tool/call
  ↓
1. pre-execute (allow/deny/ask)
  ↓
2. execute (wrappers + timeout)
  ↓
3. tool handler → output
  ↓
4. validate output_schema
  ↓
5. post-execute (accept/replace/block)
  ↓
6. finalize_content
  ↓
7. render (model 看到的内容)
  ↓
tool/result → model
```

## 理由

### 为什么选择完整吸收而不是部分借鉴？

**考虑的替代方案**：

1. **只借鉴 output_schema**
   - 拒绝原因：
     - 无法处理执行前的权限检查
     - 无法在执行后过滤敏感信息
     - 不够系统化

2. **自己设计类似的管线**
   - 拒绝原因：
     - 重复造轮子
     - DSH 已经过实战验证
     - 我们的设计可能不如原创者完整

3. **完整吸收 DSH 四阶段管线** ✅ **选择此方案**
   - 优势：
     - 设计完整，覆盖所有场景
     - 经过 DSH 生产验证
     - 社区有参考实现
     - 明确标注来源（尊重原创）

## 影响

**正面影响**:
- ✅ 工具输出格式统一（`output_schema` 强制校验）
- ✅ 权限检查前置（`pre-execute` 阶段）
- ✅ 并发安全声明（`isConcurrencySafe`）
- ✅ 结果可过滤（`post-execute` 替换敏感信息）
- ✅ 模型看到的内容可控（`render` 分离）
- ✅ 与 DSH 兼容（未来可能互操作）

**负面影响**:
- ⚠️ 架构复杂度增加（4 阶段 vs 1 阶段）
- ⚠️ 现有工具需要迁移到新接口
- ⚠️ 学习成本（开发者需要理解管线）

**影响的组件**:
- `runtime/execution/arms/tool_registry.py` - 核心注册表（29KB）
- 所有工具实现需要逐步迁移

## 实现细节

### 1. 工具定义（DSH 风格）

```python
registry.register_tool(
    name="read_file",
    description="Read a file from disk",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "number"},
            "limit": {"type": "number"}
        },
        "required": ["path"]
    },
    output_schema={  # ← DSH 新增
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "lines": {"type": "number"}
        },
        "required": ["content"]
    },
    render=lambda input, output: output["content"],  # ← DSH 新增
    handler=read_file_handler,
    is_concurrency_safe=lambda args: True,  # ← DSH 新增
    timeout_ms=30000,  # ← DSH 新增
)
```

### 2. 四阶段 Hook

#### Pre-Execute（执行前门禁）
```python
@registry.on_pre_execute
async def check_file_access(ctx: ToolCallContext) -> PreToolDecision:
    if ctx.tool_name == "read_file":
        path = ctx.input.get("path")
        if not is_safe_path(path):
            return PreToolDecision.DENY
    return PreToolDecision.ALLOW
```

#### Execute（执行包装器）
```python
@registry.on_execute
async def add_timeout(ctx: ToolCallContext, next: Callable) -> Any:
    # 超时包装
    return await asyncio.wait_for(next(), timeout=ctx.timeout_ms / 1000)
```

#### Post-Execute（执行后处理）
```python
@registry.on_post_execute
async def filter_secrets(ctx: ToolCallContext, result: ToolCallResult) -> PostToolDecision:
    if "SECRET_KEY" in str(result.output):
        result.output = redact_secrets(result.output)
        return PostToolDecision.REPLACE
    return PostToolDecision.ACCEPT
```

#### Result（最终观察）
```python
@registry.on_result
async def log_tool_result(result: ToolCallResult) -> None:
    logger.info(f"Tool {result.tool_name} completed in {result.elapsed_ms}ms")
```

### 3. Output Schema 强制校验

```python
# runtime/execution/arms/tool_registry.py
if tool.output_schema:
    # 校验输出是否符合 schema
    validate_json_schema(output, tool.output_schema)
    if not valid:
        raise ToolOutputSchemaViolation(
            f"Tool {tool.name} output does not match schema"
        )
```

### 4. Render 分离

```python
# output: 完整的输出（可能包含调试信息）
output = {
    "content": "file content...",
    "lines": 42,
    "metadata": {"size": 1024, "mtime": "2026-08-14"}
}

# render: 模型看到的内容（仅核心信息）
rendered = render(input, output)  # → "file content..."
```

**好处**：
- 调试时可以看完整输出
- 模型只看核心信息（减少 token）
- 敏感信息可以在 output 中保留但不 render

### 5. Concurrency Safe

```python
is_concurrency_safe = lambda args: args.get("readonly", False)

# 只读操作可并发
read_file(path="/foo", readonly=True)   # 可并发
write_file(path="/foo", content="...")  # 不可并发
```

## 迁移计划

### Phase 1（已完成，2026-08-14）
- ✅ 实现四阶段管线核心
- ✅ 添加 `output_schema` / `render` / `isConcurrencySafe` 支持
- ✅ 标注来源："absorbed from DeepSeek Harness"

### Phase 2（本周）
- [ ] 核心工具迁移（Bash/Read/Write/Edit）
- [ ] 添加 output_schema 定义
- [ ] 测试 schema 校验

### Phase 3（下周）
- [ ] 所有工具迁移到新接口
- [ ] 文档更新
- [ ] 示例代码

### Phase 4（下月）
- [ ] 强制 output_schema（所有工具必须定义）
- [ ] 性能优化
- [ ] A/B 测试

## 与 DSH 的差异

虽然完整吸收设计，但实现语言不同：

| 维度 | DSH | Octopus |
|------|-----|---------|
| 语言 | TypeScript | Python |
| 行数 | 1946 行 | 29KB (约 1000 行) |
| 类型推断 | ✅ TS 自动推断 | ⚠️ Python 手动标注 |
| Schema 校验 | Ajv (编译时) | jsonschema (运行时) |

**我们的增强**：
- ✅ 与现有 Reflex Layer 集成
- ✅ 与 Swarm Mesh 的并发控制集成
- ✅ 支持 per-agent scope 隔离

## 相关决策

- **ADR-001**: Reflex Layer - 零 LLM 快速响应
- **ADR-002**: Swarm Mesh - Boids 并发控制与工具并发安全配合
- **DSH Reference**: `packages/core/tools/src/index.ts` (1946 行)

## 致谢

感谢 DeepSeek Harness 团队的开源设计。我们完整吸收了四阶段管线的理念，并在注释中明确标注来源。

## 参考

- DSH 工具系统：`packages/core/tools/`
- DSH 文档：`docs/tool-execution-pipeline.md`
- JSON Schema：https://json-schema.org/

---

**创建时间**: 2026-08-14  
**最后更新**: 2026-08-14
