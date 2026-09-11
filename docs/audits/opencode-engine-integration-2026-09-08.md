# OpenCode / Zen 接入验收（2026-09-08）

已把官方 OpenCode 1.18.29 作为独立执行引擎接入 Echo，并在原 NAS 对话中完成真实调用。没有修改或仿造 Zen 的客户端鉴别请求头，也没有把 `opencode serve` 包装成供原生/Codex 使用的模型接口。

## 实测结果

| 验证 | 结果 |
| --- | --- |
| 官方引擎 + `big-pickle` 网页搜索 | 搜索 Synology 官网并输出真实官网链接，完成回执 cost=0 |
| 原 NAS 调研任务 | `trn_ca1f0a82897f4150`，31.89 秒，3 次网页搜索，completed |
| 同一对话连续追问 | `trn_9e20ed051bb1456a`，48.06 秒，恢复上轮上下文并补充来源链接，completed |
| 中止测试 | 1.41 秒内返回取消事件，官方会话回到 idle，托管进程退出 |
| 后端回归 | 48 passed（新引擎、统一引擎选择、实时执行上下文） |
| 前端回归 | 171 passed（引擎偏好、请求序列化、历史回放、消息转换及模型边界） |
| TypeScript / Ruff | 通过 |

验收对话：`http://localhost:3310/#/workspace/realtime/t5m4_s_I_8Q3bpl0dhEnjU`。上述验收证明调用和会话功能可用，不代表对模型生成的 NAS 行业数据进行了独立事实审计，也不保证其他 Zen 模型或未来额度始终可用。

## 运行方式

当前安装：`.codex-run/tools/opencode/1.18.29/opencode.exe`。启动脚本从 `.codex-run/runtime-paths.json` 的 `opencode` 字段加载路径；其他环境可通过 PATH 或 `OCTOPUS_OPENCODE_BIN` 指定安装。

界面：输入框「执行引擎 → OpenCode」，模型列表只显示 Zen 模型。角色仍由 Echo 管理。自动引擎规则保持原样，使用 OpenCode 需明确选择。模型 Auto 对应 `big-pickle`；具体模型选择不做静默替换。

每个租户、账号、对话使用独立的 OpenCode 状态目录。子进程监听随机回环端口并启用随机 Basic Auth 密码。凭据沿用当前账号已连接的 Zen 加密密钥，仅注入子进程环境，不进入前端或明文配置。禁用共享、自动更新、外部 skills、项目配置及默认插件。默认拒绝工具，仅在宿主允许网络时开放 `websearch`、`webfetch`。

消息通过官方会话 API 提交，增量快照转换为 Echo 的文字和工具执行事件。停止及异常路径中止官方会话并关闭进程，持久化会话供下次恢复。检查消息级 `info.error` 和终止原因，HTTP 200 不能单独作为成功依据。工具分组和最终回答都带实际执行引擎标记。

## 当前边界

首轮支持文本对话、网页搜索、网页读取、连续追问、流式输出、停止。后续已接入 Echo 共享工具、显式 Skill 指令和已授权插件动作，详见 [共享工具验收](shared-engine-tools-2026-09-08.md)。团队编排及完整多模态/交互式插件界面仍未接入；原生和 Codex 的现有能力不经 OpenCode 转发。

协议参考：[OpenCode Server](https://opencode.ai/docs/server/)、[OpenCode Permissions](https://opencode.ai/docs/permissions/)。
