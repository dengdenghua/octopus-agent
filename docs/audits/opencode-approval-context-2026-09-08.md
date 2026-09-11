# OpenCode 审批上下文错误：新旧后端模块混用

2026-09-08 21:43，任务 `tcrw3P5HRdDAXtWW7Aoi5P` 在发送“你好”后报错：
`'ExecutionTask' object has no attribute 'approval_provider'`。

## 根因证据

- 后端 PID 32156 于 19:05:12 启动，一直运行到故障发生。
- `runtime/execution/request.py` 最后修改于 20:15:14，当前 `ExecutionTask` 已包含 `approval_provider` 等执行上下文字段。
- `runtime/execution/opencode_roles.py` 最后修改于 20:56:27；`realtime_opencode_backend.py` 最后修改于 21:05:23。
- 21:43:33 的异常发生在 `drive_opencode` 读取 `request.task.approval_provider` 时，尚未提交模型请求。

进程启动后源文件继续更新，早先已加载的任务类型和随后加载的新引擎模块来自不同版本。新进程下的当前源码契约检查通过。

## 处理与验证

完整停止并重启经过进程路径和命令行核实的 Echo 后端。新进程 PID 34540 于 21:46:43 启动，后端 8310 健康检查及前端 3310 均返回 HTTP 200。

扩充 `tests/test_opencode_roles.py` 的实时适配器回归，覆盖审批器继承、相同实例、显式替换，以及成功、错误、取消三种结果；确认原始任务不被修改、权限和资源对象得到保留。执行上下文、OpenCode 角色和实时执行三组共 59 项测试通过，Ruff 检查通过。

恢复原本地账号后，在原对话重试“你好”。21:48:21 开始的新回合 `trn_127989fe4ee74906` 经 OpenCode + big-pickle 正常完成，页面显示：

> 你好！我是 Eve，有什么可以帮你的？

原有项目分析和对话历史保留。此轮修复了正在运行的后端版本不一致问题，并未变更模型选择或审批权限。后续更新 Python 执行模块时，也需要完整重载后端后再验收。
