---
name: octopus-mobile-inspiration-xhs
description: "灵感 tab 对标小红书(图文社区+可复刻app+付费积分复刻);服务端已成,客户端UI换流待并行重构落地"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1d6d27c3-dc6a-43a7-97bf-65acc5304019
---

**目标(用户拍板)**:octopus-mobile 灵感 tab 从"复刻式发现流"改成**小红书式 square_posts 双列瀑布流** + 部分帖子关联可运行 app/例程能"一键复刻/下载" + 其中一些复刻要**花付费积分**。三合一 = 小红书 × 应用市场 × 积分付费墙。

**两个钱/内容决策(用户已定)**:①付费复刻 = **作者自定价 + 平台按 `CREATOR_REVENUE_SHARE`(默认0.7)抽成**;②内容 = **机审干净自动上架 + 我先种子填充一批**(发帖原本恒 pending 会空流)。

**已完成(2026-07-06)**:
- 服务端地基 `server/app.py` 提交 **83a2327**:square_posts 扩列(app_ref/app_kind/price_credits/topic)+ 新表 square_unlocks(PK幂等)+ `_present_post` 输出这些字段+owned + `/square/feed?topic=` 分类过滤 + publish 支持关联应用/定价/机审自动上架(可疑留人工、盗挂防护)+ **新端点 `POST /square/posts/{id}/acquire`**(照 `/plugin/pay` 范式:原子扣积分不透支/余额不足402/unlock幂等/交付前校验/作者分成)。test_app.py +8 测试,全套 **175 通过**。**未部署盒子**。
- 客户端数据层 `SquareCatalog.kt` 提交 **33a1eae**:SquarePostDto/AgentPost 加 5 字段 + `remoteFeed(topic)` 按分类拉取+分桶缓存。纯 additive。
- 增量2b **灵感 tab UI 换流** 提交 **7a48e12**:ExploreTab 换 `SquareRepository.remoteFeed(topic)` + 复用 `AgentPostCard`(改 internal)+ 点击 `navigate(square_post/{id})` + NavigationGraph 接 onOpenPostDetail;删掉过时 discovery 详情链路 336 行。compileDebugKotlin 绿、我的4文件 detekt 干净(module 仅剩并行 34d9ef6 的 OctopusComponents/KButton MagicNumber ×3,非我)。

- 增量3 **复刻/付费UI** 提交 **c76cac4**:`SquarePostApi.acquire()` + `CommunitySquareApi.parseDownloadPayload`(暴露既有 parseDownload;acquire.app 与社区 download 的 data 字节同款)+ PostDetailScreen 的 `AppAcquireCard` 三态(免费/N积分/已复刻)+ 付费确认弹窗 + 调 `CommunityMiniAppInstaller.install` 落地。硬付费墙(body 付款后才下发)。compile 绿、我文件 detekt 干净。

- 增量4 **发帖关联应用+定价+分类** & feed 应用帖徽标 提交 **0e813a1**:CreatePostScreen 加 6分类 chips + 选填「关联应用 slug + 复刻定价」;publishPost 扩 topic/appRef/appKind/price;AgentPostCard 右上角「可复刻/N积分」徽标。
- 增量5 **部署 + 种子 完成并生产验证**:全量部署已提交 app.py→盒子(`app.py.bak.20260705-172348`+`octo.db.bak.*` 备份;盒子零独有逻辑纯子集,顺带上线了个人网页 remote_sites 端点)。迁移生效(square_posts 新列+square_unlocks+remote_sites 表)。种子(**重建过**:初版 5 条图文帖是空口宣传假货被用户指出,已删):现为 **8 个真·自包含 mini-app 全做成可复刻应用帖**——小费计算器/BMI/单位换算/随机决定/口算(免费)+ 番茄钟30/房贷计算20/记账本50(付费),纯 HTML 无外部资源、离线可用、作者 official。8 个全过验证(sha256完整+node --check JS语法+DOM id引用)+ 浏览器实渲染确认(BMI 22.5、房贷月供¥4490 计算正确)。**生产端到端 14/14 通过**(feed→免费复刻交付body+sha256对齐→付费扣款+official分成→幂等),测试副作用已清。种子重建脚本 seed_rebuild.py 在 scratchpad。

**4 篇官方教程帖**(post_tutorial-*,新手上手/Shizuku/无障碍保活/远程指挥,seed 重建没碰它们)原本无封面,已配真封面:Canvas 画渐变+emoji+标题→PNG(经本地 saver 端点存盘避免 base64 灌上下文)→传盒子 uploads/→cover_url+images 设**绝对 URL**(https://api.octoapk.com/static/tutorial-*.png;绝对是因为 AgentPostCard 不给 /static 前缀加 base)。发帖封面设置提交 **08e688a**(首图=封面+徽标,点其他图设封面;服务端取 images[0])。

**插件按月积分订阅(用户选:手动续订 + 先建订阅核心+mini-app门控)**:服务端核心**已构建+183测试全绿**,但**在 HEAD 隔离副本上做的、未落地**——并行 session 的 server WIP(FTS搜索/图片安全重编码/中间件/healthz,还动了 square_feed)一直**未提交**,直接改工作树 app.py 会缠一起没法干净提交。改动存成 git 补丁:`scratchpad/sub/subscription-server.patch`(app.py +127/-6)+`subscription-test.patch`(+141)。**已部署盒子并生产验证 17/17**(scratch app.py=HEAD+订阅补丁,是线上干净超集,4921→5042行;备份 app.py.bak.20260705-183609;未订阅→激活→续订顺延→402→幂等 全过,测试数据已清)。**服务端已落地仓库** 提交 **0f14719**(并行 f94da9b 后端安全加固+app.py软拆分提交后,rebase 到新 app.py 重套编辑,183 测试全过)。**客户端订阅流已落地** 提交 **f3e94c7**:SquarePostApi.subscribe/subscriptionStatus + AgentPost/DTO 加 subPriceCredits/subActive + PostDetailScreen SubscribeCard(订阅/续订+确认弹窗→subscribe→安装→SubscriptionGate.mark)+ 新 SubscriptionGate(标记订阅制+checkActive fail-open)。**门控 enforcement 已补** 提交 **b4f0f62**(等并行 mini-app 子系统重写稳定 9f259ab 后,MiniAppActivity.onCreate 抽出 launchWebView + 订阅制打开前 lifecycleScope 异步 checkActive 失效即拦;@file:Suppress 兜 baseline 失配)。**按月订阅彻底闭环:发帖定月价→详情订阅/续订扣款分成→装应用+标记→打开校验失效即拦。**

**动态定价/AI自动调价三步走(独立于订阅,admin/运维基建)**:①**动态定价配置** 提交 **fad7df7**(config_kv 表+get_config/set_config 30s缓存+PRICING_KEYS白名单含语音参数+admin GET/POST /admin/api/config+接线 daily/signup_bonus 即时生效);②**定时真实成本核算** 提交 **aea19fd**(cost_snapshots 表+_take_cost_snapshot 复用 _profit_snapshot+后台 _cost_snapshot_loop 按 config 间隔+GET /admin/api/cost-trend+手动触发端点;ENABLE_COST_SNAPSHOTS=0 关);③**AI 调价建议(提议→人工批准)** 提交 **68d7472**(用户选"提议+批准"非全自动):pricing_proposals 表 + POST /admin/api/pricing/advise(qwen 读成本快照+可调参数→产结构化JSON建议→白名单过滤+护栏[夹0~max(10×默认,100)]+去重→存pending)+ list/approve(校验后写config_kv即时生效)/reject 端点 + _extract_json_array 容错。**自动调价三步全闭环**:定时成本核算→AI读趋势产建议→面板一键采纳写动态配置生效。全套测试 205 通过。面板可视化已接 提交 **b0b4436**(ui_html.py 加「定价/调价」tab:动态配置编辑卡+成本趋势表+AI建议采纳/驳回)。**盒子已完整 reconcile 部署到仓库最新**(备份 app.py.bak.20260705-204945+octo.db.bak;装了新依赖 Pillow;部署 app.py 5228行+新文件 ui_html.py;盒子纯子集零丢失;生产全绿:迁移全生效/种子完好8应用4教程/面板/admin/含定价tab/动态配置7参数含语音费率/成本快照手动+后台定时都跑/订阅feed鉴权正常;含他们的安全加固Pillow图片重编码上线)。⚠️注意:box ADMIN_TOKEN 走 systemd EnvironmentFile 原样传值(别 strip 引号)。上游 qwen omni 实时语音≈几分钱/分钟(音频 12.5token/秒,输出贵),定 3-5积分/分钟高毛利。⚠️box 跑的是旧HEAD+订阅(4921基线),落后于 f94da9b 安全加固;下次 repo→box 全量部署会带上订阅(已进仓库)+ 需带 ui_html.py+新dep。设计:square_posts 加 `sub_price_credits` 列(与一次性 price_credits 互斥,标月价则清一次性价)+ 新表 `plugin_subscriptions`(PK user_id+plugin_ref=slug,expire_at 到期即失效);`POST /square/posts/{id}/subscribe`(手动续订:扣月费+70%分成+顺延30天封顶365,自订不扣,idempotency_key 防双击,首订交付app)+ `GET /square/plugin/{ref}/subscription`(运行时门控)+ _present_post 出 subPriceCredits/subActive。**关键认知**:订阅只对"连服务器的插件"(VPN)是硬锁,纯本地 mini-app 只能客户端软门控。**待办**:①并行 server WIP 提交后 apply 补丁+提交+部署;②客户端 mini-app 门控(MiniAppActivity.onCreate 调 status 失效即拦,复用 AccountRepository/OctopusBridge 通道)——现客户端编译红(并行 WorkspaceFolderPicker 缺 import),待树绿再做;③VPN 订阅需 VPN 落地+服务端下发受控配置,延后。

**客户端全链路完整 + 服务端已上线并验证。唯一剩:vc12 发版**——用户装的还是 vc11(旧发现流),要打 vc12 覆盖 shared/downloads/OctopusMobile_v1.0.0.apk 才看得到。⚠️**发版先别急**:从当前 main 打会连带并行 session 的浏览器/UX 大改(他们还有 BrowserScreen/DiscoverScreen 未提交 WIP),等他们落定 + 用户明确点头再发。
- 增量4 发帖:CreatePostScreen 关联应用+定价+选分类。
- 增量5 **种子填充 + 部署盒子**(需授权)。

**阻塞根因 + 恢复条件**:并行 session 在做大规模设计系统重构(改 OctopusDesign/OctopusComponents/NavigationGraph/DiscoverScreen/KButton + ~25 XML),共享树**当前编译红**(OctopusType.tag 在 NavigationGraph:181 解析不了),且 churn 的文件跟增量2b 高度重叠。**共享树勿 stash**。恢复条件:并行重构提交、`:app:compileDebugKotlin` 转绿后,基于新设计系统一次做 UI 换流(不返工)。相关:[[octopus-optimization-scan]] 的 Codex WIP 别碰。
