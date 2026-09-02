---
name: octoapk-website-download
description: 官网 octoapk.com=Next.js 站(pm2 bazhuayuapk);v1.0.0 APK 公开下载+二维码已上线
metadata: 
  node_type: memory
  type: project
  originSessionId: 1d6d27c3-dc6a-43a7-97bf-65acc5304019
---

**官网 = 独立 Next.js 站(不在 octopus-mobile 仓库里)**。与 [[octopus-mobile-payment-server]] 同一台 Lightsail(ssh 别名 `mi`,ubuntu@,IP 32.185.238.217):
- `octoapk.com`/`www` → nginx 反代 `127.0.0.1:3000`,pm2 进程名 **`bazhuayuapk`**(next 16/react 19,`next start -H 127.0.0.1`,非 standalone → public/ 运行时直出、不必 rebuild)。
- 代码在盒子 `/var/www/bazhuayuapk/current`(`current→releases` 符号链接部署;**就地改会被下次官网流水线部署覆盖,需同步回官网源码仓库**)。build=`npm run build`(next build),node22。
- 站是双语文案(src/content/home.ts en+zh),满站"立即下载 APK"CTA 全指向 `/download`。
- `nginx` sites-enabled:api./club./octoapk.com;api. 的 `/api/v1/registry/`→8090、`/`→8081。

**2026-07-05 已做:官网 APK 公开下载 + 扫码上线**
- 本机 release 包 `app/build/outputs/apk/release/OctopusMobile_v1.0.0_universal.apk`(59.2MB,versionCode 9,minSdk28=Android9.0+,V2 签名,sha256 `86bb3a08…`,用户确认是**正式发布 key**)→ scp 到 `current/public/octoapk.apk`,线上 `https://octoapk.com/octoapk.apk`(200,mime application/vnd.android.package-archive,长度精确一致)。
- 二维码 `current/public/qr-octoapk.png`(离线 python qrcode 生成,编码 `https://octoapk.com/download`)。
- `src/app/download/page.tsx` 从"coming soon"占位改成真下载页(直下按钮+二维码+版本/大小/Android 要求+安装步骤+sha256);改前备份 `page.tsx.bak_*`。next build 通过 + pm2 restart，线上验证全绿。

**2026-07-05 二次更新:换官网品牌图标 + 带最新代码重打包**
- 应用图标 `app/src/main/res/drawable/ic_launcher.xml` 换成官网 logo(深底白章鱼,由 public/icon.svg 转 Android 矢量,章鱼放大 1.22×;像素级一致验证过);versionCode 9→10(versionName 仍 1.0.0),同发布 key `be4d2eb2…` 签名 → 已装可 OTA 覆盖。commit 7e3a90f(icon+build.gradle.kts)。
- 重打签名 release(含当时最新树:artifacts 面板 04946f8 等)→ 新 universal **82.7MB**,sha256 `2492f8b4…` → 覆盖 octoapk.com/octoapk.apk;下载页 SIZE 83 MB + SHA256 同步更新。线上验证:apk content-length 82705115、页面新 sha 全绿。

**2026-07-05 v1.0.0 正式合并发布(vc11)**
- 分支曾分叉(feat/script-sandbox-upgrade ↔ main,今天 14:28 起):10 对平行重复提交(同工作不同 hash)+ feat 独有 5 个 UI 提交(icon/历史/图片/玻璃/TV)+ main 独有 1 个沙箱安全修复(12b2cf9)。cherry-pick 12b2cf9 到 feat(干净,→00ffa81)使 feat 成内容全集;versionCode 10→11(c103a93);再经隔离 worktree 把 feat 合入 main(仅 WebActivity 一处冲突,取 feat 侧图片修复;merge 294e43c),**main 现 == feat 内容 == 已发布 vc11**。
- 新 universal 包 82.6MB,sha256 `c18aa222…`,同发布 key `be4d2eb2`(可 OTA 覆盖 vc10/vc9)→ 覆盖 octoapk.com/octoapk.apk;下载页 sha 同步。线上验证全绿。
- ✅ 已 push origin(`12b2cf9..294e43c main->main`,ff 18 提交,github.com/dengdenghua/octopus-mobile main 与 origin/main 同步)。当前本地工作树仍在 feat/script-sandbox-upgrade(== main 内容)。

**⚠️ 真实下载机制(2026-07-05 才查清,之前一直搞错)**:官网下载按钮 → `octoapk.com/downloads/OctopusMobile_v1.0.0.apk` →(nginx 302)→ `download.octoapk.com/OctopusMobile_v1.0.0.apk` →(nginx vhost `sites-available/download.octoapk.com` 的 `location = /OctopusMobile_v1.0.0.apk` **alias**)→ **`/var/www/bazhuayuapk/shared/downloads/OctopusMobile_v1.0.0.apk`**。这个文件在 `shared/`(Capistrano 持久区,**扛住 current→releases 频繁重新部署**),文件名固定 `OctopusMobile_v1.0.0.apk`。**换 APK = 覆盖这一个文件即可**(scp 到 shared/downloads,保持同名);nginx+CF 自动服。之前误把包传到 `current/public/octoapk.apk`(Next public):既不是按钮指向、又被每几分钟一次的重新部署覆盖 → 用户一直下到 shared 里那个没换的原始 59MB。CF 对该 apk 有 max-age=86400 缓存,换文件后个别边缘可能短时服旧包,彻底即时生效需在 Cloudflare 面板 purge 该 URL(用户侧)。下载页(Next 源码 src/app/download/page.tsx)在**官网源码仓**、就地改会被部署覆盖 —— 展示的版本/大小/sha 要改得回源码仓改。

**2026-07-06 vc12 发布(实时语音 + 灵感修复)+ 首次开启 OTA**
- **内容**:实时语音四阶段(通话/工具接管/个性化+声音克隆,见 [[octopus-mobile-voice-realtime]])+ **灵感帖详情 R8 修复**(proguard 漏护 SquarePostApi 的 *Result wire 类 → release 下列表能出但点进去内容全空;补 `-keep SquarePostApi$*` + `BrowserPluginHost$PluginFile`;服务端 feed 去重掉带斜杠 id 的 plugin 重复帖)+ LLM 备用模型等。versionCode 11→12(build.gradle.kts,commit 27e8780),versionName 仍 1.0.0,同发布 key CN=Octopus Mobile(be4d2eb2)→ 可 OTA 覆盖 vc11。
- **签名 release 包**:universal 82.9MB,sha256 **ada61d18…**(本机 = 源站核对一致)。本机在 `/Users/dangbei/Public/octopus/octopus-mobile/OctopusMobile_v1.0.0.apk` + 桌面 `~/Desktop/`。
- **发布下载站**:旧 4 文件先移到备份 `shared/downloads_bak_20260706-094753/`(可回滚),新包 scp 覆盖 `shared/downloads/OctopusMobile_v1.0.0.apk`(sha256 核对一致)。
- **🔴 踩坑(已修)——官网链接的文件名变了、我移错文件把下载搞挂**:上面老记录说官网按钮 →`octoapk.com/downloads/OctopusMobile_v1.0.0.apk`→302→`download.../OctopusMobile_v1.0.0.apk`,但官网早已改版,**下载页现在直接硬链 `https://download.octoapk.com/OctopusMobile_v1.0.0_vc11.apk?v=20260705222144`**(文件名固定 `_vc11.apk`+`?v=` 缓存串;`curl octoapk.com/download | grep -oE 'OctopusMobile[^"]*apk'` 可查真实链接)。我发布时按老记录只更新了 `OctopusMobile_v1.0.0.apk`、还把 `_vc11.apk` 移进备份 → 官网那个 URL 404(CF 还缓存了 404)→ **全站下载失败**。**修法**:`cp shared/downloads/OctopusMobile_v1.0.0.apk shared/downloads/OctopusMobile_v1.0.0_vc11.apk`(让官网链的文件名装新版 vc12 内容,文件名叫 vc11 但内容是 vc12=功能对、名字误导),CF 那份 404 缓存约几分钟后 EXPIRED 自动重取到 200。已完整下载核 sha256 = vc12。**教训:换版前先 `curl octoapk.com/download` 看真实链接文件名,把 vc12 放到那个名上(现在两个名都放了 vc12);别动官网链的文件**。彻底改名要去官网源码仓改 download 页。
- **⚠️ Cloudflare 缓存滞后**:换文件后 `download.octoapk.com/OctopusMobile_v1.0.0.apk` 边缘仍 `cf-cache-status: HIT` 服旧 vc11(max-age 原 24h),约 4h 后过期或去 CF 面板 purge 才即时。**已把 nginx 两个 APK location 的 `Cache-Control` 从 max-age=86400 改 300(5分钟)**(sed 改 `download.octoapk.com` 配置,`nginx -t` 过 + reload;备份 `.bak.20260706-123428`;源站直连已验 max-age=300 + content-length 82882960)——治本,以后换版几分钟全网刷新;但**已缓存的那次旧对象不受影响**,首次切换仍需 purge/等过期。
- **✅ 首次开启 OTA 推送**(app 内在线升级,机制见 AppUpdater.kt:MainActivity 启动 `AppUpdater.check()` 查 `/app/latest`,设置页也可手动;弹框 AppUpdateHost;下载装用 FileProvider+ACTION_VIEW+REQUEST_INSTALL_PACKAGES,同签名原地覆盖不卸载不丢数据)。**之前一直没配所以 `/app/latest` 报 versionCode=0(=无更新)**。这次在 [[octopus-mobile-payment-server]] 盒子 `.env` 加 `APP_UPDATE_VERSION_CODE=12` + `APP_UPDATE_VERSION_NAME=1.0.0` + `APP_UPDATE_APK_PATH=/home/ubuntu/octopus-server/octopus-latest.apk`(vc12 独立副本,不依赖下载站)+ `APP_UPDATE_NOTES`(备份 `.env.bak.20260706-103904`)→ 重启 octopus-account。验证:`/app/latest` 本地+公网都报 **versionCode 12**(该 API 端点不走 CF 缓存、即时生效),`/app/latest.apk` sha256 ada61d18 = vc12。**vc11 用户下次开 app 即弹升级**(force=false 可"稍后")。以后发新版:换 octopus-latest.apk + 改 `APP_UPDATE_VERSION_CODE` + 重启即可。

**后续更新 APK 姿势(旧记录,已过时——见上方真实机制)**:替换 `current/public/octoapk.apk`(同一发布 key 才能覆盖安装)+ 改 download/page.tsx 里的 VERSION/SIZE/SHA256 常量 + `npm run build` + `pm2 restart bazhuayuapk`;并把页面改动同步回官网源码仓库以免被部署覆盖。Shizuku 辅助包另在 8081 的 `/downloads/shizuku.apk`(app.py 路由)。
