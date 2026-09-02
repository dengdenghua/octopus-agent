---
name: codexplusplus-relay-version-race
description: Codex 接 packyapi 中转;"codex 连不上"根因=自动更新重置 ~/.codex/config.toml 抹掉 model_provider(非网络/VPN),从 config.toml.bak.* 恢复三样即可
metadata: 
  node_type: memory
  type: project
  originSessionId: cbd4b1f5-c76b-4703-b9b6-7cf62f3bc177
---

用户在 macOS 上用 **BigPizzaV3 版 Codex++**(`/Applications/Codex++.app` 静默启动器 + `Codex++ 管理工具.app` Tauri 控制台,bundle id `com.bigpizzav3.codexplusplus[.manager]`)给 OpenAI 官方 **Codex 桌面 App** 接 **packyapi.com 中转 API**。设置/日志/锁都在 `~/.codex-session-delete/`(`settings.json` 里 relayProfiles 含明文 OPENAI_API_KEY;`codex-plus.log` 是注入日志)。中转 API key 也明文存在那。

**"代理不了中转 API" 的根因(2026-06-21 实测):** Codex++ 靠 CDP 注入打补丁 `model_app_server_request_patch` 把模型请求改道到中转,该补丁要找 Codex 内部模块 `app-server-manager-signals-`。Codex 经 **Sparkle 自动更新**(`defaults read com.openai.codex` → `SUAutomaticallyUpdate=1`)升到 **26.616.51431**,该模块被改名,补丁报 `未找到 Codex App asset: app-server-manager-signals-` 而失败 → 请求不走中转。最新 Codex++ **1.2.18**(当日最新)只适配到 **Codex 26.611**,1.2.4 和 1.2.18 同样失败。其它补丁(插件市场桥接等)成功,只这个核心改道补丁挂。

**结论:** 重装/升 Codex++ 解决不了,是版本竞速。出路:关 Codex 自动更新防止继续漂移 + 等 Codex++ 适配 26.616(作者几乎日更);或降级 Codex 到 26.611(本机无旧安装包);或绕过 GUI 用 `codex` CLI 原生 config.toml 接 packyapi。

**注入机制要点(踩坑记录):** 这俩 app 是"自改写 wrapper"(首次运行把真 Mach-O 改名 + 写壳脚本规避 Gatekeeper),命令行反复 `kill`/直接跑二进制会在自改写中途打断、损坏真二进制——`open` 启动后别 kill。注入只在 Codex 由 Codex++ 亲自带 `--remote-debugging-port=9229` 拉起时才生效。排查进程别用 `pgrep -f "a\|b"`(macOS ERE 下 `\|` 不是"或");用 `ps -ax|grep -iE`。

**2026-07-14 更新——已改用原生 config.toml 接法(不再靠 Codex++ CDP 注入):** 现在 packyapi 走 `~/.codex/config.toml` 原生 `model_provider`。可用配置就 3 样(顶层 `model_provider = "custom"` + `disable_response_storage = true` + `[model_providers.custom]` 段:`wire_api="responses"` / `requires_openai_auth=true` / `base_url="https://www.packyapi.com/v1"`)。**认证是复用 ChatGPT 登录 token**(`~/.codex/auth.json` 里 `tokens`,`requires_openai_auth=true`;`OPENAI_API_KEY` 是空的)——**不是 API key**,恢复配置不涉密。**复发套路:Codex Sparkle 自动更新(现 26.707,`BROWSER_USE_CODEX_APP_VERSION`)会重写 config.toml、抹掉上述三样 → Codex 改直连 OpenAI 默认端点 → ChatGPT-token 那条路不通 → 表象是"网络连不上"。** 修法=从 `~/.codex/config.toml.bak.<ts>`(Codex 自留)或 `~/.codex/backups_state/provider-sync/*/config.toml` 把三样恢复回去,重启 Codex 桌面 app 即好;保留当前 `model`(如 gpt-5.6-sol),中转报模型错再退 gpt-5.5。**关键澄清:这不是网络/VPN 问题**——实测 api.openai.com 与 www.packyapi.com **直连+经 7890 都返回 401**(=可达,服务器正常应答);FlClash(7890)是 TUN 全局,VPN 一直正常。桌面 app 从 Finder 启动不继承 shell 的 `HTTP_PROXY`,走系统代理(常为 Enabled:No),但既然直连都可达,代理与否都不影响。别再往代理方向查。
