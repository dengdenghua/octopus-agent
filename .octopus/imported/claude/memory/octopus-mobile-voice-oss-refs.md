---
name: octopus-mobile-voice-oss-refs
description: "Phase 2 Android 实时语音客户端可借鉴的开源 repo 清单(48代理调研核实40个真实repo)"
metadata:
  node_type: memory
  type: reference
  originSessionId: 1d6d27c3-dc6a-43a7-97bf-65acc5304019
---

给 [[octopus-mobile-voice-realtime]] 的 **Phase 2 Android 客户端**准备的开源参考(2026-07-06 多代理调研:93候选→去重57→WebFetch核实40真实存在)。核心洞察:服务端代理那层我们已比业界同类完整(大多没计费);缺口在 **Android 裸 PCM 客户端**——高 star 项目大多 Web/iOS 或走 WebRTC(音频被 SDK 黑盒,拿不到代码),真正能搬 Kotlin 裸 PCM 的很少。

**骨架来源顺序(直接照此搬)**:
1. **音频采集/播放金矿**:`pipecat-ai/pipecat-client-android-transports`(**BSD-2 可直接 vendor**),`gemini-live-websocket` 模块的 `AudioIn.kt`(AudioRecord+`AudioSource.VOICE_COMMUNICATION` **自带AEC回声消除**+16k/MONO/PCM16,回调裸 byte[]→Base64→`input_audio_buffer.append`)和 `AudioOut.kt`(AudioTrack 24k/MODE_STREAM+队列+后台线程+`interrupt()`清队列打断)。走 WS 分支不是 WebRTC 模块。
2. **协议+平台交叉参照**:`fuwei007/OpenAIAndroidRealtimeDemo`(★21 Kotlin,⚠️无license只能参照重写)——OkHttp WS+AudioRecord/Track+与我们完全一致事件集;`WebSocketManager.kt` 的 onMessage 按 event type 分发是事件循环模板。交叉验证用 `klomash/openai-realtimeapi-android-agent`(★6 MIT,`AudioPlay.kt` 几乎整文件可用+barge-in 收 speech_started 就 clearAudioQueue)。
3. **协议字段真值**:`dashscope/dashscope-sdk-python`(★67 官方活跃)的 `dashscope/audio/qwen_omni/omni_realtime.py`——与我们代理同协议两端,音频枚举 PCM_16000HZ_MONO_16BIT(上行)/PCM_24000HZ_MONO_16BIT(下行)、server_vad 参数。**session.update 字段照它抄别照 OpenAI 文档猜**(枚举名不同)。
4. **框架级对照**:`pipecat-ai/pipecat`(★13.2k BSD-2)services/openai/realtime/ + transports/websocket/;`BerriAI/litellm`(★52.7k)有 /v1/realtime 代理+按 user/team 计费门控可对照我们的计费中间件。
5. **通话 UI**:抄 pipecat 两个 android demo(gemini-live-websocket-demo / openai-realtime-webrtc-demo)的 Compose 组件(权限页/麦克风按钮/音量波形/**计时器**呼应按分钟计费)。
6. **VAD 下沉(可选优化)**:`ten-framework/ten-vad`(★2.2k,有 Android arm64 预编译 .so)——客户端本地 VAD:有语音才上行省计费分钟+本地即时打断降延迟。

**Phase 2 五个易踩坑**(调研提炼):①不用 VOICE_COMMUNICATION → AI 声音被采回自问自答(AEC 必备);②播放要抖动缓冲(队列+补静音)否则爆音;③DashScope server_vad 自动断句**不用手动 commit**;④barge-in 收 speech_started 立即清未播队列+可发 response.cancel(最易漏);⑤所有 demo 都客户端硬编码 key 直连上游——我们已 key 收服务端,客户端只连 `/voice/realtime`+用户 token,别学它们。

**避坑别碰**:LiveKit/WebRTC 全系(音频 SDK 黑盒,除非未来做多人房间);twilio demo 是 μ-law/8k 采样率别抄;各类 Rust/Cloudflare 边缘代理、Qwen cookbook 对 Phase 2 零参考。
