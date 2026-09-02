---
name: octopus-tool-migration
description: 一键迁移其他 AI 工具(Codex/Claude/Trae/Qoder)的插件/记忆/MCP 进 octopus；已建只读 dry-run 规划器(Codex+Claude 两家)
metadata: 
  node_type: memory
  type: project
  originSessionId: ff25d56e-cd25-4c88-9ed5-a162bd9c628b
---

**目标**:用户切到 octopus 时一键迁移 Codex/Claude/Trae/Qoder 的插件、记忆、MCP 等。可行性高,因为这些工具在收敛到同一套格式(SKILL.md / AGENTS.md·CLAUDE.md / MCP),而 octopus 的目标端基本都有(SkillRegistry 的 SKILL.md loader[见 [[octopus-codex-plugin-compat]]]、memory、mcp 配置、agent 档案)。

**已建(2026-06-28,只读 dry-run 规划器,纯 stdlib,无副作用)**:`runtime/platform/migration/{base,codex_adapter,claude_adapter,service}.py` + `tests/test_migration.py`(4 绿)。`build_migration_plans(sources, home=)` → 每家一个 `MigrationPlan(items=[MigrationItem(kind,name,source,summary,origin,portable,needs)])`;`render_plan_summary()` 出预览。**只扫不写**;apply(灌进 octopus,带信任闸)是下一步,未建。

**各家真实源位置(逆向出来的,关键资产)**:
- **Codex `~/.codex`**:技能在 `plugins/cache/<市场>/<插件>/<版本>/skills/*/SKILL.md`——**有版本目录**,所以 adapter 锚定 `.codex-plugin/plugin.json` 再找同级 `skills/`(别用固定深度 glob);记忆 `AGENTS.md`(常为空)+ `rules/*.rules`;MCP 在 `config.toml [mcp_servers.*]`(tomllib 解析);`auth.json`=凭证别碰。
- **Claude `~/.claude`**:技能 `plugins/marketplaces/*/(plugins|external_plugins)/*/skills/*/SKILL.md`;agents/commands 同插件下 `*.md`;记忆 `projects/<proj>/memory/*.md`(frontmatter name/description/metadata.type——**和 octopus 自己的记忆格式一样**,1:1 可映);MCP 在 `~/.claude.json` 的 `mcpServers`(顶层 + `projects.*.mcpServers`)。
- **Qoder `~/.qoder`**:`memories/<id>/`、`canvas/recipes/*.recipe.md`、`plugins/`、`extensions/`(VSCode 扩展,与 octopus 运行时无关)。Trae **本机没装**。

**本机实测 dry-run**:`[codex] 10`(skill×8 + rule×1 + mcp×1,node_repl 标 creds/node)、`[claude] 126`(agent×23/command×29/memory×45/skill×29)。注:claude 的 45 memory 里**含我自己给各 octopus 仓写的记忆文件**;claude mcp=0(用户没在 Claude 配 MCP)。

**硬坎(apply 时必须守)**:MCP 只能**导入为禁用+待补凭证**,绝不自动起(=启动期 RCE,见 [[octopus-agent-integration-debt-audit]] 的 computer-loop 教训);凭证(auth.json 等)绝不迁;记忆语义要逐家归一(frontmatter vs 自由文本 vs id 条目);工具专属面(Codex apps/commands、Claude hooks、Qoder canvas、VSCode 扩展)部分/不可移植。

**apply 已建(2026-06-28,staging-first)**:`runtime/platform/migration/apply.py:apply_plan(plan, project_root, kinds=, dry_run=)` 把计划落到 `<root>/.octopus/imported/<source>/`:技能 bundle 整目录拷到 `skills/<name>/`、记忆/规则/agent/命令拷到 `<kind>/`、MCP 写 `mcp.disabled.json`(enabled:false,绝不自启,不带凭证)。幂等(目标存在即 skip)、dry_run 只数不写。技能落地即**可调用**——`runtime/execution/suckers/imported_skills.py:register_imported_skills` 扫 `.octopus/imported/*/skills` 经 register_market_skills 注册(tag `imported://<source>`),已 hook 进 register_all + 加进 react_context 的 search-only 前缀(同 codex,动态注入非常驻)。tests/test_migration_apply.py(5 绿)。**实测**(扫真机→apply 进 temp):codex 8skill+1rule+1mcp;claude 25skill/21agent/28command/46memory(少量同名 skip);33 个迁移技能注册可调。**记忆/agent/命令是"暂存待审"**,没自动并进 octopus live memory(语义差异,需显式激活);MCP 同理 disabled 暂存。

**A(CLI)+ B(激活)已建(2026-06-28)**:
- **CLI** `octopus migrate [--source codex,claude] [--apply] [--activate] [--kinds ...]`:`runtime/cli_migrate.py:run_migrate` + cli.py 子解析器/dispatch。默认=preview;`--apply`=staging;`--activate` 隐含 apply。**坑**:cli.py 有个 `_CLI_COMMANDS` frozenset(L349)是 argv 预处理白名单,新子命令必须加进去,否则被当 goal 跑(我踩了)。实测 `octopus migrate` 出 codex 10/claude 127。
- **激活** `runtime/platform/migration/activate.py`:**memory**→把 staged 记忆作有界索引行(`- [源] 名: 描述 (full: 路径)`)append 进**项目级** `<root>/.octopus/MEMORY.md`(`scope_paths.project_memory_path`;global 是 `~/.octopus/MEMORY.md`;per-agent 是 `agents/<id>/agent-core/MEMORY.md`,CLI 无 session 故用 project/global),幂等(rel 路径已在文件里就 skip),全文留 staging。**MCP**→写 `config.snippet.yaml`(待补 creds、disabled),**绝不动 config.yaml**(MCPServerConfigEntry 无 enabled 字段,塞进 config.yaml 会自动起=RCE)。test_migration_apply.py/test_migration_activate.py 全绿。

**HTTP API 已建(2026-06-28)**:`runtime/sensing/gateway/migrate_router.py:create_migrate_router`(自闸 `_auth_dep`,镜像 mcp_router):`GET /api/migrate/preview`(只读,出 plans JSON)+ `POST /api/migrate/apply`({sources,kinds,activate} → reports + activation,写到 `Path.cwd()`)。已 include 进 app.py + 加进 `_LEGACY_CONTROL_PLANE_PREFIXES`(双层鉴权)。openapi 快照已重生(含 /api/migrate)。test_migrate_router.py 绿(preview/apply-into-temp/401)。**至此 engine→CLI→API 全通,均鉴权+测试覆盖**。

**前端 UI 已建(2026-06-28)**:Vite SPA + react-router(**不是 Next**,页面 `src/app/workspace/<x>/page.tsx` 靠 `src/router.tsx` 的 lazy+`<Route>` 注册,导航在 `workspace-sidebar.tsx` 的 `NavRoute[]`,`resolveRoutes` 支持裸 `label`)。新增 `frontend/src/app/workspace/migrate/page.tsx`(WorkspaceContainer + 直接 `fetch("/api/migrate/preview"|"/apply")` + preview 卡片/一键迁移按钮/activate 勾选/报告),router.tsx 加 lazy+Route,sidebar 加 nav item。frontend typecheck 绿、eslint 我的文件 0 error(仅 1 个预存 WorkflowIcon unused warning)。**验证坑**:`/workspace/*` 被 ProtectedRoute 挡(preview 里跳登录页=对的);dev backend **不自动 reload**,跑着的旧 server 不含新路由→`/api/migrate` 现场 404,但 test_migrate_router 的 TestClient(create_app) 证明路由在码里=对的,**重启 backend 即生效**。

**MCP OAuth-on-enable 第一步已建(2026-06-28;通用 MCP 能力,非仅迁移)**:之前 octopus MCP 只支持静态 env/headers,没 OAuth——远程 MCP(cloudflare/slack/...)是"点启用→弹官方授权"。现补:
- `runtime/adapters/mcp_client/oauth.py`:PKCE(S256)+ `build_authorize_url` + `exchange_code`/`refresh_access`(urllib POST)+ `MCPOAuthStore`(`~/.octopus/mcp_oauth.json`,chmod 0600,per-server token + 单次性 state pending,TTL 10min)+ `bearer_for_server(name)`(到期前自动 refresh)。
- `runtime/sensing/gateway/mcp_oauth_router.py`:`POST /api/mcp-oauth/authorize`(**鉴权闸**,出 authorize URL)+ `GET /api/mcp-oauth/callback`(**state 闸、非鉴权闸**——provider 重定向不带 operator token)。**关键**:prefix 用 `/api/mcp-oauth`(不在 `/api/mcp/` 下)所以 legacy 中间件不会 401 掉 callback;**没**加进 `_LEGACY_CONTROL_PLANE_PREFIXES`。
- `client.py:_transport()` 远程连接时注入 `Authorization: Bearer bearer_for_server(self.config.name)`(无 token=不注入,行为不变)。
- app.py 已 include;openapi 快照已重生(含 /api/mcp-oauth)。tests test_mcp_oauth.py + test_mcp_oauth_router.py 绿;mcp_client 全套 43 绿(transport 改动无回归)。
- **第二步已建(2026-06-28,自动发现 + DCR)**:`runtime/adapters/mcp_client/oauth_discovery.py`:`discover(server_url)`(RFC9728 `/.well-known/oauth-protected-resource`→auth server→RFC8414 `/.well-known/oauth-authorization-server`(回退 openid-configuration);protected-resource 取不到就拿 origin 当 auth server)+ `register_client`(RFC7591 DCR,public PKCE,`token_endpoint_auth_method=none`)。`MCPOAuthStore` 加 per-issuer `client_id` 缓存(get/save_client,持久化,免重复注册)。router 加 `POST /api/mcp-oauth/start`{server,url}(鉴权闸)→ discover →(必要时 DCR)→ PKCE+state → 返回 authorize URL。**UI 只需给 {server,url}**。tests test_mcp_oauth_discovery.py(发现/origin 回退/DCR/start 缓存)绿;openapi 含 /start。全网络调用走 urllib + best-effort(失败回退 /authorize 手填)。
- **前端授权按钮已建(2026-06-28)**:`frontend/src/app/workspace/migrate/page.tsx` 加「授权 OAuth MCP」区块(服务器名 + URL 输入 + 授权按钮 → `POST /api/mcp-oauth/start` → `window.open(authorize_url)`)。typecheck + eslint 净。redirect_uri 自动=后端 base_url 的 /callback(前端经 Vite 代理打到后端,所以回调落后端=对)。
- **仍剩**:给 `MCPServerConfigEntry` 加 oauth 字段(transport 自动识别 + 在 MCP 项上就地显示「授权」按钮,需 adapter 捕获 server url);浏览器 happy-path 实拍要登录 + 重启后端(被鉴权 + 旧 server 挡,非代码问题)。

**Qoder adapter 已建(2026-06-29,commit `31a23ffc` 在 feat/octopus-mix-virtual-model,本地未 push)**:`runtime/platform/migration/qoder_adapter.py:scan_qoder`。逆向 `~/.qoder` 真实格式后发现**和 Codex/Claude 高度趋同**:skills=`plugins/cache/<mkt>/<plugin>/[<ver>/]skills/*/SKILL.md` 锚 `.qoder-plugin/plugin.json`(几乎照搬 codex_adapter);memory=`memories/<id>/**/*.md`(rglob,cap 200);recipes=`canvas/recipes/*.recipe.md`→`command` kind(canvas 专属,portable=False needs=canvas);**MCP 在 `~/Library/Application Support/Qoder/SharedClientCache/mcp.json`**(标准 mcpServers,**不在 ~/.qoder!** macOS 路径)。加进 `_ADAPTERS`→SUPPORTED=(codex,claude,qoder)。apply/activate **不硬编码 source**(按 kind),qoder 自动走通。实测真机 `~/.qoder`=7 项(skill×1 meoo-cli/memory×2/command×4 recipes);test_migration_qoder.py 4 绿 + migration 套件 15 绿。**环境坑**:migration 代码在 feat 分支不在 main 工作树,**不能切分支**(epitaxy 会 stash 干扰并发)→ 用 `git worktree add <path> feat 分支` 隔离 + `PYTHONPATH=. 主.venv/bin/python` 跑(PYTHONPATH 盖过 editable install),完事 `git worktree remove --force`。

**国产适配现状(2026-06-29 实证)**:本机只 **Qoder 装了**(已适配✓)。Trae(字节)/通义灵码(阿里)/腾讯 CodeBuddy/MarsCode(字节)**都没装**→没真实数据没法可靠写+测 adapter,等装了/给样本再做。**Hermes(Nous)/OpenClaw(MIT,SOUL.md+AGENTS.md+skills,🦞)** 是开源同类 agent、格式趋同(OpenClaw 的 AGENTS.md 和 Codex 同源),可行性比 IDE 工具高,但**用户没装=没资产可迁**,现在做 adapter 没东西可迁也没法验证。

**下一步**:① MCP snippet 存全 spec(adapter 里把 command/args/env/url 带进 MigrationItem,现在只 name/needs/origin);② Trae/通义/腾讯/字节等装了或给样本再补 adapter;Hermes/OpenClaw 同理。
