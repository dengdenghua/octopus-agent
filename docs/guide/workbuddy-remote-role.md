# WorkBuddy 远程角色

Echo 通过 A2A 委派完整任务，桥接服务使用本机 WorkBuddy 官方 CLI 执行，返回进度、回复和文件产物。这不是模型 API，也不把 WorkBuddy 积分转成其他引擎的余额。

## 启动与注册

在安装了 WorkBuddy 和 Node.js 的电脑上，从 Echo 项目目录运行：

```powershell
.\.venv\Scripts\python.exe -m runtime.sensing.gateway.workbuddy_bridge --permission-mode acceptEdits
```

另开终端，注册到本机 Echo 的远程角色目录：

```powershell
.\.venv\Scripts\python.exe -m runtime.sensing.gateway.workbuddy_bridge --register
```

也可在 Echo 的「远程角色」页面添加地址 `http://127.0.0.1:8321`。点击 WorkBuddy 即可发送任务；执行中的任务可取消，完成后点击文件名下载。点击历史任务标题可重新查看结果及下载产物。

注册命令重复运行会更新同一个地址，不会创建重复角色。服务需要保持运行；本版本不会自动开机启动，也不把 WorkBuddy 的安装包复制到 Echo 安装包。

依赖为现有项目的 `serve` 和 `mcp` extras（包括 `a2a-sdk>=1.1,<2`）。Windows 开发环境可使用 `.venv/Scripts/python.exe`；其他系统使用已安装这些依赖的 Python 3.11+。

## 配置

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--port` | `8321` | 本机桥接端口 |
| `--cli` | 自动发现 | `codebuddy.js` 或原生 CLI 路径 |
| `--model` | `auto` | 官方 CLI 模型标识 |
| `--permission-mode` | `default` | `default`、`acceptEdits` 或 `plan` |
| `--timeout` | `300` | 单次 CLI 执行超时秒数 |
| `--max-turns` | `20` | 单次任务最大代理轮数 |
| `--data-dir` | `~/.octopus/workbuddy-bridge` | 会话映射、A2A 任务库和工作目录 |

可通过 `ECHO_WORKBUDDY_CLI`、`ECHO_WORKBUDDY_NODE` 指定 CLI 和 Node.js 路径。不使用 shell 拼接启动参数。

认证交给官方 CLI。先在官方客户端/CLI 完成登录；桥接不读取、复制或返回登录 token。当前 Windows 的 WorkBuddy 2.137.1 已通过现有本机登录完成真实文本和文件任务，但没有核对积分余额变化，不能据此断言具体套餐扣费来源。

权限由桥接电脑的所有者选择。`acceptEdits` 允许原生文件编辑；不会设置 `--dangerously-skip-permissions`。桥接关闭额外 MCP 配置和后台任务。工作目录是文件组织方式，不是操作系统沙箱；CLI 仍以运行它的系统用户权限工作。更强隔离应使用独立系统用户或虚拟机。

## 放在另一台电脑

桥接只监听 `127.0.0.1`，不提供公网匿名执行入口。可用 SSH 转发：

```text
ssh -N -L 8321:127.0.0.1:8321 user@workbuddy-host
```

然后在 Echo 注册 `http://127.0.0.1:8321`。两端使用相同端口，以匹配 Agent Card 公布的地址。任务读取的文件位于 WorkBuddy 那台电脑；本版本输入为文本，不会自动上传 Echo 本地文件。

## 调用与续接

可使用 Echo 已有的登录认证访问：

```text
POST /api/a2a/agents/{agent_id}/send
{"text":"创建一份项目简报，保存为 report.md","local_task_id":"my-unique-task-id"}
```

返回 `context_id` 后，下一次在请求体中附带该字段即可续接同一个 WorkBuddy 会话。新任务省略它，使用独立会话和工作目录。原生 session ID 由桥接内部保存，不允许调用方指定。页面发送默认创建新任务，程序调用可显式续接。

直接使用 A2A 时：

- Agent Card：`/.well-known/agent-card.json`
- JSON-RPC：`/a2a/rpc`，支持 A2A 1.0 和 SDK 的 0.3 兼容接口
- 健康检查：`/health`（表示桥接运行中，登录可用性在真实任务中验证）

群聊中打开「成员」选择器，搜索 WorkBuddy 并添加。输入框选择该成员的 @提及，或输入 `@WorkBuddy 你的任务`，即可由远程角色执行并以 WorkBuddy 身份回复。也可以同时点名本地成员。远程调用失败会明确提示，不会由本地模型代答。

远程角色只响应单独点名：普通聊天、自动协作模式和 `@所有人` 不会自动消耗其额度。群成员被移除、静音或设为观察者后不能执行。为避免收紧历史权限后沿用旧记忆，群聊每次使用独立远程会话，只发送当前任务与服务器授权可见的历史；不会自动上传本地文件。返回文件可在远程角色面板的任务记录中下载。

群聊派发已接入，原有通用 `call_agent` 工具仍只负责本地角色。更新后需要重新启动 Echo 后端并刷新前端；WorkBuddy 桥接服务继续保持运行。

含远程成员的派发每条用户消息执行一轮，不自动追加辩论或复核调用。群聊任务镜像有大小上限；返回内容超过约 900 KB 时保留最后回复，附件需从 WorkBuddy 任务工作目录获取，界面会明确提示。

每次返回当前专用工作目录中新建或修改的非隐藏文件，最多 16 个、总计 8 MiB；超限文件保留在远端工作目录，名称记录在任务 metadata 的 `omitted_files` 中。任务和文件快照持久化在本机 A2A 数据库，已完成结果可在桥接重启后读取。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workbuddy_bridge.py tests/test_workbuddy_a2a_relay.py tests/test_a2a_router.py tests/test_a2a_server.py -q
```

2026-09-11 已验证真实 WorkBuddy 创建文本文件、通过 A2A 回传文件、续接同一会话，以及 Echo 接收端保存最终回复和二进制产物。
