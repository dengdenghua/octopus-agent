# Octopus-Agent

Octopus-Agent 是一个自托管的 agent runtime，用来规划、执行、观察和改进任务。

English readers: [README.en.md](README.en.md)

先看这几份：

1. [10-minute golden path](docs/GOLDEN_PATH.md)
2. [Quickstart](QUICKSTART.md)
3. [Concepts](docs/CONCEPTS.md)
4. [Architecture](docs/guide/architecture.md)
5. [Main Path Audit](docs/archive/main-path-audit.md)
6. [Self-Evolution Minimum Loop](docs/archive/react-self-evolution.md)

当前结构：

| 路径 | 作用 |
|---|---|
| `runtime/` | 核心运行时：规划、执行、记忆、安全、UI API |
| `frontend/` | 工作区 UI 和桌面壳 |
| `tests/` | 回归、单元和集成测试 |
| `agents/` | agent 定义、preset 和元数据 |
| `skills/` | 可调用技能和技能元数据 |
| `protocols/` | 协议资产 |
| `prompts/` | prompt 模板和变体资产 |
| `extensions/` | 随运行时一起发布的扩展 |
| `tools/` | 开发工具 |
| `scripts/` | 项目自动化脚本 |
| `docs/` | 架构、入门、审计和参考文档 |

如果你想看历史资料，请从 [docs/archive/README.md](docs/archive/README.md) 进。
