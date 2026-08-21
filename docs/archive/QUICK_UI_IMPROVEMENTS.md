# 子代理 UI 快速优化建议

## 现状评估

你们的系统已经有非常完善的实现了！主要组件：
- ✅ `SubtaskHoverPreview` - hover 预览卡片
- ✅ `ParallelSubtasksGrid` - 网格布局和整体进度
- ✅ `AgentIdentityCard` - 角色身份卡
- ✅ `MiniSubtaskRow` - 紧凑的任务行

## 建议的小优化（可选）

### 1. 增强主对话区的集群标题栏

**当前位置**: `frontend/src/components/workspace/messages/message-list.tsx:1738-1742`

**现在**:
```tsx
<div className="text-muted-foreground font-normal pt-2 text-sm mb-2">
  {t.subagents.executing(subagentEventsInTurn.length)}
</div>
```

**建议优化**:
```tsx
<div className="mb-3 flex items-center justify-between rounded-lg border border-border-default bg-muted/20 px-4 py-2.5">
  <div className="flex items-center gap-3">
    <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
      <UsersIcon className="size-4 text-primary" />
    </div>
    <div>
      <div className="text-sm font-semibold">
        {t.subagents.parallelExecution}
      </div>
      <div className="text-xs text-muted-foreground">
        {stats.done}/{stats.total} {t.subagents.completed}
        {stats.running > 0 && ` · ${stats.running} ${t.subagents.running}`}
      </div>
    </div>
  </div>
  {/* 整体进度条 */}
  <div className="flex items-center gap-3">
    <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted/60">
      <div 
        className="h-full rounded-full bg-success transition-all duration-500"
        style={{ width: `${(stats.done / stats.total) * 100}%` }}
      />
    </div>
    <span className="font-mono text-xs tabular-nums text-muted-foreground">
      {Math.round((stats.done / stats.total) * 100)}%
    </span>
  </div>
</div>
```

**效果**：
- 视觉上更突出，类似 Kimi 的标题栏
- 一眼看到整体进度
- 更专业的设计

### 2. Hover 卡片添加更多统计信息

**文件**: `frontend/src/components/workspace/messages/parallel-subtasks-grid.tsx:228-353`

**在 `SubtaskHoverPreview` 中添加**:

```tsx
{/* 现有的 meta 行后面添加 */}
<div className="mt-2 flex items-center gap-4">
  {task.iterationCount && (
    <div className="flex items-center gap-1.5 text-xs">
      <RefreshCwIcon className="size-3 text-muted-foreground" />
      <span className="text-muted-foreground">
        {task.iterationCount} {t.subagents.iterations}
      </span>
    </div>
  )}
  {task.filesTouched && task.filesTouched.length > 0 && (
    <div className="flex items-center gap-1.5 text-xs">
      <FileEditIcon className="size-3 text-muted-foreground" />
      <span className="text-muted-foreground">
        {task.filesTouched.length} {t.subagents.filesModified}
      </span>
    </div>
  )}
  {task.duration && (
    <div className="flex items-center gap-1.5 text-xs">
      <ClockIcon className="size-3 text-muted-foreground" />
      <span className="text-muted-foreground">
        {formatDuration(task.duration)}
      </span>
    </div>
  )}
</div>
```

### 3. 折叠状态显示更多信息

**在 `MiniSubtaskRow` 中**，当前只显示状态标签，可以添加：

```tsx
<div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
  <span className="truncate">{task.description}</span>
  {task.iterationCount && (
    <>
      <span>·</span>
      <span>{task.iterationCount} iterations</span>
    </>
  )}
  {task.filesTouched && task.filesTouched.length > 0 && (
    <>
      <span>·</span>
      <FileIcon className="inline size-3" />
      <span>{task.filesTouched.length}</span>
    </>
  )}
</div>
```

### 4. 添加键盘快捷键

为主对话区的子代理卡片添加快捷键支持：

```tsx
// 在 message-list.tsx 中
useEffect(() => {
  const handleKeyDown = (e: KeyboardEvent) => {
    // Cmd/Ctrl + E: 展开/折叠所有子代理
    if ((e.metaKey || e.ctrlKey) && e.key === 'e') {
      e.preventDefault();
      setAllCollapsed(prev => !prev);
    }
  };
  window.addEventListener('keydown', handleKeyDown);
  return () => window.removeEventListener('keydown', handleKeyDown);
}, []);
```

### 5. 移动端响应式优化

当前网格在小屏幕上可能显示不佳，建议：

```tsx
<div
  className={cn(
    "grid gap-2",
    // 移动端单列，平板2列，桌面根据数量决定
    "grid-cols-1 sm:grid-cols-2",
    visibleIds.length === 3 && "lg:grid-cols-3",
  )}
>
  {visibleIds.map(renderTask)}
</div>
```

## 总结

你们的实现已经非常完善了！主要的功能都有：
- ✅ Hover 预览
- ✅ 整体进度统计
- ✅ 角色身份卡
- ✅ 自动折叠/展开
- ✅ 可访问性支持

上面的优化都是**锦上添花**，不是必须的。如果要选优先级：

1. **高优先级**：增强主对话区的集群标题栏（视觉提升最明显）
2. **中优先级**：Hover 卡片添加统计信息（信息密度提升）
3. **低优先级**：其他细节优化

是否需要我实施第1项（集群标题栏优化）？
