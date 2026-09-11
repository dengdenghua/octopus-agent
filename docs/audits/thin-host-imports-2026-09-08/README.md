# 外部执行宿主的导入边界测量

这是包导入测量，不是整个应用冷启动、运行时峰值内存或安装体积测量。

环境：本机 Windows，Python 3.12.14。每个目标各执行 3 个新的 Python 进程，导入耗时取中位数；没有启动 OpenCode、MCP 服务或向模型发请求。Windows 工作集通过当前进程的 `GetProcessMemoryInfo` 读取，表中的 MiB 为三次样本的近似中位数。系统文件缓存与机器负载没有控制，时间不作为自动测试门槛。

| 导入目标 | 模块数：前 → 后 | 耗时：前 → 后 | 工作集：前 → 后 | 原生 LLM planner：前 → 后 |
| --- | --- | --- | --- | --- |
| `runtime.platform.config.schema` | 852 → 299 | 0.847 → 0.188 秒 | 65 → 33 MiB | 已加载 → 未加载 |
| `runtime.execution.request` | 142 → 142 | 0.027 → 0.027 秒 | 20.5 → 20.5 MiB | 未加载 → 未加载 |
| `runtime.execution.opencode_backend` | 1102 → 671 | 1.338 → 0.562 秒 | 91 → 56 MiB | 已加载 → 未加载 |
| `runtime.sensing.gateway.realtime_opencode_backend` | 1168 → 935 | 1.575 → 0.895 秒 | 95 → 71 MiB | 已加载 → 未加载 |

原始记录：[before.json](before.json)、[after.json](after.json)。前测在本次导入重构前采集，后测在最终导入改动后采集。

## 改动

- 配置包只在请求 `BuiltStack` / `build_from_config` 时导入构建器。
- cerebrum 包只在请求具体 planner 时加载其实现，公共策略子模块不再隐式导入原生 LLM planner。
- 工具包只在请求 `ToolExecutor` / `StepExecutionError` 时加载执行器，协议与分类导入保持可用。
- `HostMCPConnection` 移到不依赖 MCP 服务的连接数据模块。原 `host_mcp` 路径保留同一类的导出，字段不可变且 token 不出现在 repr 中。
- OpenCode 托管进程使用连接数据模块；实时适配器在真正执行任务时才加载宿主工具服务与 broker。

公开名称、`__all__`、类身份与默认完整栈的构建方式保留。独立进程测试验证公共宿主模块不加载 native planner，并验证 OpenCode 后端导入不加载 `mcp`、`uvicorn` 或宿主 MCP 服务。

最终后端回归 631 项通过，没有排除配置用例；包括原生 planner、原生执行循环、工具协议、MCP 实际传输和外部执行的兼容性验证。Ruff 检查通过。

## 复现

在仓库根目录运行：

```powershell
.venv/Scripts/python.exe benchmarks/probe_host_imports.py --samples 3 --output .codex-run/thin-host-imports-current.json
.venv/Scripts/python.exe -m pytest tests/test_host_import_boundary.py -q --no-cov
```

目前完整应用仍会按配置构建原生 planner 并装配团队协调能力。本结果证明外部执行与公共配置的导入依赖已拆开，不证明整个应用已经不再需要原生 planner。
