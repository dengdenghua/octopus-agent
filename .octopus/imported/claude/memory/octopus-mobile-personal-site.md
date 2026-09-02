---
name: octopus-mobile-personal-site
description: 个人网页 MVP——手机托 filesDir/site、经盒子 /u/<slug>/ 公网中转;已提交未部署
metadata: 
  node_type: memory
  type: project
  originSessionId: 1d6d27c3-dc6a-43a7-97bf-65acc5304019
---

用户方向:让每个用户的**手机**托管自己的个人网页,经盒子中转暴露公网。定位"个人端点/分享"而非可靠托管——手机离线时返 503 可接受(用户 2026-07-05 明确"个人网页我觉得可以接受啊")。决定用**路径版** `/u/<slug>/`(非子域名,子域名要通配 DNS+DNS-01,对单台 Lightsail 过重,留 Phase 3)。

**架构精要**(复用 85-90% 既有机器):
- 承载链路复用 [[octopus-mobile-payment-server]] 的设备 WS:手机出站连 `/remote/device/ws`(RemoteConsoleGateway),盒子 RemoteRelayHub `send_to_device` 按 device_id 定位手机。不用 WebRTC(那是 PC 远控 P2P)。
- 隧道新加的就一层:`type:"http"` 信封 + 请求/响应按 id 关联(hub 的 pending futures)+ 公开入口路由。

**已落地(commit ee3b4b5,branch feat/script-sandbox-upgrade,3 文件窄提交)**:
- 盒子 server/app.py:`remote_sites` 表(slug→设备);`/remote/sites` bind/list/unbind(鉴权+归属/占用校验);RemoteRelayHub 加 open/resolve/cancel_http_request;设备 WS 循环截获 `type:http_response` 兑现 future;公开路由 `@app.api_route("/u/{slug}"|"/u/{slug}/{path:path}")` 在线→转发 await(15s→504)/离线→503/无绑定→404;页面 CSP+nostore+nosniff。
- 手机 PersonalSiteServer.kt(新):只读沙箱,canonicalPath 防穿越、mime 查表、8MB 上限、首启种子 index.html。RemoteConsoleGateway 加 `type:http` 分支,**只调 PersonalSiteServer,绝不触达 ToolRegistry**。
- 隔离铁律:访客一次请求只能产出 filesDir/site 的字节;公网入口只发 `type:http` 信封,永不发 control。即便盒子被攻陷,手机 canonicalPath 也挡住越界。
- 验证:TestClient 跑通 hub 关联/happy-path/HEAD/离线/穿越/bind 校验/IDOR;detekt 零新增(剩 9 条全既有基线);compileDebugKotlin 过。

**盒子当前状态(2026-07-05)**:box(ssh 别名 `mi`,ubuntu@,app.py 在 /home/ubuntu/octopus-server/app.py,systemd octopus-account:8081,venv .venv/bin/uvicorn)仍**未上个人网页代码**(remote_sites/`/u/` 计数=0)。只做过一次**外科式价格改**:sub_99 旗舰月卡 priceUsdCents 6900→6990($69→$69.90)已上线并验证(备份 app.py.pre_price_*;CNY ¥499 未动;commit 76227ad)——刻意没整份覆盖以免带上缓着的个人网页那半。将来个人网页整份前推时价格已在,幂等。

**未做/后续(功能对用户不可用前的缺口)**:
① 盒子部署(scp app.py+restart octopus-account)——**outward-facing 新增公网匿名路由,需用户明确授权**;`/` 已代理到 8081,`/u/` 大概率无需改 nginx(待盒子确认)。② 新 APK 重打包+装到已配对真机(手机半在旧 APK 上是 inert 的,所以盒子单独部署无意义,两半要一起)。③ 用户绑 slug。④ 内容授权入口(现只有种子页+高级用户手塞文件)、静态资源多页、大资源走 WebRTC P2P 绕开盒子——都是 Phase 2。盒子瓶颈:2vCPU/1GB/单 worker,大流量要单独中转层。
