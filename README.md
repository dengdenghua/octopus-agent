# Octopus-Agent

> v0.2.0 Beta · Apache-2.0

Octopus-Agent 是一个自托管的 **Agent OS** —— 以 `runtime/` 里的 Python 运行时为核心，跑通「规划 → 执行 → 观察 → 记忆 → 改进」的完整闭环：支持工具调用、记忆反思、安全治理、浏览器/桌面控制与自改进循环。

IDE、浏览器、桌面应用与扩展只是产品表层；核心产品是 `runtime/`。

English readers: [README.en.md](README.en.md)

## 快速开始

```bash
# 最小确定性后端演示，无需 LLM key
pip install -e ".[minimal]"
python -m runtime bugfix-demo

# 开发环境（测试、FastAPI UI、web skills）
pip install -e ".[dev,serve,web]"
python -m runtime quickstart --non-interactive
python -m runtime status
python -m runtime ui --port 8000
```

打开 <http://127.0.0.1:8000>。

前端开发：

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

## 核心文档

先看这几份：

1. [10-minute golden path](docs/GOLDEN_PATH.md)
2. [Quickstart](QUICKSTART.md)
3. [Concepts](docs/CONCEPTS.md)
4. [Architecture](docs/guide/architecture.md)
5. [Main Path Audit](docs/archive/main-path-audit.md)
6. [Self-Evolution Minimum Loop](docs/archive/react-self-evolution.md)

## 当前结构

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

历史资料请从 [docs/archive/README.md](docs/archive/README.md) 进入。

## License

Apache-2.0，见 [LICENSE](LICENSE)。
