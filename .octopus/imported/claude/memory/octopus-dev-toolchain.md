---
name: octopus-dev-toolchain
description: 本机无系统级 Node/Python3.11，octopus 项目使用本地独立工具链的位置和用法
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d1cc717-ed67-45d7-830e-793579e5a9f3
---

这台 Mac 没有系统级 node/npm/brew，系统 Python 只有 3.9（项目要求 3.11）。2026-06-11 搭建了本地工具链：

- Node 22.12.0: `~/.local/octopus-tools/node-v22.12.0-darwin-arm64/bin`（用前 export PATH）
- uv: `~/.local/octopus-tools/uv/uv`
- 后端 venv: `backend/.venv`（Python 3.11，跑测试用 `.venv/bin/python -m pytest tests/ -q`）
- 前端构建: `npm run build`（tsc + vite），测试 `npx vitest run`

种子账号: admin/admin123（租户 demo 和 default，demo 租户有示例项目）。
注意 zsh 中 `${var//(1)/}` 会把括号当 glob 分组——批量重命名用 sed。
