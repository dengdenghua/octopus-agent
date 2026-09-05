# Twitch 接入指南

## 概述

Twitch 通道复用 IRC 长连接内核，让 Octopus-Agent 进入一个或多个直播聊天室，并将聊天室绑定到单个 Agent 或持久 AI 团队。

## 配置

在「渠道」页面选择 Twitch，填写：

| 字段 | 说明 | 示例 |
|---|---|---|
| OAuth Token | 聊天机器人 OAuth Token，可带或不带 `oauth:` 前缀 | `oauth:...` |
| Bot Username | Token 对应的 Twitch 用户名 | `octopusbot` |
| Twitch Channels | 逗号分隔的主播频道名 | `creator_one, creator_two` |

连接固定使用 Twitch IRC 的 TLS 入口，并请求 tags、commands 和 membership 能力。频道名会自动规范为小写并补上 `#` 前缀。

## 运行保障

- 保存配置后立即连接，失败时保留原有工作连接和原凭据。
- 服务启动自动恢复；掉线后自动退避重连。
- Twitch 消息 ID 进入统一跨 Worker 幂等链路，避免一次平台重送触发多次团队执行。
- 模型执行与网络读取隔离，长任务不会阻塞 `PING/PONG`。
- 输出按 IRC 协议上限安全分片。

目前支持纯文本聊天室消息。健康检查反映真实长连接状态，而不是仅表示“凭据已保存”。
