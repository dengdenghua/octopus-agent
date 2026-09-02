---
name: octopus-local-cli-partners
description: 本地 CLI 伙伴(Claude Code/Codex)接入要点——探测/注册/stdin/代理三处坑
metadata: 
  node_type: memory
  type: project
  originSessionId: 51b00ad7-1a6e-4c0f-b303-d51e6e24949a
---

octopus-agent 把本机安装的 coding-agent CLI 注册为可被团队指派的"本地伙伴"。链路与三个踩过的坑：

**探测→注册→显示三段**：
- 探测:`runtime/execution/agents/cli_team.py:detect_installed_partners()`(`shutil.which`,实时,认后端进程 PATH)+ 规格表 `runtime/sensing/gateway/agents_local_partner.py:LOCAL_PARTNER_SPECS`(claude-code/codex-cli/openclaw)。`/api/cli-team/status` 暴露探测结果。
- 注册:`POST /api/agents/local-partners/register`,body `{"partners":[{"id":"claude-code","alias":"..."}]}`,写 `agents/local_<id>/profile.jsonc`(`runtime:"local_partner"`)+SOUL/IDENTITY。dev 模式(require_auth=False)免鉴权直接 curl 即可。PATH-poisoning 守卫只拒 cwd 子树、**放行 home**(~/.local/... 合法)。
- 显示:`frontend/src/core/agents/local-cli.ts:useLocalCliAgents()` 把探测结果合成 `Agent`(name=`local_*`)。**注册后**也会经 `useAgents()` 回来(磁盘 profile)→ 必须 `dedupeAgentsByName` 去重。sidebar 切换面板(`sidebar-footer.tsx`)我已改成合并探测+按「人设/本地 CLI 伙伴」分两组(commit `76f3cec0`);create-team/invite 对话框早就合并了探测结果。判据 `name.startsWith("local_")||capabilities.local_partner`。

**坑1 stdin(产品级,已修)**：bridge `local_partner_bridge.py:_default_runner` 的 `subprocess.run` 原来没设 stdin,子进程继承非 tty 管道,`claude -p` 等 3 秒("no stdin data received in 3s")并把 ANSI `[33m...` 泄进输出。修复=加 `stdin=subprocess.DEVNULL`(headless 伙伴 prompt 永远走 argv,不用 stdin)。已在 HEAD。

**坑2 代理(环境级,机器特有)**：claude→api.anthropic.com 在中国被墙,无代理直接 `403 Request not allowed`;codex 走 packyapi(国内可达)**不需要**代理。后端进程默认无 `HTTPS_PROXY`→它 spawn 的 claude 子进程 403。解法:`.claude/launch.json` 后端启动命令 `export HTTPS_PROXY=http://127.0.0.1:10808 NO_PROXY=...,packyapi.com,molili.8kbl.com,...`——claude 走代理、后端自身+codex 的国内流量经 NO_PROXY 直连。改后必须 preview_stop+start 后端才生效(env 在进程启动时快照)。`.claude/` 被 gitignore,这是本机配置不进仓。

**坑3 CLI 登录**：`claude` 命令行版独立于桌面 App 鉴权,要在真 Terminal `/login`(走代理才连得上官方),用订阅会员账号即可。本机 `~/.zshrc` 已加 `claude(){ HTTPS_PROXY=...:10808 command claude "$@"; }` 只给交互式 claude 挂代理。

相关:[[octopus-agent-generated-artifact-drift]] i18n 5 文件+并发提交、[[octopus-tentacle-mobile-bridge]] 另一类本机桥、[[octopus-agent-automation-stacks]] 强原语弱编排。
