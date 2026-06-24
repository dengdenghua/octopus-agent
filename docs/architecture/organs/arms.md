# 🦑 Arms · 腕足

**生物原型**：章鱼有 8 条腕足，每条半自主，能独立尝味、抓握、探索。

## 8 条专长腕

| Arm | 专长 | 典型 Suckers |
|---|---|---|
| code_arm | 代码改写 / git / 跑测试 | edit, git, pytest |
| data_arm | 数据处理 / SQL / 可视化 | sql, pandas, plot |
| search_arm | 联网搜索 / RAG | web_search, rag |
| browse_arm | 浏览器自动化 | chromium, dom |
| file_arm | 文件系统 I/O | fs, glob, grep |
| comm_arm | Slack / 邮件 / IM | slack, email |
| deploy_arm | 打包 / Docker / K8s / CI | docker, kubectl |
| observe_arm | 指标 / 日志 / trace | prometheus, loki |

## 为什么正好 8 条
不是硬性限制，而是：① 生物学对齐 ② 8 类职责覆盖常见软件工程任务 ③ 上下文隔离更干净。

## 平权原则
Arm 之间没有 master/slave。通过 `chromatophores/` 互相广播状态。

## 接口
```python
class Arm:
    name: str
    sucker_affinity: list[str]
    model: str                      # 可与其他 Arm 不同
    def handle(self, task: ArmTask, ganglion: Ganglion) -> ArmResult: ...
```
