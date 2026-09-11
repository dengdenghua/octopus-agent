# 跨引擎续聊（2026-09-08）

## 结果与实现

Echo 的会话事件日志作为历史来源。原生引擎继续使用其历史适配器；Codex 与 OpenCode 增加共享的 `realtime_engine_history.py` 投影，补齐之前只续接各自内部会话、看不到其他引擎回合的问题。

- Codex 和 OpenCode 按日志中实际执行引擎与已确认的历史接收记录选择增量。历史接收记录复用现有 `execution_handoff` 事件，只有已完成回合才推进下一轮的同步边界。
- 旧引擎会话首次升级时补充以前未收到的其他引擎记录，避免再次注入其自身已缓存的回合。
- Codex 根据真实 `thread/resume` 结果选择增量或完整近期历史；OpenCode 根据官方会话是否已有消息选择。新建内部会话会恢复近期历史，不依赖旧缓存的存在。
- 同一个 Echo 回合内的续跑通过宿主 Session 去重。当前用户消息、当前草稿和日志中后续回合不进入历史包。
- 使用现有历史适配器排除推理内容和失败的中间草稿。保留用户诉求、已有回答、错误状态以及有限的工具结果和文件路径；历史工具调用不会被作为可执行协议重放。
- 历史作为有边界的 JSON 数据附在当前请求之前，不进入角色系统指令。旧记录不能授予权限，角色和工具目录仍根据当前请求构建。
- 原生 `_build_intent` 使用服务端日志覆盖浏览器自带的历史，包括服务端空历史，避免客户端伪造历史优先于真实会话。
- 不新建记忆库，不改写长期记忆。

## 验证

相关测试共 93 项通过：

```text
tests/test_engine_history.py
tests/test_opencode_backend.py
tests/test_drive_codex_app_server.py
tests/test_codex_execution_backend.py
tests/test_realtime_context_memory.py
tests/test_host_mcp.py
```

覆盖双向历史投影、同引擎去重、旧会话升级、首次内部会话恢复、真实 Codex / OpenCode 请求载荷选择、失败不推进同步边界、当前消息去重、跨线程/账号/租户拒绝、推理与失败草稿排除、超长历史预算，以及原生历史来源优先级。

另外，`tests/test_execution_engines.py` 与 `tests/realtime_cerebrum/test_fast_path.py` 共 39 项通过；本轮以上不同测试文件累计 132 项通过。修改的 Python 文件 Ruff 检查通过。

真实页面使用已有验收线程 `traU9ieqUt5JIqiAzzgkhl`：先切到 Codex，在新消息中写入只供本对话使用的验收代号；再切回 OpenCode / Zen `big-pickle`，要求仅根据聊天历史回答该代号、已有文件标记与文件名。OpenCode 正确回答，未调用工具，也未写入长期记忆。

OpenCode 接收其他引擎回合消息的成功回合为 `trn_f7cc0e858145489f`；随后的同引擎续聊回合为 `trn_1659a02f64d54142`，均正常完成、工具调用数为 0。已只读核对官方 OpenCode 数据库：前一个输入确实包含 Echo 补充的缺失历史，后一个输入只有最新用户请求，没有重复历史包装；两次回答均包含正确验收代号。证据位于 `.codex-run/host-tool-acceptance/history-evidence.json`。后端 `/api/health` 与前端页面均返回 HTTP 200。

Codex 真实执行在模型启动前被 `Codex account credentials are unavailable` 阻断，失败回合为 `trn_fa76da22fc9341ff`。因此不能把本次结果称为三个引擎的完整真实模型互切验收。Codex 的新建/恢复请求注入已通过模拟协议测试；还需要当前 Echo 账号重新连接 Codex 后补验真实模型。测试后已恢复此前的 Codex 系统模型来源设置，页面回到可用的 OpenCode / `big-pickle`。

## 边界

外部引擎每次补充最多近期 24 轮、约 48,000 字符；单条内容及工具输出也设有上限，省略的轮数和截断会被标注。更早内容仍在 Echo 日志中，但不会一次全量塞入模型。本次未重传历史图片/音频附件，未新增长对话的自动摘要或检索流程。引擎缓存被显式清除且新建会话时可以恢复近期历史；已有损坏会话仍沿用原来的错误处理，不静默删库或换会话。
