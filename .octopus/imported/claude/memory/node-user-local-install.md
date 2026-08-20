---
name: node-user-local-install
description: Node.js 装在 ~/.local/node（用户级安装），非交互 shell 需手动加 PATH
metadata: 
  node_type: memory
  type: project
  originSessionId: 7da12040-c4fa-41f4-a971-66846e188e43
---

这台 Mac（arm64，无 Homebrew/MacPorts）的 Node.js 是 2026-06-11 装的用户级安装：v24.16.0 LTS 解压在 `~/.local/node`，PATH 已加入 `~/.zshrc`。

**Why:** 机器上原本没有任何 Node 运行时（frontend/node_modules 是现成的），也没有包管理器；用户确认可以安装。

**How to apply:** 在 Bash 工具（非交互 shell）里跑 npm/npx/vitest/tsc 前先 `export PATH="$HOME/.local/node/bin:$PATH"`，否则 npm 会因 `#!/usr/bin/env node` 找不到 node 而报错。
