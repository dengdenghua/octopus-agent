# 子代理卡片 UI 优化方案

## 现状分析

### 当前实现
- ✅ 主对话区显示子代理卡片
- ✅ ParallelSubtasksGrid 网格布局
- ✅ SubtaskCard 显示基本信息（名称、avatar、状态）
- ✅ 实时进度点动画

### 对比 Kimi 的差距
1. **信息密度低**：卡片只显示任务标题，缺少详细步骤
2. **缺少整体控制**：没有一键折叠/展开所有子代理
3. **缺少进度摘要**：没有显示 "X/Y 已完成" 的总体进度
4. **交互反馈不足**：点击卡片后没有详细视图
5. **视觉层级不明确**：集群标题不够醒目

## 优化方案

### 1. 增强集群标题栏 (Phase 1 - 高优先级)

**位置**：`frontend/src/components/workspace/messages/message-list.tsx:1738-1742`

**当前代码**：
```tsx
<div className="text-muted-foreground font-normal pt-2 text-sm mb-2">
  {t.subagents.executing(subagentEventsInTurn.length)}
</div>
```

**优化后**：
```tsx
<div className="flex items-center justify-between rounded-lg bg-muted/30 px-4 py-3 mb-3">
  <div className="flex items-center gap-3">
    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary/10">
      <UsersIcon className="w-4 h-4 text-primary" />
    </div>
    <div>
      <div className="font-semibold text-sm">
        {t.subagents.parallelExecution}
      </div>
      <div className="text-xs text-muted-foreground">
        {completedCount}/{totalCount} {t.subagents.completed} · {runningCount} {t.subagents.running}
      </div>
    </div>
  </div>
  <div className="flex items-center gap-2">
    <Button 
      variant="ghost" 
      size="sm"
      onClick={handleCollapseAll}
    >
      {allCollapsed ? t.subagents.expandAll : t.subagents.collapseAll}
    </Button>
  </div>
</div>
```

**新增字段**：
- `parallelExecution`: "并行执行"
- `completed`: "已完成"
- `running`: "运行中"
- `expandAll`: "展开全部"
- `collapseAll`: "折叠全部"

### 2. 优化 SubtaskCard 信息密度 (Phase 2 - 高优先级)

**文件**：`frontend/src/components/workspace/messages/subtask-card.tsx`

**目标**：折叠状态下显示更多有用信息

**当前折叠显示**：
- 名称 + 状态标签

**优化为**：
```tsx
// 折叠状态显示
<div className="flex items-center gap-3 px-3 py-2">
  {/* 左侧：Avatar + 基本信息 */}
  <div className="flex items-center gap-2 flex-1 min-w-0">
    <div className="avatar">{task.avatarEmoji}</div>
    <div className="flex-1 min-w-0">
      <div className="font-medium text-sm truncate">{task.name}</div>
      <div className="text-xs text-muted-foreground truncate">
        {task.description || task.latestToolCall}
      </div>
    </div>
  </div>
  
  {/* 右侧：状态 + 进度 */}
  <div className="flex items-center gap-2 shrink-0">
    {/* 迭代次数 */}
    {task.iterationCount && (
      <Badge variant="secondary" className="text-xs">
        {task.iterationCount} {t.subagents.iterations}
      </Badge>
    )}
    
    {/* 文件修改数 */}
    {task.filesTouched && task.filesTouched.length > 0 && (
      <Badge variant="secondary" className="text-xs">
        <FileIcon className="w-3 h-3 mr-1" />
        {task.filesTouched.length}
      </Badge>
    )}
    
    {/* 状态图标 */}
    {icon}
    
    {/* 进度点 */}
    {isActive && <DotProgress ... />}
  </div>
</div>
```

### 3. 添加子代理详情侧边栏 (Phase 3 - 中优先级)

**类似 Kimi 的右侧详情面板**

**实现方式**：
- 点击卡片时，在右侧滑出详情面板
- 显示完整的子代理执行历史
- 显示所有工具调用和输出
- 显示文件修改列表

**组件结构**：
```tsx
<Sheet open={selectedSubagent !== null} onOpenChange={...}>
  <SheetContent side="right" className="w-[600px]">
    <SheetHeader>
      <div className="flex items-center gap-3">
        <div className="avatar-large">{task.avatarEmoji}</div>
        <div>
          <SheetTitle>{task.name}</SheetTitle>
          <SheetDescription>{task.role}</SheetDescription>
        </div>
      </div>
    </SheetHeader>
    
    <div className="space-y-4 mt-6">
      {/* 统计信息 */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="迭代次数" value={task.iterationCount} />
        <StatCard label="执行时长" value={formatDuration(task.duration)} />
        <StatCard label="文件修改" value={task.filesTouched.length} />
      </div>
      
      {/* 执行时间线 */}
      <div>
        <h3 className="font-semibold mb-2">执行历史</h3>
        <Timeline>
          {task.messages.map(msg => (
            <TimelineItem
              key={msg.id}
              time={msg.timestamp}
              content={formatMessage(msg)}
            />
          ))}
        </Timeline>
      </div>
      
      {/* 文件修改列表 */}
      {task.filesTouched && task.filesTouched.length > 0 && (
        <div>
          <h3 className="font-semibold mb-2">修改的文件</h3>
          <ul className="space-y-1">
            {task.filesTouched.map(file => (
              <li key={file} className="text-sm">
                <FileIcon className="inline w-3 h-3 mr-2" />
                {file}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  </SheetContent>
</Sheet>
```

### 4. 添加紧凑视图选项 (Phase 3 - 低优先级)

**类似 Kimi 底部的缩略视图**

在集群标题栏添加视图切换：
```tsx
<ToggleGroup type="single" value={viewMode} onValueChange={setViewMode}>
  <ToggleGroupItem value="grid">
    <GridIcon className="w-4 h-4" />
  </ToggleGroupItem>
  <ToggleGroupItem value="compact">
    <ListIcon className="w-4 h-4" />
  </ToggleGroupItem>
</ToggleGroup>
```

紧凑视图只显示：
- Avatar
- 编号
- 完成状态

### 5. 增强进度可视化 (Phase 2 - 中优先级)

**在集群标题下方添加整体进度条**：

```tsx
<div className="relative h-2 w-full rounded-full bg-muted overflow-hidden">
  <div 
    className="absolute inset-y-0 left-0 bg-gradient-to-r from-primary to-primary/80 transition-all duration-500"
    style={{ width: `${(completedCount / totalCount) * 100}%` }}
  />
  {/* 运行中的子代理用脉动动画 */}
  {runningCount > 0 && (
    <div 
      className="absolute inset-y-0 bg-primary/30 animate-pulse"
      style={{ 
        left: `${(completedCount / totalCount) * 100}%`,
        width: `${(runningCount / totalCount) * 100}%`
      }}
    />
  )}
</div>
```

## 实现优先级

### Phase 1 - 立即实施 (1-2天)
1. ✅ 增强集群标题栏（进度摘要 + 折叠控制）
2. ✅ 整体进度条
3. ✅ SubtaskCard 折叠状态信息增强

### Phase 2 - 短期目标 (3-5天)
1. 子代理详情侧边栏
2. 迭代次数和文件修改数显示

### Phase 3 - 长期优化 (1-2周)
1. 紧凑视图模式
2. 更丰富的统计图表
3. 性能优化（虚拟滚动）

## 需要的 i18n 字段

```typescript
// frontend/src/core/i18n/locales/zh-CN.ts
subagents: {
  parallelExecution: "并行执行",
  completed: "已完成",
  running: "运行中",
  pending: "等待中",
  failed: "失败",
  expandAll: "展开全部",
  collapseAll: "折叠全部",
  iterations: "次迭代",
  duration: "执行时长",
  filesModified: "文件修改",
  executionHistory: "执行历史",
  modifiedFiles: "修改的文件",
  viewDetails: "查看详情",
}
```

## 技术注意事项

1. **性能**：当子代理数量 > 20 时，考虑虚拟滚动
2. **状态管理**：使用 `useState` 管理折叠状态，避免重渲染
3. **动画**：使用 `framer-motion` 实现流畅的展开/折叠动画
4. **响应式**：移动端自动切换到紧凑视图
5. **可访问性**：确保键盘导航和屏幕阅读器支持

## 预期效果

实施后，我们的子代理 UI 将：
- ✅ 信息密度更高，一屏显示更多内容
- ✅ 交互更直观，快速了解整体进度
- ✅ 支持深度探索，点击查看详细执行历史
- ✅ 视觉层级清晰，重要信息突出
- ✅ 与 Kimi 的体验对齐甚至超越
