---
name: freebuff-local-agent
description: 使用官方 Freebuff CLI 在用户明确要求时启动本地交互式编程 Agent。适用于安装、登录、启动或继续 Freebuff 会话；不适用于把 Freebuff 当成 OpenAI 兼容模型 API。
version: "1.0.0"
author: "Octopus"
---

# Freebuff 本地 Agent

仅在用户明确要求使用 Freebuff 时使用本技能。

## 能力边界

- 使用官方 `freebuff` npm 包和官方网页登录。
- Freebuff 免费 CLI 是交互式终端应用；当前官方命令不支持把任务 prompt 作为命令行参数传入。
- 不调用未公开接口，不伪造官方客户端元数据，不绕过免费层、CLI Gate 或其他访问控制。
- 不读取、复制或回显 `~/.config/manicode/credentials.json` 中的凭据。
- Freebuff 会处理用户交给它的消息、代码及工作区文件。启动前应确保用户已理解该数据会发送给 Freebuff 服务。

## 使用方式

1. 通过插件市场安装本插件。安装阶段才检测本机是否已有 `freebuff`，缺失时执行官方安装命令。
2. 通过插件的“执行 CLI 登录”打开 `freebuff.com` 官方授权页。
3. 在可见、可交互的终端中，从目标工作区启动：

```bash
freebuff --cwd /absolute/path/to/workspace
```

继续最近会话：

```bash
freebuff --continue --cwd /absolute/path/to/workspace
```

## 禁止的降级方案

不要把 Freebuff 注册为 OpenAI 兼容 Provider，也不要用第三方逆向代理取得免费模型。若用户要求 Echo 自动委派任务，应明确说明：需要 Freebuff 官方提供非交互调用或允许其 SDK 复用 Freebuff 登录会话后才能可靠接入。
