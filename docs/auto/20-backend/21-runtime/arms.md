---
type: "RuntimeSubsystem"
title: "Arms · 执行工具组"
description: "Arm preset 工厂 · 将原始 Skill 按职责打包成 arm（fs_writer / git / shell / browser_read / ...）。"
tags: ["backend", "runtime"]
tier: "core"
---
# Arms · 执行工具组

> Arm preset 工厂 · 将原始 Skill 按职责打包成 arm（fs_writer / git / shell / browser_read / ...）。

**Source**: `runtime/execution/arms/`

## Exports

- `PRESET_FACTORIES`
- `Arm`
- `ArmPool`
- `ByteStreamBuffer`
- `ExtensionContext`
- `ExtensionInfo`
- `ExtensionRegistry`
- `ExtensionState`
- `GateError`
- `LazyArmPool`
- `LazyPool`
- `LazyPromise`
- `LazyValue`
- `LineBuffer`
- `ProcessTreeManager`
- `PromiseGate`
- `SafeRmConfig`
- `SafeRmProtector`
- `SessionLock`
- `ShellEnvState`
- `ShellExecEvent`
- `ShellExecTelemetry`
- `ShellStateManager`
- `ToolCallContext`
- `ToolCallResult`
- `ToolDefinition`
- `ToolProvider`
- `ToolRegistry`
- `Worker`
- `get_shell_telemetry`
- `get_tool_registry`
- `make_all_presets`
- `make_code_arm`
- `make_coder_arm_v2`
- `make_desktop_operator_arm`
- `make_ecommerce_mind_arm`
- `make_file_arm`
- `make_general_arm`
- `make_search_arm`
- `make_shell_arm`
- `make_vibe_selling_arm`

## Modules

| Module | Summary |
| --- | --- |
| `base.py` | — |
| `enterprise_cache.py` | Enterprise Arm 本地决策层(Ganglion). |
| `extension_registry.py` | Dynamic extension registry — hot-pluggable skill registration. |
| `lazy_loader.py` | Lazy loading patterns — on-demand resource initialization. |
| `output_buffer.py` | Dual-layer output buffer for shell command output. |
| `presets.py` | — |
| `process_tree.py` | Process tree management and graceful shutdown utilities. |
| `promise_gate.py` | Promise gate — async concurrency control via chained promises. |
| `safe_rm.py` | safe_rm — file protection mechanism for shell commands. |
| `shell_state.py` | Shell environment state snapshot model. |
| `shell_state_manager.py` | Shell state snapshot manager. |
| `shell_telemetry.py` | Shell execution telemetry events. |
| `specialized.py` | — |
| `tool_registry.py` | MCP-style tool registry — declarative tool registration pattern. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `base.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Worker` |  |
| class | `class ArmPool` |  |

### `enterprise_cache.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EnterpriseDecisionCache` | Enterprise Arm 的本地决策缓存(Ganglion 层). |

### `extension_registry.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ExtensionState(StrEnum)` | Lifecycle state of a registered extension. |
| class | `class ExtensionInfo` | Metadata about a registered extension. |
| class | `class ExtensionContext` | Context passed to extension activation functions. |
| class | `class ExtensionRegistry` | Registry for dynamically loadable extensions/skills. |

### `lazy_loader.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class LazyPromise(Generic[T])` | A promise that defers execution until first access. |
| class | `class LazyValue(Generic[T])` | A value that is computed on first access and cached. |
| class | `class LazyPool(Generic[T])` | A pool of lazily-initialized resources. |
| class | `class LazyArmPool` | Specialized lazy pool for Arm resources. |

### `output_buffer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ByteStreamBuffer` | Byte-oriented buffer with a hard size cap. |
| class | `class LineBuffer` | Line-oriented buffer with a hard line cap. |

### `presets.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def make_web_read_arm(runtime)` |  |
| func | `def make_browser_read_arm(runtime)` |  |
| func | `def make_browser_interact_arm(runtime)` |  |
| func | `def make_fs_writer_arm(runtime)` |  |
| func | `def make_git_arm(runtime)` |  |
| func | `def make_shell_arm(runtime)` |  |
| func | `def make_desktop_operator_arm(runtime)` |  |
| func | `def make_mobile_operator_arm(runtime)` | 移动操作 Arm —— 控制 Android 设备. |
| func | `def make_mobile_browser_operator_arm(runtime)` | 移动浏览器操作 Arm —— 在 Android 上用 GeckoView 自动化. |
| func | `def make_general_arm(runtime)` |  |
| func | `def make_coder_arm_v2(runtime)` |  |
| func | `def make_vibe_selling_arm(runtime)` |  |
| func | `def make_ecommerce_mind_arm(runtime)` |  |
| func | `def make_all_presets(runtime)` |  |

### `process_tree.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ProcessTreeManager` | Manages cross-platform process tree lifecycle. |

### `promise_gate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class GateError(Exception)` | Raised when a gate entry is rejected. |
| class | `class PromiseGate` | A promise chain gate for serializing async operations. |
| class | `class SessionLock` | Session-based lock with file-system persistence. |

### `safe_rm.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ProtectionLevel` |  |
| class | `class SafeRmConfig` | Configuration for safe_rm protection. |
| class | `class SafeRmProtector` | Intercepts and blocks dangerous file operations. |

### `shell_state.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ShellEnvState` | Immutable snapshot of a shell environment. |

### `shell_state_manager.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ShellStateManager` | Manages shell environment state across subprocess executions. |

### `shell_telemetry.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ShellExecEvent` | A single structured telemetry event. |
| class | `class ShellExecTelemetry` | Manages shell execution telemetry events. |
| func | `def get_shell_telemetry()` | Get or create the global shell telemetry instance. |

### `specialized.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def make_code_arm(runtime, enable_exec, enable_git_network, enable_quality)` |  |
| func | `def make_search_arm(runtime)` |  |
| func | `def make_file_arm(runtime)` |  |

### `tool_registry.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ToolDefinition` | Declarative definition of a tool. |
| class | `class ToolCallContext` | Context passed to tool call event handlers. |
| class | `class ToolCallResult` | Result of a tool call. |
| class | `class ToolProvider` | A group of tools registered under a single provider. |
| class | `class PreToolDecision(StrEnum)` | Decision of a pre-execute gate (dsh ``tools/pre-execute``). |
| class | `class PostToolDecision(StrEnum)` | Decision of a post-execute gate (dsh ``tools/post-execute``). |
| class | `class ToolRegistry` | Registry for MCP-style tools. |
| func | `def get_tool_registry()` | Get or create the global tool registry. |


## Who imports this

**10** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/execution/`** · 5 file(s)
  - `runtime/execution/agents/base.py`
  - `runtime/execution/agents/loader.py`
  - `runtime/execution/swarm/_runtime_helpers.py`
  - `runtime/execution/swarm/drive.py`
  - `runtime/execution/swarm/runtime.py`
- **`runtime/platform/`** · 2 file(s)
  - `runtime/platform/ui/_app_meta.py`
  - `runtime/platform/ui/_app_routers_extra.py`
- **`runtime/sensing/`** · 1 file(s)
  - `runtime/sensing/gateway/terminal_router.py`

