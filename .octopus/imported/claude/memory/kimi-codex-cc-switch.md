---
name: kimi-codex-cc-switch
description: Codex CLI 通过 cc-switch 本地代理使用 Kimi For Coding(K2.7)的配置与坑
metadata: 
  node_type: memory
  type: user
  originSessionId: 63795553-be1e-44e5-bab2-5394aa9c4e9c
---

用户的 Codex CLI(桌面 App 内置,~/.local/bin/codex → Codex.app)用 **Kimi For Coding** 订阅的 key 驱动,2026-07-03 配置完成。

关键事实:
- Kimi coding 端点 `https://api.kimi.com/coding/v1` 只支持 **chat completions**(+ Anthropic 协议给 Claude Code),模型 ID 固定 `kimi-for-coding`(显示名 K2.7 Code,262K 上下文,强制 thinking)。
- 新版 Codex(≥0.99,2026-02 起)**只支持 Responses API**,`wire_api = "chat"` 是硬错误 → 必须走转换代理。
- 方案:**cc-switch(CC Switch.app)本地代理** 127.0.0.1:15721 做 responses→chat 转换(3.16.0 修复了 #2806 messages:null bug)。主界面顶部天线图标 toggle = 「路由 Codex 请求」开关;开启后 cc-switch 自动改写 `~/.codex/config.toml`(base_url→localhost:15721/v1)和 auth.json(填 PROXY_MANAGED,真实 key 由代理注入)。
- Kimi 的 key 存在 cc-switch 数据库 `~/.cc-switch/cc-switch.db` providers 表(kimi provider,meta.apiFormat=openai_chat)。

坑:
- **托管配置会被还原**:在 cc-switch 里点击/编辑/重新应用 provider 会把 config.toml 和 auth.json 还原成直连(真实 key 回写),但代理和 DB 标志位还显示开着 → codex 全 404。修复:把「路由 Codex」toggle 关一下再开(重写托管配置),然后重启 Codex 桌面端。3.16.5 可能已改进。
- **桌面端只在启动时读 config.toml**:改完配置必须重启 Codex.app;AppleScript quit 可能被拒,用 `kill -TERM <pid>` 优雅退出再 open。桌面端模型选择器改模型会把 model 写回 config.toml(用户曾选出错误的 "K2.7 code")。
- **cc-switch 必须常驻**(托盘),退出则 codex 断连;且 launchOnStartup=false,重启电脑后要手动开 CC Switch。
- 用户从 **DMG 挂载卷**运行 cc-switch(/Volumes/CC Switch/),非 /Applications。
- computer-use 对 cc-switch 窗口点击会误报"程序坞",改用 osascript System Events AXPress 可行(checkbox 1 of group 1 of group 1 of UI element 1 of scroll area 1 of group 1 of group 1 of window 1)。
