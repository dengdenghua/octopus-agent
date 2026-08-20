---
name: desktop-mode-feature
description: 横屏「本地虚拟电脑」桌面模式(DesktopActivity)——浏览器桌面+右对话+科幻全息皮肤+Zero 角色
metadata: 
  node_type: memory
  type: project
  originSessionId: c29e0497-ca40-419c-897a-a2f1c0561182
---

横屏「桌面模式」= **本地虚拟电脑**(不是真 macOS;真 Mac 是"远端电脑"WebRTC 那条)。锁横屏的 `ui/desktop/DesktopActivity.kt`(AppCompatActivity + configChanges 防旋转闪断 WebView + FLAG_KEEP_SCREEN_ON 常亮)。

**入口**:对话框上方的**设备选择器**(`ChatScreen.TargetSelector`)里的「本地虚拟电脑」项 → 启动 DesktopActivity。设备选择器四类:本机(本地手机)/局域网设备(同类手机)/远程控制电脑(远端电脑,PcRemoteWebrtcActivity)/本地虚拟电脑(桌面模式)。**不从发现页进**(早期放过 FeatureHub,已移除)。也有 opt-in「启动直达桌面模式」(`KVUtils.isDesktopModeDefault`,SplashActivity 据此登录后直接进)。

**布局**:左「直播间」(浏览器桌面 + HUD)+ 右浮动玻璃对话。
- **左=内容宿主** `DeskContent { Web, Discover, Square }`:浏览器 / 发现(DiscoverScreen,点站内链接回 onOpenUrl 在桌面 WebView 打开)/ 广场(AgentSquareScreen)三态切换;底部 **Dock**(macOS 风)摆图标:浏览器/发现/广场 + 已装小程序(`MiniAppRegistry.all()`,点 launch)+ 全部(MiniAppListActivity)。
- **浏览器桌面**复用 `BrowserEngine`/`SystemWebViewEngine`:`engine.createView()` 嵌 AndroidView + `ToolRegistry.setBrowserEngine(engine)` → **Agent 的 `browser_navigate` 等直接作用到桌面这块 WebView**;订阅 `engine.events()` 驱动进度条/「正在打开 X」/地址栏。onDestroy 清理 + clearBrowserEngine。规矩:前台谁显示 WebView 谁 setBrowserEngine,桌面模式在前台不并存 BrowserActivity。
- **右对话** = 现有 `ChatScreen()` 常驻组合,收起时宽度动画 0↔340dp(不丢对话/运行状态,不从组合移除),收起态右下 Zero 头像悬浮球。

**科幻/全息皮肤**(参考 MiniMax OpenRoom“AI 操作的桌面”)= `ui/desktop/DesktopHolo.kt`:`Holo` 青色配色、`HoloBackground`(深空渐变+淡青网格 Canvas)、`Modifier.holoGlass`(半透明+霓虹描边玻璃拟态)、`HudStrip`(顶部直播条:● LIVE 脉冲 + URL + 母体 LINK 态 + 走秒时钟,等宽)。**真·毛玻璃(backdrop-blur)Compose 做不了,用半透明色 glass 近似;ChatScreen 自绘不透明底,所以对话内容区本身不透,透出壁纸的是边框/HUD/Dock/留白**。

**角色资产 = Echo 宇宙的 Zero**(跨仓依赖!):素材从**兄弟仓** `../echo-universe-engine/assets/characters/001_zero/octopus_refs/`(avatar.png/front.png)拷到 `res/drawable-nodpi/zero_avatar.png` + `zero_front.png`。`DesktopHolo.ZeroAvatar`(圆形头像:对话头部 + 悬浮球)、`ZeroCompanion`(全身立绘:原图纯黑底,用**亮度→透明度 ColorMatrix**抠黑底 + 按亮度半透明 → 全息投影感;空闲桌面右侧)。Zero=银发+粉镜片赛博风。更换角色只需换这两张图。相关 [[echo-universe-bind-feature]]。

**注意**:DesktopActivity 曾被并行会话/编辑器同时改(字符串 i18n、engine onPause/onResume、安全加固),提交时用 `git add -A` 别用 `commit -am`(会漏未跟踪的新文件——`DesktopHolo.kt` 就被漏过一次导致 HEAD 编译不过)。构建见 [[build-and-release]]。
