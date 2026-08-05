# Checklist

## Delta 1 · 对话模式优化
- [x] `modeFromProjectKind` 不再恒返回 `develop`，各检测类型有正确映射
- [x] 模式切换失败时 UI 模式回滚到原值并有提示
- [x] 手动覆盖标记持久化到 localStorage，刷新后不被自动检测抢占
- [x] 相关单测（映射/持久化）通过（9 个）

## Delta 2 · 流式增量重算
- [x] 单 token delta 时，历史 turns 的消息引用保持不变
- [x] live tool events 在无相关变化时保持引用稳定，不每次全量重建
- [x] WeakMap 身份缓存语义保留，React.memo 仍能跳过未变化内容
- [x] `realtime-adapter.test.ts`（及相关）通过（66 个）

## Delta 3 · 工作区 resize 逻辑抽取
- [x] `useResizablePanel` hook 封装 sidebar/secondary 的 drag/keyboard/clamp/persist 逻辑
- [x] 拖拽、键盘调宽、localStorage 持久化行为与改造前一致（type-check 通过）

## Delta 4 · 工作栏折叠态合并
- [x] collapsed/expanded 两套结构合并为共享渲染逻辑
- [x] 折叠/展开视觉与行为不回退（type-check 通过）