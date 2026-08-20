---
name: octopus-mobile-skill-marketplace
description: "octopus-mobile 接资产 registry 的「技能商城」(广场→能力):浏览/下载/注入,内置技能保留"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1d6d27c3-dc6a-43a7-97bf-65acc5304019
---

**octopus-mobile 技能商城(用户:「mobile开始,内置技能要保留,广场能力里面加技能商城」+ 决策「2跟3」,2026-06-30)**。
mobile 是资产 registry 的**第一个真产品消费者**(之前只有参考 CLI)。全程 JBR(JDK21)`compileDebugKotlin` 编译验证通过;mobile app 树干净(只 `server/app.py` 是阿泽收款的本地改动,与 app 无关)。

**关键语义发现**:mobile 内置技能 = **可执行工具**(带 `parameters` JSON Schema,LLM 当 function-call 调,有执行器,如点屏/备份);registry 技能 = **指令型**(纯 markdown,无参数无执行器,body 连 frontmatter 都没有,name/description 在信封里)。**故下载技能不能塞进工具列表**(LLM 会调到没执行器的工具出错)。

**落地(3 段,内置 50 技能零改动)**:
- **① 商城本体**:`app/.../registry/RegistryClient.kt`(新)—— `RegistryClient`(列技能 `GET /api/v1/registry/assets?type=skill`、下载 `/{id}/download`、**sha256 校验**)+ `RegistrySkillStore`(落 `filesDir/registry/skills/<slug>/{body.md,envelope.json}` + `.manifest.json` 安装清单 + install/uninstall/setEnabled)。复用 `OctoHttp.shared`+Gson+KVUtils(无新依赖)。UI:`ui/compose/screen/SkillMarketplaceScreen.kt`(新,搜索+筛选+网格+安装/卸载+Toast,复用 GlassCard/GlassTextPill);入口在 `FeatureHubScreen` 的 **Toolbox tab(=「能力」;`nav_features`=「广场」=Features 屏)** 顶部整行(`Icons.Filled.Extension` 拼图图标);`Screen.kt` 加 `SkillMarketplace` 路由 + `NavigationGraph` 注册。
- **② 注入(option 2)**:`RegistrySkillStore.knowledgeBlock(ctx, 6000字上限)` 把**已启用**下载技能的 body 拼成系统上下文 → `LightweightReAct.run` 加 `extraSystemContext` 参数(默认空=零改动)→ 第48行 `ChatMessage.System` 追加 → `BrainModeSelector.kt:216` 的 `react.run(...)` 传 `extraSystemContext=RegistrySkillStore.knowledgeBlock(context)`。**指令注入,不进工具列表**,内置工具调用路径零改动。
- **③ mobile 适配(option 3)**:生产侧 `octopus-enterprise/.../registry.py` 的 `_envelope` 加 `mode`(inject|tool;现都 inject)+ `platforms`(启发式 `_DESKTOP_ONLY_HINTS`=xlsx/pptx/docx/excel… → desktop-only,余 mobile+desktop)。**本地验证:89/97 技能适合手机**(xlsx/pptx-author→desktop-only)。消费侧 `RegistryAsset` 加 `mode/platforms` + `mobileFit`(有字段按字段、否则启发式兜底,兼容**未重部署的线上**)+ 商城「仅手机适配」筛选(默认开)。

**✅ on-device 真机验证已完成(2026-07-01)**:headless AVD(`octo_test`,`-gpu swiftshader_indirect` 绕开之前灰屏)起模拟器 → JBR `assembleDebug` 出 APK → 装机 → 真实邮箱验证码登录(api.octoapk.com 真账号服务)→ 广场→能力→技能商城 → 真实拉到公网 97 个技能 → 点装 brainstorming → 下载+sha256校验+落盘+清单登记(`adb shell run-as` 验证 filesDir 真有 body.md/envelope.json/manifest.json,checksum 对得上)→ 卸载 → 文件真删除、UI 状态回退、toast 确认。**Toolbox 顶部现同时有「技能商城」(我做)+「插件商城」(Codex 并行做的,同源 registry)**。坑:①`monkey`启动失败要用`am start`+正确 SplashActivity 全限定名;②点击坐标须 `uiautomator dump` 取精确 bounds,截图眼估会踩空两次;③App 内有个后台 agent 对话弹"高危操作审批"(与本次任务无关,拒绝掉即可)。**✅ registry.py 的 mode/platforms 已重部署上线**(线上 brainstorming→mode=inject/platforms=[mobile,desktop],89/97 适配手机,盒子重启验证过,收款零影响)。

**真·剩下**:mode 全 inject —— 真·mobile 原生工具技能(带执行器)是更深的内容准备,未做。

相关 [[agent-asset-consolidation]](registry/分发)、[[octopus-mobile-payment-server]](mobile 账号/盒子)。
