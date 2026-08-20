---
name: plugin-ecosystem-plan
description: octopus 自建插件+小程序生态的架构决策与分期蓝图(用户拍板:两头都要)
metadata: 
  node_type: memory
  type: project
  originSessionId: c29e0497-ca40-419c-897a-a2f1c0561182
---

用户要做 octopus **自己的生态** —— 既要"给 agent 加能力的插件",也要"自带 UI 的迷你 app(他的小程序)"。**已拍板:两头都要,分期落地。** 完整设计见 repo 根 **`PLUGIN_ECOSYSTEM.md`**。

核心决策:
- **一份 manifest,4 种 type**(复用 registry 的 `mode×kind`):`knowledge`(✅有)、`browser-script`(✅运行时 [[build-and-release]] 里的 `BrowserPluginHost` 已建)、`tool`(声明式 HTTP配方/工具串联,**不跑任意原生代码**)、`mini-app`(H5 + `octopus.*` 受控桥)。
- **"你的小程序" = H5 + JS 桥**,不需要微信/FinClip 那套重框架(webview + native 桥即可),复用已有 WebView + 工具系统 + 计费。
- **脊梁 = manifest + 权限模型(PermissionGate,默认 deny)+ registry 签名**;安全是主成本(插件碰登录态 + 能驱动手机 = RCE 面,对接 R12 审计)。
- 分发复用 registry(`api.octoapk.com`,sha256 校验已有);分发+能力是护城河,运行时不是。

分期:Stage1 脊梁(PluginManifest+PermissionGate+PluginManager+registry type 接线)→ Stage2 browser-script 接 registry → Stage3 声明式 tool 插件 → Stage4 mini-app 宿主(`octopus.*` 桥 + 小程序宫格)→ Stage5 开发者门户/签名流。

**实现状态(2026-07-01,Stage1-4 运行时已落地,APK 仍 35MB,均未提交):**
- **关键发现:已存在 dex 插件系统**(`com.apk.claw.android.plugin` 包:`PluginManager`(ClawApplication 实例化但**之前从没调 loadAll**)+ `PluginLoader`(DexClassLoader 加载 assets 签名 dex,**fail-closed 拒外部 dex**)+ `PluginManifest`)。我是**扩展**它,不是另起。
- 改:`PluginManifest` 加 `type`(默认 dex,向后兼容)+ browser-script/tool/mini-app 字段;`PluginManager.loadAll` 加 `loadNonDexPlugins()`(**assets-only**,与 dex 同 fail-closed 口径);`ClawApplication` 补调 `pluginManager.loadAll()`。
- 新文件(`plugin` 包):`PermissionGate`(默认 deny,敏感 device/pay 需 KVUtils CSV 授予)、`DeclarativePluginTool`(BaseTool,HTTP 配方,过 allowHost)、`OctopusBridge`(@JavascriptInterface,callTool→ToolRegistry,pay/device 是受网关扩展点)、`MiniAppActivity`(WebView 跑 `file:///android_asset/plugins/<id>/<page>` + 桥;**锁本地源:shouldOverrideUrlLoading 禁远端导航 + shouldInterceptRequest 拦一切非 file 子资源**,对外只走桥)、`MiniAppRegistry`、`ui.featurescreens.MiniAppListActivity`(小程序宫格,FeatureHub 加"小程序"tile)。
- **R8 gotcha(已修):`PluginManifest` 等 Gson DTO 无 @SerializedName,必须 proguard `-keep`** 否则 release 下 type/js/page 解析成默认值、插件全加载不出(因 loadAll 之前没被调用过,这 bug 一直潜伏)。已加 keep。
- **已验证(release 装机):4 类 demo 插件(assets/plugins/demo-highlight=browser-script、demo-ip=tool(get_my_ip)、demo-clock=mini-app)启动日志 `Non-dex plugins: 1 browser-script, 1 tool, 1 mini-app`,无崩溃。** mini-app 的 H5+桥端到端、小程序宫格 UI **未验**(MiniAppActivity exported=false,am start 被拒;且 FeatureHub/浏览器等 UI 全在 login 墙后,本环境无验证码进不去)。
- **未做:registry→插件的真实下载接线(等服务端 inject/code 资产契约)+ pay/device 桥深接 + Stage5。** demo 插件是验证用,可删。
- 注:strings.xml 实为 **LF 无 BOM**([[build-and-release]] 旧记的 CRLF+BOM 已过时,普通 Edit 即可)。
