# Codex / OpenCode 共用 Echo 工具（2026-09-08）

## 实现

- 从 Codex 动态工具桥提取 `tool_engine/host_tool_broker.py`。原有 Codex 入口保留兼容包装，两种引擎使用同一套目录筛选、角色/租户检查、审批、插件停用复查、调用去重、原生执行器与执行记录。
- 提取 `tool_engine/role_instructions.py`，复用角色、记忆、工作模式和可信注册表中明确选中的 Skill 指令。
- 新增 `tool_engine/host_mcp.py`：每轮绑定一个宿主任务与账号，在随机回环端口提供 MCP。令牌仅进入 OpenCode 子进程环境，凭据不写入明文配置。回调显式恢复宿主 Session、ExecutionRequest 和能力租户上下文。
- OpenCode 仅连接该临时 MCP，继续禁用环境中未授权的插件和本地工具。已获授权的 Echo 工具经过原生执行器，MCP 调用不会直接执行注册表 handler。
- 工具结果转换为原有实时消息；共享工具显示原生名称，保留 OpenCode 执行引擎标记。停止时拒绝新调用，并等待已进入执行器的操作结束后关闭接口。
- OpenCode 使用 64 个相关工具的预算，Codex 保留 128 个。不是整个插件目录无上限注入模型。

## 验收发现及修复

实际对话最初被文件工作区检查拒绝。根因是 `_build_intent` 经过 `build_turn_metadata` 的存量会话合并时丢失 `permission_mode`、`execution_environment` 等本轮执行选择，导致界面“完全访问”在宿主变为 `default/sandbox`。现保留这些选择再交给原有服务端校验；操作员关闭免确认时，客户端不能凭 bypass 模式扩大权限。

原生 `_prepare_scoped_args` 将没有写入范围的读取工具一并拒绝，也已修复。只读任务可读取获授权文件，写入继续拒绝。此处没有绕过执行范围检查。

OpenCode 的模型写回改为保留 Zen 连接的完整模型坐标，使后续回合继续识别同一个连接和模型。

失败历史中模型曾错误地声称处于 Plan Mode。现在每轮系统指令带上宿主当前的写入权限和产物目录，要求按本轮实际目录与执行结果判断。权限本身仍由执行器检查。

## 已验证证据

- 官方 OpenCode 1.18.29 + Zen `big-pickle` 实际连接临时 MCP，执行 `read_file`、`write_text_file`、测试插件动作 `plugin_probe`。文件从 `before` 改为 `after`，插件收到正确的 actor/tenant/turn，最终状态完成。证据：`.codex-run/host-mcp-validation/1788856004/evidence.json`。
- 真实前端对话验收：线程 `traU9ieqUt5JIqiAzzgkhl`，回合 `trn_6decdb5e256d4726`，2026-09-08 16:54 开始。当前角色 Eve、引擎 OpenCode、模型 `big-pickle`、权限“完全访问”；实际调用 `read_file` 和 `write_text_file`，最终 `turn_completed: completed`，无错误。输出文件 `D:/echo agent/.codex-run/octopus/data/workspaces/traU9ieqUt5JIqiAzzgkhl/output/final/echo-tool-check.txt` 已核对，文本与输入一致（换行按文本读取规范化）。独立落盘证据：`.codex-run/host-tool-acceptance/evidence.json`。
- 实际回合目录包含 64 个工具及 `write_text_file`，执行器收到 `bypassPermissions/local`。回合结束后官方 OpenCode 子进程已退出。
- MCP HTTP 测试覆盖：未认证请求拒绝、真实原生文件读写、越界写入拒绝、插件身份上下文、停用后拒绝、跨账号任务绑定拒绝、停止后拒绝、关闭时等待已开始操作、只读任务读写分离。
- 存量会话测试覆盖完全访问、自动审核、默认模式和服务端关闭免确认四种情况。
- 原有 Codex 动态工具、角色指令、记忆语义和 App Server 流程：48 项通过；权限与存量会话相关测试：69 项通过；新增 MCP 与原生范围/工具桥检查：103 项通过（各组含重叠用例）。前端 TypeScript 检查通过。
- 最终相关回归 `tests/test_host_mcp.py`、`tests/test_opencode_backend.py`：19 项通过；本次修改的 Python 文件 Ruff 检查通过。

## 边界

后续已补上跨引擎的文本历史衔接，见 [跨引擎续聊验收](cross-engine-history-2026-09-08.md)。

可复用的是当前角色获授权的注册工具和插件动作。没有把任意 OpenCode/Codex 用户配置、插件 MCP 进程、交互式插件界面导入 Echo。工具图片/音频的完整多模态传递、OpenCode 团队编排尚未接入；桌面及外部插件实际效果仍依赖对应能力和模型。

2026-09-12 补充：三个浏览器/电脑截图工具的图片回传现已接入 Codex 动态工具和 OpenCode MCP，见[截图回传验证](automation-image-return-2026-09-12.md)。这不表示任意工具图片、音频或完整桌面视觉操作均已验收。

协议依据：[OpenCode MCP](https://opencode.ai/docs/mcp-servers/)、[官方 1.18.29 MCP 工具转换](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/mcp/catalog.ts)。
