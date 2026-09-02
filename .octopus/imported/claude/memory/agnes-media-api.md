---
name: agnes-media-api
description: "Agnes(apihub.agnes-ai.com)图像/视频生成 API 格式 + 约束,给 octopus 生图/生视频增值插件用"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 1d6d27c3-dc6a-43a7-97bf-65acc5304019
---

Agnes 端点 `https://apihub.agnes-ai.com/v1`(OpenAI 兼容,key=`AGNES_API_KEY` 只在服务端)。`GET /models` 共 5 个:文本 `agnes-1.5-flash`/`agnes-2.0-flash`;图像 **`agnes-image-2.1-flash`/`agnes-image-2.0-flash`**;视频 **`agnes-video-v2.0`**。Agnes 是免费额度(见 [[octopus-mobile-payment-server]],并发弱已退出文本主力、转做生图/生视频增值)。

**图像** `POST /images/generations`(OpenAI 标准复数),**同步**。req `{model,prompt,n,size}` → resp `{created,data:[{url,b64_json,revised_prompt}],usage}`;url 形如 `https://platform-outputs.agnes-ai.space/images/t2i/xxx.png`。usage 全 0(不按 token 计费)。图像无明显限流。

**✅ 视频可用(2026-06-29 更正,之前误判)**:生图稳(秒回 200+url),**视频也能用 —— ~2 分钟出片、产出真 mp4**。之前误以为"不交付"纯因**轮询端点写错**:用 `GET /videos/{task_id}` 返回永久假 `queued`,正确是 **`GET /agnesapi?video_id=<video_id>`(根路径,视频 URL 在 `remixed_from_video_id` 字段)**。已修(PR #28→main `ac4f591`):server `video_poll` 改对 + 部署线上、MediaRepository 改 video_id 轮询、重新启用 `generate_video`/`check_video`。**教训:端点查错就下"不交付"结论是误判,幸亏用户让我细查。**

**视频** `POST /video/generations`(**注意单数 video**,复数 `/videos/generations` 是 Invalid URL),**异步任务制**。⚠️**限流 1 次/分钟(全账号共享)= 增值配送的硬瓶颈**。req `{model,prompt}`(默认 5 秒/1280×704)→ resp `{task_id,video_id,object:"video",status:"queued",progress:0,seconds:"5.0",size:"1280x704"}`。**轮询(唯一正确端点):`GET {根路径}/agnesapi?video_id=<video_id>`** —— 注意①在根路径不在 /v1;②用提交返回的 `video_id`(174 字符那个)不是 task_id。响应:`{status:queued→in_progress→completed, progress, remixed_from_video_id=完成后的 .mp4 URL}`。**⚠️坑:`GET /videos/{task_id}` 返回永久假 `queued`,千万别用(我曾因此误判视频不出活)。** 生成耗时实测 ~2 分钟。

架构定调:key 不出服务端 → **服务端中转端点**(类似现有 chat relay),member 门控 + 视频严格配给。

**已落地(2026-06-29,线上部署+验证)**:app.py 加 3 个端点(绕过 `_resolve_model`/FORCE_MODEL,直走 agnes provider):`POST /v1/images/generations`(同步,实测真出图 200+url)、`POST /v1/video/generations`(异步,返 task_id)、`GET /v1/video/generations/{task_id}`(轮询透传 Agnes `GET /videos/{id}`)。门控:会员/白名单免费,非会员原子扣分(`IMAGE_CREDITS=8`/`VIDEO_CREDITS=40`,上游失败自动退款 `_charge_media`/`_refund_media`);视频额外 `VIDEO_DAILY_QUOTA=3`/天 + 1/分钟(呼应 Agnes 全账号 1/min,繁忙友好提示)。备份 `app.py.pre_media.20260629_075750`。仓库同步在分支 `chore/server-qwen-sync`(commit `5579c8f`)。

**App 端已全做完(客户端层 + UI),未编译验证**:
- `app/.../media/MediaRepository.kt`(object,镜像 HttpAccountGateway:OctoHttp.shared + Gson + Bearer token,Result 包裹):`generateImage(prompt,size)`→图 url;`submitVideo`/`pollVideo`;`generateVideo(prompt,onProgress)` 一站式提交+每3s轮询(~3min超时)。透传服务端友好错误(402/429/detail/error.message)。
- **入口形态(2026-06-29 用户拍板:不要账户页,做成 agent 工具)**:生成能力接进 agent 工具系统(`tool/impl/` + `ToolRegistry.registerCommonTools`)——用户在对话里说"画只猫"→agent 自动调,结果出在对话里。3 个工具:`generate_image`(同步出图,返回 url+markdown)、`generate_video`(异步提交返 task_id,不阻塞)、`check_video`(凭 task_id 轮询)。均 `runBlocking` 调 MediaRepository(同现有 5 个工具),生成类 `isIdempotent()=false`(失败不自动重试防重复计费)。
- **曾走错一版**:先做了独立 `MediaActivity` 挂账户页(为避阿泽 agent/chat 热区 WIP),用户批评"埋钱包页烂 UX"→**已 `git revert`(e8fe3b6→162907e)**,MediaActivity/activity_media.xml/manifest 入口都撤了。教训:为规避冲突牺牲 UX 还不说明=错。

**整条 qwen 迁移 + 生图/生视频在分支 `chore/server-qwen-sync`,7 个 commit**(qwen单档锁→隐藏档位→媒体服务端→MediaRepository→[媒体UI→revert]→agent工具),**基于新 main rebase 过**。**在隔离 git worktree(scratchpad/wt-qwensync)里做的——因为阿泽在主树实时改 agent 文件、不能在主树切分支**。**已 merge 进 main(PR [#27](https://github.com/dengdenghua/octopus-mobile/pull/27),merge commit `681507f`,9 个 commit 含编译修复 `fc170fb`)。** 整条 qwen 迁移 + 生图 agent 工具已落主线、推到 origin。rebase/merge 实测零冲突。

**待办**:① ✅ **已本地编译验证通过**(Android Studio JBR/JDK21,`compileDebugKotlin`+`assembleDebug` 全 BUILD SUCCESSFUL、出 APK;揪出并修了漏实现 `BaseTool.getDescriptionEN/CN` 的 bug——静态检查抓不到、只有真编译能抓);② ✅ 视频已修能用(PR #28,轮询走 `/agnesapi?video_id=`,~2分钟出片,`generate_video`/`check_video` 已重启用);③ GitHub Actions CI 被**账单**卡(私有仓库免费额度用尽,需补付款/提额度或自建 runner)——但本地能编(Android Studio JBR),不阻塞;④ PR #27+#28 已 merge 进 main;⑤ **聊天内嵌渲染图片/视频(PR #29 已 merge 进 main `596c404`)**:改 `ui/compose/screen/ChatScreen.kt` 的 `AgentBubble` —— Markwon 渲染 markdown 文字(加依赖 `markwon-core`+`markwon-image`,**别用 image-glide/coil 插件**,你 Glide5/Coil2 会冲突)+ **裸 URL 检测**(只认 `platform-outputs.agnes-ai.space` 域)图片用 Coil `AsyncImage`、视频用系统 `VideoView` 内嵌。**关键坑:agent 回复给的是"纯 URL"不是 `![](url)`,Markwon 只渲 markdown 图,所以图必须按裸 URL 检测**(我一开始只用 Markwon→图不显示,加回裸URL检测才行)。**真机 emulator 端到端验证过:登录→"draw a cat"→agent 出图→图片气泡内内嵌显示 ✅**(adb 驱动:`input text` 不支持中文用英文 prompt;Enter=发送;无障碍服务要用户自己开,我不碰系统安全设置)。视频同路径(VideoView)未单独视觉验、但代码一致。

**剩:merge PR #29 + 轮换 key。**
