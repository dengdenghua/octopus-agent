# 🚀 快速启用指南

立即体验 Phase 2 优化效果！

## 前端优化：IndexedDB 缓存

### 启用方法

1. 打开浏览器控制台（F12）
2. 执行以下命令：

```javascript
localStorage.setItem('octopus:cache-workbench', '1');
```

3. 刷新页面

### 验证效果

**测试步骤**:
1. 打开一个有大量工具调用的对话（100+ 事件）
2. 等待工作台完全加载
3. 刷新页面（Cmd+R / Ctrl+R）
4. 观察控制台输出

**预期结果**:
```
[WorkbenchCache] Restored snapshot from cache (245 events)
```

**性能对比**:
- **优化前**: 刷新后黑屏 2-3 秒，逐步重放事件
- **优化后**: 刷新后 <100ms 立即显示完整状态

### 禁用方法

```javascript
localStorage.removeItem('octopus:cache-workbench');
```

---

## 后端优化：自适应批处理

### 启用方法

**默认已启用**！无需配置。

### 验证效果

**观察日志**:
```bash
tail -f logs/octopus.log | grep AdaptiveBatch
```

**预期输出**:
```
[AdaptiveBatch] LOW tier: threshold=32 interval=50ms
[AdaptiveBatch] MID tier: threshold=64 interval=75ms  
[AdaptiveBatch] HIGH tier: threshold=256 interval=100ms
```

**性能指标**:
- 查看 WebSocket 消息频率（DevTools → Network → WS）
- 高吞吐场景下消息数量应减少 70%+

### 禁用方法

如果遇到问题，可以在代码中禁用：

```python
# runtime/sensing/gateway/realtime_react_stream.py
# 找到 _ReactBridgeState 初始化处
bridge = _ReactBridgeState(
    ...,
    enable_adaptive_batching=False  # 禁用自适应批处理
)
```

---

## 调试工具

### 1. 查看缓存内容

```javascript
// 打开 IndexedDB
// Chrome DevTools → Application → IndexedDB → workbench-snapshots

// 或使用代码查询
const cache = new WorkbenchSnapshotCache();
const snapshot = await cache.load('thread_xxx', 'turn_yyy');
console.log(snapshot);
```

### 2. 清空所有缓存

```javascript
// 清除过期快照
const cache = new WorkbenchSnapshotCache();
await cache.cleanExpired();

// 或直接删除数据库
indexedDB.deleteDatabase('workbench-snapshots');
```

### 3. 性能监控

```javascript
// 启用性能追踪
localStorage.setItem('octopus:debug:performance', '1');

// 查看指标
PerformanceTracker.getReport();
```

---

## 常见问题

### Q1: 刷新后没有看到缓存恢复

**原因**:
- 首次访问时缓存为空
- 缓存已过期（5 分钟）
- 特性开关未启用

**解决**:
1. 确认已设置 `localStorage.setItem('octopus:cache-workbench', '1')`
2. 打开一个对话，等待工作台加载
3. 再次刷新页面

### Q2: 自适应批处理没有生效

**检查**:
1. 后端是否重启（修改后需重启）
2. 查看日志是否有错误
3. 验证 `AdaptiveDeltaBuffer` 是否正确导入

**排查**:
```bash
# 检查后端是否运行
lsof -i :8000

# 查看错误日志
tail -f logs/octopus.log | grep -i error
```

### Q3: 缓存占用太多空间

**查看大小**:
```javascript
// Chrome DevTools → Application → Storage → IndexedDB
// 查看 workbench-snapshots 数据库大小
```

**清理**:
```javascript
// 自动清理 5 分钟前的快照
const cache = new WorkbenchSnapshotCache();
await cache.cleanExpired();
```

---

## 性能基准测试

### 运行测试

```bash
# 前端缓存测试
cd frontend
pnpm test workbench-cache

# 后端批处理基准
cd ..
.venv/bin/python benchmarks/benchmark_adaptive_batching.py
```

### 预期结果

**前端缓存**:
```
✓ should save and load snapshot (45ms)
✓ should measure load performance (52ms)
✓ should handle large snapshots (134ms)
```

**后端批处理**:
```
场景: 高吞吐 (80 chars/chunk)
固定批处理: 刷新 500 次, 耗时 592ms
自适应批处理: 刷新 127 次, 耗时 161ms
优化效果: -74.6% 刷新, -72.8% 耗时
```

---

## 生产部署检查清单

### 部署前
- [ ] 运行所有测试套件
- [ ] 验证 TypeScript 编译无错误
- [ ] 检查后端 Python 语法
- [ ] 备份生产数据库

### 部署步骤
1. [ ] 前端构建: `cd frontend && pnpm build`
2. [ ] 后端重启: `systemctl restart octopus-agent`
3. [ ] 验证服务健康: `curl http://localhost:8000/health`

### 部署后
- [ ] 监控错误日志（前 15 分钟）
- [ ] 检查 WebSocket 连接稳定性
- [ ] 验证缓存功能正常工作
- [ ] 观察自适应批处理日志

### 回滚方案
```bash
# 前端回滚
git checkout HEAD~1 frontend/
cd frontend && pnpm build

# 后端回滚
git checkout HEAD~1 runtime/
systemctl restart octopus-agent
```

---

## 下一步优化

### 已启用（立即生效）
- ✅ IndexedDB 缓存
- ✅ 自适应批处理

### 待启用（需要完善）
- ⏳ 增量快照计算
- ⏳ 协议版本化

### 未来计划
- 缓存预热（空闲时预加载）
- 智能压缩（大型快照）
- 多级缓存（内存 + IndexedDB）

---

## 联系支持

如有问题，请查看：
- 📖 完整文档: `docs/phase2-integration-complete.md`
- 🔧 集成计划: `docs/phase2-integration-plan.md`
- 🧪 测试用例: `frontend/src/components/workspace/__tests__/`
- 📊 基准测试: `benchmarks/benchmark_adaptive_batching.py`

祝使用愉快！🎉
