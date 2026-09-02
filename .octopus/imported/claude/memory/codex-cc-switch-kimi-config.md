---
name: codex-cc-switch-kimi-config
description: Codex 路由配置(官方/CC Switch/第三方)的位置、坑与 2026-07 的 packyapi 事件
metadata: 
  node_type: memory
  type: reference
  originSessionId: 2fa15870-2a4b-45f0-aa53-89f60b55c2ee
---

**当前状态(2026-07-17)**:Codex 已随 ChatGPT 桌面版走(`/Applications/ChatGPT.app/Contents/Resources/codex`,codex-cli 0.144.2),官方 chatgpt 登录,**Team 版**(dengdenghua@dangbei.com,org "Personal",订阅至 2026-07-26)。config.toml 无 `model_provider`(默认官方),model `gpt-5.6-sol`(官方真模型,窗口 258400)。kimi 供应商已被删除;CC Switch 剩 codex-official(current)+ DeepSeek(**key 仍是占位符 YOUR_DEEPSEEK_API_KEY,待用户注册充值后填**,1M 窗口/900K 压缩阈值/meta apiFormat=openai_chat)。

**⚠️ CC Switch 存的是整份 config.toml 快照(每个供应商一份)**,切换即整体覆写——所以 config.toml 里的手改会被切换抹掉,且**模板会随 App 升级而过期**。2026-07-17 已把 official+DeepSeek 两个模板都从当前基线刷新(旧模板还指向已不存在的 `/Applications/Codex.app`,切一次就写坏桌面 App 的 node_repl/plugins)。App 升级或路径变化后要重刷模板。db 备份:`~/.cc-switch/backups/cc-switch.db.claude-2026070{4,17}`。

**packyapi 事件(2026-07-16)**:config.toml 被外部(非 CC Switch)写成 `base_url = https://www.packyapi.com/v1` + `requires_openai_auth = true` → Codex 把 ChatGPT OAuth 令牌发给第三方中转站 → 401「无效的令牌」(登录动作把中转站的 key 冲成 null)。已删除该段,备份 `~/.codex/config.toml.bak-packyapi-20260716`。**令牌已泄露给 packyapi,已建议用户登出所有设备**。若 packyapi 再次出现 = 有脚本在改 config.toml,需揪源头。

**授权边界**:ChatGPT 订阅令牌只授权官方 Codex 工具(CLI/IDE 扩展/Cloud)使用,喂给第三方软件违反 ToS(Team 版爆炸半径=整个组织;`originator` 字段会随请求上报,官方可识别)。**"登录送 $5/$50 API credits" 对本账号无效**——Team/Enterprise/Edu 被排除,且该促销 2025-06-15 就截止了(我曾据二手博客误告知用户,已更正)。给第三方软件供能只能买 API key。Codex 二进制里的 `rate-limit-reset-credits`/`CreditsSnapshot` 是限流重置额度,与 API credits 无关。

**排障入口**:CC Switch 数据 `~/.cc-switch/`(cc-switch.db 的 providers.settings_config = {auth, config};proxy_request_logs 表可查每请求 token/状态码/上游报错,created_at 是秒级);Codex 会话 `~/.codex/sessions/`(jsonl 的 token_count 事件含 model_context_window 与真实用量,head -1 可看 originator/model_provider——可据此判断某会话走的哪条链路、是否吃到新配置)。**桌面 App 把配置缓存在进程里,改配置后必须 ⌘Q 完全退出重启**。
