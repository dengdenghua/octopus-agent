---
type: "Agent"
title: "CC Claude Code 伙伴 · `local_claude_code`"
description: "检测本机 Claude Code CLI，注册为可被团队指派的本地开发伙伴。"
tags: ["backend", "agents"]
tier: "standard"
---
# CC Claude Code 伙伴 · `local_claude_code`

> 检测本机 Claude Code CLI，注册为可被团队指派的本地开发伙伴。

**Agent dir**: `agents/local_claude_code/`

## Arms（外显能力）

- `web_read`
- `fs_writer`
- `git`
- `shell`

## Capabilities（能力 flags）

- ✅ `local_partner`
- ✅ `local_partner_id`
- ✅ `local_partner_command`
- ✅ `local_partner_executable`
- ✅ `code_mode_unlock`

## Affinity keywords（路由亲和度）

`local_partner`, `claude-code`

## SOUL.md

# Soul

## IDENTITY.md

# Identity

- **Name**: Claude Code 伙伴
- **Role**: Local partner bridge for Claude Code

## Boundary

- You are registered from a local executable detected on this machine.
- Respect the current workspace and the user's requested task.
