---
name: octopus-account-unification
description: 母本生态账号体系从 molili 统一到 oct 自己的网关(api.octoapk.com)的迁移进度与设计
metadata: 
  node_type: memory
  type: project
  originSessionId: e12c8315-6447-4fdb-a107-2426e3ccf2cf
---

**目标(用户 2026-06-30):把母本全生态账号体系换成 oct 自己的** = 统一到 octopus-mobile 账号网关
`https://api.octoapk.com`(已上线:邮箱验证码登录→JWT、`/account/{balance,membership,usage,profile}`、
`/billing/{goods,estimate,orders}`、`/v1/chat/completions` 按 token 计费、Bearer JWT 鉴权)。详见 [[octopus-mobile-payment-server]]。

**这是 Claude 在推的活、不是 Codex**(molili-discard P 系列 commit 全带 Co-Authored-By Claude)。
在 **octopus-agent / main** 上做。**纪律**:Codex 共享树,只 `git add` 我自己的具体文件、绝不 `-A`、
不碰 Codex 脏文件(它的 WIP 全在前端 UI 层,与账号面不重叠);窄提交进 main(沿用 P 系列,用户选定)。

**打法(用户选「全量含 LLM 计费」)**:agent 建 `oct` 集成镜像 molili,但 client 指向网关、邮箱登录、
OctModelRouter 走网关 `/v1` 让 agent LLM 用量计入统一积分池。octopus-os 随后跟改、enterprise(有独立 better-auth)单列。

**进度**:
- **P1 ✅(早先)**:LLM 路由解耦 molili(`31b7900ba` fallback 改自配模型/`224e5969e` current_actor 中立化/
  `67c2217b6` MoliliModelRouter 出 dispatch/`a0047cac9` 出 provider 目录+包导出)。
- **②/① ✅ `8477e94ed`**:additive 后端 oct 包(纯新文件、未接线)。
  `runtime/adapters/integrations/oct/{config,client,links,router_auth,router_account,router_proxy,__init__}`
  + `runtime/sensing/model_router/oct_router.py`(**OctModelRouter** 替代 MoliliModelRouter)。
  OctLinkStore 存 actor→网关 JWT(`oct_links.json`);邮箱登录存网关 JWT + 签 agent 会话 JWT;
  **无新依赖**(`EmailStr`→`str` 避开 email-validator);client 识别 401 失效/402 余额不足。
- **②a ✅ `db2706b93`**:接线。schema 加 `OctConfig`(frozen)+ `AgentConfig.oct`;app.py `create_app` 加
  `oct_config/oct_link_store/oct_jwt_secret` + cocoloop 鉴权派生折入 oct(oct 启用时其 jwt_secret 优先,
  全局鉴权门校验 oct JWT)+ 挂载 14 路由(/api/auth/oct、/api/account/oct、/api/oct/openai/v1);
  cli_serve 传 `cfg.oct`。**gated `config.oct.enabled`(默认关)**。验证:create_app(oct) 挂 14 路由、
  molili 44 测试零回归、ruff+octopus-lint 0 issue。

- **②b ✅ `1f0c79639`**:dispatcher 接 oct LLM 计费。oct_router.py 加 **OctFallbackRouter**(actor 感知):
  当前 actor 有有效 oct link → OctModelRouter(网关 /v1 计费);否则(guest/未登录/无 link/token 失效)
  → 自配模型 fallback。app.py `_attach_oct_fallback_router` 在 oct 挂载块设 `dispatcher.set_fallback`。
  **不回退 P0**:guest 永远走 self_router、不碰登录门控网关;具名/BYO 模型由 dispatcher 直接命中其 sub-router。
  (洞察:dispatcher 的 guest-rescue 本就按类名含 "Credentials"+消息含"登录态" catch,但用显式 wrapper 更稳。)
- **④ ✅ `77caaffe9`**:`tests/test_oct.py` 22 测试(config/links/client/邮箱登录路由/账号路由/
  OctModelRouter/OctFallbackRouter 四态),上游全用注入 fake http_client。坑:account 路由 `_resolve_actor`
  校验 `required_issuer`,测试 token 须带 `iss="octopus-agent"` + IdentityStore 里有该 actor。

**后端账号+LLM 计费统一全部完成**(4 commit,gated `config.oct.enabled`,molili 44 测试零回归,ruff+lint 全 0)。
开启方式:agent config 设 `oct.enabled=true` + `oct.jwt_secret`(≥32 字符)。

- **③a ✅ `dac1665c5`**:additive 前端 `frontend/src/core/oct/{api,index}.ts`(octAuthApi.emailSend/emailLogin
  + octApi account/refresh/membership/usage/dailyClaim/goods/orders + oct 形状类型)。纯 additive、tsc+eslint 过。
- **✅ 对抗评审 + 加固 `fcdad8db7`(2026-06-30)**:多代理审 5 commit(31 findings→20 确认)。**后端缺陷全修**:
  #1 oct.enabled 缺 jwt_secret 会锁死(schema 强制必填 + 去掉 router_auth 复用网关 JWT 的危险 else);
  #2 call_stream 丢 tools(抽共享 `_build_payload`);#9 401 不标失效(`_mark_dead`);#8 proxy 流式 401 检测;
  #6 oct/molili 互斥(AgentConfig validator);#7 oct_links.json chmod 0o600;#12 builder planner 加 oct.enabled。
  test_oct 26、molili 44 零回归。

**✅ #4 已做 `78b88ac8a`**:meta_router 加 oct_config 参数 + `/api/auth/providers` 在 oct.enabled 时返回
{id:'oct',label:'邮箱登录',endpoint_send/verify};app.py 调用处传 oct_config。验证:create_app(oct)→providers 含 oct。

**✅ #5 登录 UI 已做 + 浏览器验证 `57b96811a`**:AuthProvider 加 `emailLogin`(→octAuthApi.emailLogin→写 agent JWT,镜像 smsLogin);login/page.tsx 加 `EmailLoginForm`(邮箱+验证码+倒计时)+ `hasOct` 渲染分支(hasOct+local→Tabs;仅 hasOct→邮箱表单)。**preview 实测全链路**:3 服务(agent 前端 3000 + agent 后端 8000[config.local.yaml oct.enabled] + oct 网关 8099[octo-admin 配置, octopus-mobile server, ALLOW_MOCK_AUTH+EMAIL_MOCK_CODE=123456])→ 登录页渲染 oct 邮箱表单无 console 错 → 填邮箱→获取验证码(mock devCode 123456)→ 登录 → agent JWT 落地 → 跳 /workspace、账号自动建。**坑**:mock 网关 login 要求该邮箱先发过码(跳过发码会合法 401);preview_fill 不触发 React 受控 onChange,要用原生 value setter + input 事件。
**preview 复跑**:`config.local.yaml` 已配 oct.enabled + base_url=http://127.0.0.1:8099 + jwt_secret(gitignored,未提交);session 根 `.claude/launch.json` 已加 `agent-backend`(8000)/`agent-frontend`(3000)配置;先 preview_start octo-admin(网关)→ agent-backend → agent-frontend。

**✅ ③c 消费者积分切换全部完成(用户「都做完不要遗漏」,2026-06-30)**:
- **#3 `45a5c3fea`**:`core/oct/hooks.ts`(useOctLink/useRefreshOctCredits/useDailyClaimInfo[从 membership 派生]/
  useClaimDailyCredits/useOctGoods/useCreateOrder/useFindOrder)+ normalize() 补 surplusCredits/isMember;OctBalance 加这俩字段。
- **#2/#10/#13/#19 `1465dbc58`**:8 个积分消费者切 @/core/oct(hook/字段/类型/moliliApi→octApi);OctBalance 加 molili 兼容
  optional 字段(plan/modelDisplayName/creditsSummary,oct 永不填→旧渲染块优雅显示空)→ 零字段重写、不崩。
- **#11 `e446c19fa`**:订单/充值流 subscription-settings+pay-order 切 Stripe(payUrl 非 data.paymentLink、goodsId string、
  priceFen、findByOrderNo 轮询)。
- **#5 `d46df4167`**:前端测试 mock molili→oct(model-picker.test/user-menu.smoke,26 passed)。i18n email key 由并发编辑/前序已加齐 4 locale。
- **#17/#14 `dfcb7d95f`**:config.example.yaml 加 oct 段 + molili 标废弃;#14 双 config 沿用 molili 模式不强拆。
**验证**:tsc 0 错、前端 26 测试过、后端 70 测试过(oct26+molili44 零回归)、preview 浏览器登录全链路通(fullflow@→workspace)+
/api/account/oct credits=100 + workspace 重载无 console 错。**oct 迁移共 14 commit(8477e94ed…dfcb7d95f)。**

**⏸️ 延后两项(树静默后做,强做会撞活跃 WIP——本程实测 Codex 在并发 commit agent main:cowork/teamroom/octopus-runtime + login/i18n)**:
- **⑤-os(task#7)**:octopus-os 正大改原生 Electron shell(507 脏文件),账号前端 stale fork。os 后端 re-pip 即自动继承 oct;
  前端 oct cutover 待 os shell WIP 收口后照搬 agent 的 core/oct+消费者切换。
- **删 molili(task#8,P3-full)**:要动 app.py/schema/login/i18n —— login/i18n 正被 Codex 并发改,强删撞 WIP。molili 已功能性禁用
  (oct.enabled+molili.enabled=false+互斥校验),删它纯清理。待 Codex agent WIP 收口后删整包(清单见 task#8 描述)。
**preview 复跑**:launch.json 已配 octo-admin(网关8099)/agent-backend(8000)/agent-frontend(3000);typecheck=`cd frontend && PATH=~/.local/node/bin:$PATH pnpm typecheck`。

**网关接入要点**(client 视角):登录最少 `POST /auth/email/send`→`POST /auth/email/login`(拿 JWT)
→ `GET /account/balance` → `POST /v1/chat/completions`(Bearer,网关计费)。会员 BYO 在网关侧免扣积分。
