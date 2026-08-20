---
name: echo-universe-bind-feature
description: "Octopus 宇宙 6 仓生态 + echo-universe-engine 的'绑定角色进宇宙'数字生命模拟功能(跨 echo+mobile,并行会话在建,release 已验证)"
metadata: 
  node_type: memory
  type: project
  originSessionId: aa494889-9cf1-4899-a403-3e5977c80b7a
---

**Octopus 宇宙** = `/Users/dangbei/Public/octopus/` 下 6 个仓库:`octopus-agent`(母体核心运行时,FastAPI,所有项目基础依赖)、`octopus-os`、`octopus-mobile`(Android端)、`octopus-enterprise`、`octopus-storage`、`echo-universe-engine`。母体暴露 realtime WS(`/api/realtime` turn/start)、Android 设备协议(`/api/android/ws/{id}`,mobile 用它被母体驱动)、OpenAI 兼容网关(`/v1/chat/completions`)、多provider model router。

**echo-universe-engine** = "ECHO 回响纪元" Soulpunk 世界观内容工厂(FastAPI) + 一个**"绑定角色→进入宇宙→数字生命模拟"**功能:per-user `UserCharacterBinding`、`UniverseFeed`(角色每日生命态:beliefs/goals/friends/diary/day)、身份分层(免费=Edge Ghost)、经济(钱包+`GhostSubscription`订阅一个角色)、`realms`(多人共享"场")、`npcs`(bindable canon 角色)。后端默认跑 **:8011**(mobile 配置默认,README 写的是 8010)。echo LLM 默认 `model_provider=stub`;设为 `octopus`/`relay` 可把生成路由到母体或 mobile 的中转计费网关(api.octoapk.com)。

**mobile 侧**:`UniverseScreen.kt`/`UniverseRepository.kt`(在 `ui.compose.screen`),入口 = FeatureHub 顶部"我的 Ghost"pill。默认 echoUniverseBaseUrl=`http://10.0.2.2:8011`,Ghost 对话走母体 `octopusRuntimeBaseUrl`=`http://10.0.2.2:8000`。

**状态(2026-06-24)**:整套功能是**并行 Codex/Trae 会话的未提交工作区改动**,横跨 echo(branch main)+ mobile(ui-fixes-and-tokens),两边都没 commit。我在 release 包上实测:绑定 Eve→生命态(Focus/Goals/Relations/Diary)全部正确渲染。Ghost 对话需母体 :8000(没起,未验)。R8 keep 见 [[build-and-release]](宇宙/广场 DTO 同包,字段名==JSON键,必须 keep)。
