---
name: "react-best-practices"
description: "React 18+ 最佳实践技能，包含组件架构、性能优化、Hooks 使用规范。在编写或重构 React 组件时调用。"
---

# React 最佳实践

## 组件设计原则

### 1. 单一职责原则
- 每个组件只做一件事
- 复杂组件拆分为小组件
- 使用组合而非继承

### 2. Props 设计
- 保持 props 简洁明了
- 使用解构赋值
- 提供默认值
- 使用 TypeScript 类型定义

```tsx
// ✅ Good
interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  children: React.ReactNode;
  onClick?: () => void;
}

export function Button({
  variant = 'primary',
  size = 'md',
  disabled = false,
  children,
  onClick,
}: ButtonProps) {
  // ...
}
```

### 3. 状态管理
- 优先使用本地状态
- 复杂状态使用 useReducer
- 全局状态使用 Zustand/Redux
- 服务器状态使用 React Query

## Hooks 最佳实践

### useEffect
- 明确依赖数组
- 避免无限循环
- 清理副作用
- 拆分复杂逻辑

```tsx
// ✅ Good
useEffect(() => {
  const controller = new AbortController();
  fetchData(controller.signal);
  return () => controller.abort();
}, [dependency]);
```

### useMemo / useCallback
- 用于昂贵的计算
- 避免过度优化
- 注意依赖数组

```tsx
// ✅ Good - 昂贵的计算
const sortedData = useMemo(() => {
  return data.sort((a, b) => b.score - a.score);
}, [data]);

// ✅ Good - 传递给子组件的回调
const handleSubmit = useCallback(() => {
  submitForm(data);
}, [data]);
```

## 性能优化

### 1. 避免不必要的渲染
- 使用 React.memo
- 使用 useMemo/useCallback
- 优化 Context 值

### 2. 代码分割
- 使用 React.lazy
- 路由级别分割
- 组件级别分割

```tsx
const HeavyComponent = lazy(() => import('./HeavyComponent'));
```

### 3. 虚拟列表
- 长列表使用 react-window
- 避免渲染大量 DOM 节点

## 类型安全

### TypeScript 规范
- 严格模式启用
- 避免 any 类型
- 使用接口定义 Props
- 泛型组件

```tsx
// ✅ Good - 泛型组件
interface ListProps<T> {
  items: T[];
  renderItem: (item: T) => React.ReactNode;
}

export function List<T>({ items, renderItem }: ListProps<T>) {
  return <ul>{items.map(renderItem)}</ul>;
}
```

## 测试

- 使用 React Testing Library
- 测试用户行为而非实现
- 使用 jest-dom 匹配器
- 保持测试简洁

## 文件组织

```
src/
├── components/          # 可复用组件
│   ├── ui/             # 基础 UI 组件
│   └── features/       # 功能组件
├── hooks/              # 自定义 Hooks
├── utils/              # 工具函数
├── types/              # 类型定义
└── pages/              # 页面组件
```
