# Phase 2 集成计划

## 目标

将 Phase 1 的核心优化组件集成到生产代码路径中，实现：
- 增量快照计算（O(n) → O(Δn)）
- IndexedDB 持久化缓存
- 后端自适应批处理
- 协议版本化支持

## 集成策略

### 原则
1. **渐进式集成** - 每个优化独立可控
2. **特性开关** - localStorage 控制启用/禁用
3. **降级兜底** - 失败时回退到原实现
4. **性能监控** - 记录优化效果指标

---

## 1. 增量快照计算器集成

### 现状分析
- **当前**: `useAgentWorkbenchSnapshot` 每次全量重算 O(n)
- **优化**: 使用 `IncrementalSnapshotCalculator` 增量计算 O(Δn)

### 集成点
文件: `frontend/src/components/workspace/agent-workbench-snapshot.ts`

```typescript
// 在 useAgentWorkbenchSnapshot 中
const calculator = useRef<IncrementalSnapshotCalculator>();
if (!calculator.current) {
  calculator.current = new IncrementalSnapshotCalculator();
}

// 特性开关
const useIncremental = localStorage.getItem('octopus:incremental-snapshot') === '1';

if (useIncremental) {
  return calculator.current.compute(events, options);
} else {
  // 原有逻辑
  return buildAgentWorkbenchSnapshot(events, options);
}
```

### 问题
当前 `IncrementalSnapshotCalculator` 的 `_deriveIncrementalBlocks` 返回空数组（TODO）。

### 解决方案
方案 A: **复用现有逻辑**（推荐）
```typescript
private _deriveIncrementalBlocks(newEvents: LiveToolEvent[]): WorkBlock[] {
  // 复用 work-blocks.ts 的 normalizeEventsForSettledDisplay
  const displayEvents = normalizeEventsForSettledDisplay(
    [...this.cachedEvents, ...newEvents],
    this.cachedOptions
  );
  const derived = deriveAgentPhases(displayEvents, this.cachedOptions);
  return derived.blocks;
}
```

方案 B: **暂时禁用增量计算**
- 保持代码但不启用，等完整实现后再启用

---

## 2. IndexedDB 缓存集成

### 现状分析
- 页面刷新时需要重新连接 WebSocket + 重放事件（2-3s）
- 无离线查看能力

### 集成点
文件: `frontend/src/app/workspace/realtime/[thread_id]/page.tsx`

```typescript
// 在组件顶部
const snapshotCache = useRef(new WorkbenchSnapshotCache());

// 页面加载时尝试从缓存恢复
useEffect(() => {
  const restoreFromCache = async () => {
    if (!threadId || isNewThread) return;
    
    const cached = await snapshotCache.current.load(threadId, lastTurnId);
    if (cached) {
      // 使用缓存的快照快速渲染
      setInitialSnapshot(cached.snapshot);
      setInitialEvents(cached.events);
    }
  };
  
  restoreFromCache();
}, [threadId, lastTurnId]);

// 快照更新时保存到缓存
useEffect(() => {
  if (workbenchSnapshot && lastTurnId) {
    snapshotCache.current.save(
      threadId,
      lastTurnId,
      workbenchSnapshot,
      allToolEvents
    );
  }
}, [workbenchSnapshot, lastTurnId]);
```

### 特性开关
```typescript
const enableCache = localStorage.getItem('octopus:cache-workbench') === '1';
```

---

## 3. 后端自适应批处理器集成

### 现状分析
- 当前固定批处理策略（每 N 个字符或 M 毫秒）
- 高吞吐场景可能过于频繁，低吞吐场景可能过于延迟

### 集成点
文件: `runtime/sensing/gateway/realtime_event_bridge.py`

#### 当前代码
```python
# 某处固定批处理
async def _emit_delta(self, delta: str):
    self.buffer += delta
    if len(self.buffer) > 100 or time_elapsed > 0.05:
        await self._flush()
```

#### 集成后
```python
from runtime.sensing.gateway.adaptive_delta_buffer import AdaptiveDeltaBuffer

class RealtimeEventBridge:
    def __init__(self):
        self.buffer = AdaptiveDeltaBuffer()
    
    async def _emit_delta(self, delta: str):
        self.buffer.append(delta)
        if self.buffer.should_flush():
            content = self.buffer.get_content()
            await self._send(content)
            self.buffer.clear()
```

### 配置开关
```yaml
# config.local.yaml
realtime:
  adaptive_batching: true  # 启用自适应批处理
```

---

## 4. 协议版本化集成

### 现状分析
- 前后端事件格式耦合，升级困难
- 无法渐进式推出新字段

### 集成点

#### 后端
文件: `runtime/protocol/realtime_schema.py`

```python
# 已创建，需要接入事件发射路径
def emit_tool_start_v2(tool_id: str, ...):
    return ToolStartEventV2(
        protocol_version=PROTOCOL_VERSION_V2,
        tool_id=tool_id,
        supports_cancellation=True,
        performance_metrics={"ttft_ms": 123},
        ...
    )
```

#### 前端
文件: `frontend/src/core/realtime/protocol-versioning.ts`

```typescript
// 在 WebSocket 消息处理中
const rawEvent = JSON.parse(message.data);
const adapter = globalEventAdapterRegistry.getAdapter(
  rawEvent.protocol_version || "v1"
);
const liveEvent = adapter.adapt(rawEvent);
```

### 配置开关
```python
# runtime/config/feature_flags.py
PROTOCOL_V2_ENABLED = os.getenv("OCTOPUS_PROTOCOL_V2", "false") == "true"
```

---

## 5. 性能基准测试

### 测试场景

#### 场景 1: 快照计算性能
```typescript
// frontend/src/components/workspace/__tests__/snapshot-performance.test.ts

test('incremental vs full snapshot computation', () => {
  const events = generateMockEvents(1000); // 1000 个事件
  
  // 全量计算
  const start1 = performance.now();
  const full = buildAgentWorkbenchSnapshot(events, options);
  const time1 = performance.now() - start1;
  
  // 增量计算（添加 100 个新事件）
  const calculator = new IncrementalSnapshotCalculator();
  calculator.compute(events.slice(0, 900), options);
  
  const start2 = performance.now();
  const incremental = calculator.compute(events, options);
  const time2 = performance.now() - start2;
  
  console.log(`Full: ${time1}ms, Incremental: ${time2}ms`);
  expect(time2).toBeLessThan(time1 * 0.2); // 期望 80% 提升
});
```

#### 场景 2: 缓存恢复速度
```typescript
test('cache restore speed', async () => {
  const cache = new WorkbenchSnapshotCache();
  
  // 保存
  await cache.save(threadId, turnId, snapshot, events);
  
  // 测量加载速度
  const start = performance.now();
  const cached = await cache.load(threadId, turnId);
  const loadTime = performance.now() - start;
  
  expect(loadTime).toBeLessThan(100); // < 100ms
  expect(cached).toBeDefined();
});
```

#### 场景 3: 自适应批处理吞吐
```python
# tests/sensing/test_adaptive_delta_buffer.py

def test_adaptive_batching_throughput():
    buffer = AdaptiveDeltaBuffer()
    
    # 低吞吐场景（< 100 chars/s）
    for i in range(10):
        buffer.append("a")
        time.sleep(0.02)  # 20ms per char = 50 chars/s
    
    assert buffer.threshold == 32  # 低档阈值
    
    # 高吞吐场景（> 1000 chars/s）
    for i in range(100):
        buffer.append("x" * 100)  # 100 chars
        time.sleep(0.001)  # 1ms = 100k chars/s
    
    assert buffer.threshold == 256  # 高档阈值
```

---

## 集成顺序（推荐）

### 第 1 步：IndexedDB 缓存（低风险，高收益）
- ✅ 代码已就绪
- ✅ 完全独立，不影响现有逻辑
- ✅ 用户立即感知（刷新快 10-20 倍）

### 第 2 步：后端自适应批处理（中风险，中收益）
- ⚠️ 需要找到批处理代码位置
- ✅ 降级简单（配置开关）
- ✅ 减少 CPU 占用 30-50%

### 第 3 步：协议版本化（低风险，低收益）
- ✅ 代码已就绪
- ✅ 为未来升级打基础
- ⚠️ 短期无明显性能提升

### 第 4 步：增量快照计算（高风险，高收益）
- ❌ `_deriveIncrementalBlocks` 未实现
- ⚠️ 需要深入理解现有派生逻辑
- ✅ 潜在收益最大（90% 提升）

---

## 立即可做

### A. 集成 IndexedDB 缓存（30 分钟）
1. 在 `RealtimePage` 中引入 `WorkbenchSnapshotCache`
2. 添加加载/保存逻辑
3. 添加特性开关 `octopus:cache-workbench`
4. 测试刷新恢复速度

### B. 后端批处理集成（1 小时）
1. 查找 `realtime_event_bridge.py` 中的批处理代码
2. 替换为 `AdaptiveDeltaBuffer`
3. 添加配置开关
4. 观察 CPU 占用变化

### C. 编写性能基准（30 分钟）
1. 创建 `snapshot-performance.test.ts`
2. 创建 `test_adaptive_delta_buffer.py`
3. 运行并记录基线数据

---

## 风险控制

### 降级策略
所有优化都有特性开关，出问题立即回退：
```typescript
// 前端
localStorage.removeItem('octopus:incremental-snapshot');
localStorage.removeItem('octopus:cache-workbench');

// 后端
OCTOPUS_ADAPTIVE_BATCHING=false
OCTOPUS_PROTOCOL_V2=false
```

### 监控指标
```typescript
// 在 PerformanceTracker 中记录
tracker.mark('snapshot-start');
const snapshot = computeSnapshot(events);
tracker.measure('snapshot-compute', 'snapshot-start');

// 定期上报
if (tracker.getReport().summary.slowOperations > 0) {
  console.warn('Slow snapshot computation detected');
}
```

---

## 下一步行动

建议优先级：
1. **立即做**: IndexedDB 缓存集成（最安全，用户立即感知）
2. **今天做**: 后端自适应批处理（减少 CPU 占用）
3. **本周做**: 性能基准测试（量化优化效果）
4. **迭代做**: 增量快照计算（需要完整实现）

要开始吗？从哪一个开始？
