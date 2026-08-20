---
name: octopus-codex-plugin-compat
description: 从 Codex 拷来的插件如何接进 octopus；skills 已接通(266,search-only 动态注入非常驻)、MCP 故意不自动接、apps/commands 不可移植
metadata: 
  node_type: memory
  type: project
  originSessionId: ff25d56e-cd25-4c88-9ed5-a162bd9c628b
---

用户把 ~50 个 Codex 插件拷进 `.octopus/plugins/codex/<plugin>/`(每个有 `.codex-plugin/plugin.json` + 多为 `skills/<skill>/SKILL.md` + 脚本 + `agents/openai.yaml`)。问"能用还是空架子"——拷贝前**基本是空架子**(被 catalog 显示/可搜索,但没接进执行)。

**两套插件系统(别混)**:
- **codex_discovery**(`runtime/platform/plugins/codex_discovery.py`):扫 `.octopus/plugins/codex/*/.codex-plugin/plugin.json`,只做 catalog + smoke + UI 显示。
- **原生 PluginHub**(`plugin_hub.py`):扫 `~/.octopus/plugins/*/plugin.yaml`,加载 Python `ModulePlugin`、`load/start` 注册技能/路由。**它看不到 codex 插件**(目录/格式都不对),所以 `@plugin:X` 激活不了 codex 插件。
- capability_skills 里扫到的 codex 技能曾标 `registered:False`、`use_capability` 只跑已注册 action → 不可调用。

**已接通 skills(2026-06-28,工作树;266 个技能转可调用)**:关键复用点——`runtime/execution/suckers/market_skills.py:register_market_skills(all_skills_dir=...)` 是 octopus **通用的 SKILL.md→可调用 Skill 加载器**(扫 `<dir>/*/SKILL.md`,handler=`_make_prompt_handler` 返回 instructions+bundled scripts+cwd,agent 再用受闸的 exec_shell 跑脚本)。`register_all` 本就用它加载 `skills/public`。做法:
1. 给 `register_market_skills` 加 `source` 形参(provenance);
2. 新 `runtime/execution/suckers/codex_plugin_skills.py:register_codex_plugin_skills` —— 对每个 codex 插件的 `skills/` 调上面 loader,tag `codex://plugin/<plugin>`;
3. `all_skills/__init__.py:register_all` 末尾 hook 调用它。
- 安全:技能只返回说明,不自执行;真执行走 exec_shell/ToolExecutor 闸;provenance 给 TrustEngine 判。重名时 octopus 自带技能先注册者赢(codex 同名跳过)。
- **search-only(动态注入,非常驻)**:`react_context.py:_format_skill_catalog` 加了过滤——`trusted_source` 以 `codex://plugin/` 开头的技能**排除出每轮提示词目录**(`_search_only`),但仍在 `registry.all_names()`(search_skills/search_capabilities 找得到)+ 可调用。即 agent 搜到→调用时其 SKILL.md 才懒注入,不占常驻上下文。背景:目录本就 cap=100+渐进披露+goal 排序,不会真"爆表",但 266 个会在 goal 命中时挤占自带技能槽位,故按用户"插件应动态注入非常驻"显式排除。实测 catalog 0 codex、仍可搜可调。
- 测试 `tests/test_codex_plugin_skills.py`(4 绿);回归 618 通过,唯一红 `test_resume::...trajectory` **stash 对照证实是预存/他会话的,非本改动**。

**MCP 故意不自动接(安全)**:5 个声明 MCP 的插件——cloudflare(远程 http/OAuth)、codex-security+openai-developers(本地 `node ./mcp/server.mjs`)、computer-use(Codex 的 .app 二进制,本机没有)、data-analytics(UI widget)。MCP seed 把 server 标 `enabled=True`=**会在启动时自动起这些拷来的外部进程=启动期 RCE**,正好踩本会话刚加固的控制面安全。安全路径=用户在 config.yaml 的 `mcp_servers` 里**显式**逐个加 + 配凭证(octopus 已支持)。**别自动接线**。

**apps(37)/commands(4)**:Codex 自有 UI/二进制格式,octopus 不执行,非重写不可移植。

相关:[[octopus-local-cli-partners]]、[[octopus-agent-integration-debt-audit]]、[[octopus-tentacle-mobile-bridge]]
