# 嵌入式 Agent 内核

`runtime.kernel.AgentKernel`（也可以通过 `from runtime import kernel` 访问）是
宿主应用接入 Octopus 的稳定边界。它把
Planner、工具执行、Skills、记忆/审计、安全策略和实时运行时组合成一个可
移植的内核对象；宿主不需要复制或调用 `runtime/platform/ui` 的内部实现。

## 最小接入

```python
from runtime.kernel import AgentKernel
from runtime.platform.config import load_from_yaml
from runtime.platform.ui import create_app

config = load_from_yaml("config.local.yaml")
kernel = AgentKernel.build(config)
app = create_app(kernel=kernel)
```

需要实时对话时，宿主通过内核创建一次运行时，并把自己的线程、身份和代理
注册表作为适配器传入：

```python
runtime = kernel.create_realtime_runtime(
    agent_registry=agent_registry,
    thread_store=thread_store,
)
result = await kernel.handle_request("turn/start", params, emitter)
```

`create_realtime_runtime` 是幂等的：第一次创建后不允许用另一组宿主参数重新
配置；需要切换宿主配置时应创建新的 `AgentKernel`。

## 边界

内核负责：

- `runtime/core/cerebrum`：规划、ReAct 与任务理解
- `runtime/core/graph_runtime`：多节点任务调度
- `runtime/execution`：Arms、Skills、ToolExecutor 和 MCP
- `runtime/memory`：Journal、线程事件和上下文
- `runtime/safety`：审批、信任、预算和审计
- `runtime/protocol`：实时事件协议

宿主负责：

- HTTP/WebSocket、桌面窗口和通知
- 登录身份、线程访问策略和宿主存储
- 工作台/相册/媒体等应用页面
- 应用市场与插件安装 UI

应用和插件可以使用内核提供的注册表或 ServiceBus，但内核不能反向导入某个
工作台页面。这样应用可以一起打包，内核仍能被 CLI、服务端或另一个桌面
宿主复用。

## 生命周期

- `AgentKernel.build(config)`：从 `AgentConfig` 构建完整内核。
- `AgentKernel.from_stack(stack)`：包装已有 `BuiltStack`，用于兼容旧宿主。
- `kernel.create_realtime_runtime(...)`：按需创建实时适配层。
- `await kernel.aclose()`：先排空活动实时任务，再释放 MCP 等资源。
- `kernel.close()`：同步宿主的快速释放入口；重复调用安全。

## 桌面打包

桌面端仍可以使用 Electron 作为窗口宿主、PyInstaller 作为内核载体：

```text
桌面安装包
└── Electron 宿主
    └── PyInstaller AgentKernel
        ├── 本地 API / WebSocket
        ├── Agent 内核
        └── 应用与插件资源
```

这不是两个应用通过临时 HTTP 接口互相嫁接，而是一个安装包中的宿主和一个
明确的内核组件。若宿主本身是 Python，可直接同进程调用；Node、Rust 或 Go
宿主则使用同包内的本地内核进程，接口仍保持一致。
