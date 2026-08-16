# 本地沙箱风险边界（audit S-06）

## 结论

`process_sandbox: auto`（本地默认）在未安装内核级后端时退化为 **soft**：
进程仍受软约束（cwd 锁、环境变量白名单、输出上限、墙钟超时、kill-tree），
且沙箱感知的调用方（`exec_shell` 等）会拒绝明显越界操作——但这 **不是** 内核沙箱。

**风险边界**：在单用户本地桌面机上，一个被攻破/被提示注入的模型 shell
仍可访问宿主机文件系统与网络。这是单用户本地的**已接受边界**；需要更强隔离时
必须显式选择硬后端（见下）。

## 模式含义

| 模式 | 行为 |
|---|---|
| `auto`（默认） | 自动选最佳可用硬后端；无则回退 soft |
| `soft` / `direct` / `off` | 直接子进程 + 软约束策略（非内核隔离） |
| `strict` | 强制硬后端；不可用则拒绝执行（fail closed） |
| `bwrap` / `bubblewrap`（Linux） | 用户态命名空间/容器隔离 |
| `seatbelt` / `sandbox-exec`（macOS） | Seatbelt 沙箱 |
| Windows | Job Object + 受限令牌（自动） |

商用/共享模式强制硬后端，且不能降级到 soft（`runtime/safety/sandboxing/sandbox.py`）。

## 何时提升到 strict

- 多租户/共享机器
- 运行不可信代码或外部内容
- 合规要求（SOC2 等）

设置方式：

```sh
OCTOPUS_PROCESS_SANDBOX=strict        # 环境变量
# 或 config: execution.process_sandbox: strict
```

`strict` 下无硬后端时执行会被拒绝（fail closed），而不是静默降级。

## 默认值评审（2026-08）

- `config/base.yaml`: `auto` —— 本地单用户合理。
- `config/prod.yaml`: `strict` —— 生产强制硬隔离，正确。
- `config.example.yaml`: `auto` —— 示例随默认，正确。
- 结论：默认值无需变更；本文件明确记录 soft 的边界与升级路径。

相关实现：`runtime/safety/sandboxing/sandbox.py`、`runtime/platform/config/schema.py`。
