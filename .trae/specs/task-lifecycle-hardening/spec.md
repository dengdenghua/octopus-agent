# 长任务与编程任务生命周期加固 Spec

## 目标

让客户端断线、服务重启、子进程超时和调度重入等异常都收敛到可观察的终态，避免后台继续产生不可控副作用或任务永久显示为运行中。

## 本阶段范围

1. OpenAI SSE 生成器关闭时，取消实际运行线程中的 ambient cancellation token，并有界等待清理。
2. cron shell / prompt runner 使用独立进程组，超时清理整个进程树；cron tick 使用跨进程锁避免重复执行。
3. BackgroundRunner 的 cron 任务禁止同一任务重叠执行；普通 periodic 任务保持原有并发语义。
4. TeamTask 路由启动时把无法由当前进程接管的持久化 `running` 任务标记为 `failed`，记录可诊断原因，避免永久假运行。

## 不在本阶段

- Python thread 的强制终止（不可安全实现）；需要 process isolation 才能做到硬取消。
- TeamTask 从 checkpoint 自动恢复（需要 runner checkpoint 协议和幂等写入契约）。
- 日志文件完整轮转和 ParallelAgentOrchestrator 的持久化（下一阶段）。

## 验收

- SSE generator `close()` 后 worker 能观察到取消，且不会继续进入新的工具步骤。
- cron timeout 后 descendants 被终止；两个并发 tick 至多一个实际执行。
- cron callback 执行超过调度间隔时，同一任务 `in_flight` 不增长到 2。
- 新建 router 读取旧状态后不再返回 `running` 的孤儿任务。
