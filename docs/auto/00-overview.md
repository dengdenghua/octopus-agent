---
type: "Overview"
title: "项目概述 · Project Overview"
description: "自动从仓库结构提取。Octopus · The Open-Source Multi-Agent AI Workspace."
tags: []
tier: "core"
---
# 项目概述 · Project Overview

> 自动从仓库结构提取。Octopus · The Open-Source Multi-Agent AI Workspace.

> v0.2.0 Beta · Apache-2.0

## 仓库结构

| Directory | Purpose |
| --- | --- |
| `runtime/` | Python runtime (agents / planner / executor / safety / memory) |
| `frontend/` | React + Vite SPA for the webui |
| `agents/` | Per-agent profile + memory + workspace directories |
| `docs/` | Human-written architecture docs, ADRs, invariants |
| `docs/auto/` | ← you are here · auto-generated |
| `tests/` | Pytest suite (backend) |
| `scripts/` | Tooling (this generator + OpenAPI snapshot) |
| `protocols/` | 8 protocol specs (digestion / immunity / swarm / …) |

## 规模

- Python 模块：**1284** 个（runtime/）
- TSX 组件：**537** 个（frontend/src）
- 后端测试：**836** 个

