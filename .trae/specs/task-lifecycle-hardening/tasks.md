# Tasks

- [x] SSE 断线取消传播与有界清理
- [x] cron 进程组清理与跨进程互斥
- [x] cron 调度防止同一任务重叠
- [x] scheduler stop 使用总超时预算，避免线程池无限等待
- [x] TeamTask 启动时孤儿状态收敛
- [x] call_subagent 超时后 slot 延迟到 worker 真正退出再释放
- [x] worktree / local CLI 统一进程组超时清理
- [x] 并行代理默认模式切换到 process isolation（不可序列化 runner 自动兼容降级并可观测）
- [x] LoopController 长 attempt 独立 heartbeat
- [x] background_exec 启动回收/接管策略
- [x] ParallelAgentOrchestrator checkpoint / event log 上限
