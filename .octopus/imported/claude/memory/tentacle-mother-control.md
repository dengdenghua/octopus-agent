---
name: tentacle-mother-control
description: "How the 母体 (octopus-agent) controls the phone, and how to test it end-to-end"
metadata: 
  node_type: memory
  type: project
  originSessionId: 27adccef-faf0-404c-bc4e-e6905ab458c1
---

octopus-mobile is designed as a **触手 (tentacle)** of the 母体 (octopus-agent): the phone
is a WebSocket client that connects to octopus-agent's `TentacleWebSocketServer` (port 8765);
母体 sends `tool/execute`, the phone runs the matching BaseTool and returns `tool/result`.
Modes (RuntimeConfigActivity): LOCAL_ONLY (phone is brain), RPC_ONLY (母体 is brain), DUAL.

**This path works — VERIFIED end-to-end 2026-06-13** (母体→open_app/system_key→phone executes,
results return). Before that it had never been run; two interop bugs were fixed in commit
e0284c1 (octopus-mobile): (1) incoming `method` matching was whitespace-sensitive but Python
json.dumps emits `"method": "..."` with a space; (2) the phone sent tool/result as a JSON-RPC
reply, but the server routes by `method` and reads `params.{call_id,success,data,error,duration_ms}`.

**How to test (reusable):**
1. Run the real server from octopus-agent's venv, bound to loopback (loopback bind skips auth):
   `octopus-agent/.venv/bin/python` a driver that does
   `TentacleWebSocketServer(host="127.0.0.1", port=8765, on_device_hello=…, on_tool_result=…)`,
   then `await server.send_tool_execute(tentacle_id, ToolCall(call_id, tentacle_id, tool, args))`.
   (Driver kept at /tmp/tentacle_driver.py during the test.) The emulator reaches the host
   loopback via **10.0.2.2:8765**.
2. On the phone: Settings tab → **母体连接 · Octopus Runtime** (entry added in e0284c1) →
   set Runtime URL `ws://10.0.2.2:8765`, mode RPC_ONLY, Save, Connect. Auto-connect defaults on,
   so once the RPC URL is saved it reconnects on launch.

Gotcha: the 母体-connect config UI (RuntimeConfigActivity) was historically only reachable via
the legacy HomeActivity→SettingsActivity; e0284c1 surfaced it in the Compose Settings tab.
Tool names: 母体 may send `android.tap`; ToolCallDispatcher strips the `android.` prefix.

**Reverse direction — phone controls the PC (ToDesk-style), VERIFIED 2026-06-13** (commit
46ac742 in octopus-mobile): PcRemoteActivity (Settings → 🖥 母体远程桌面) subscribes to
pc_screen/subscribe, renders push_pc_frame JPEG frames (frame protocol: 2B id-len + type
0x02=JPEG + flags + id + JPEG), and sends taps as `remote/input` (normalized coords;
tap=left, long-press=right, ⌨=type). Reuses the existing OctopusMobileClient WS.
母体 side: `octopus-agent/scripts/pc_remote_server.py` (standalone) — mss screenshot →
push_pc_frame @6fps 960×540, remote/input → pyautogui click/type. Deps installed into
octopus-agent/.venv via `uv pip install pyautogui pillow mss`. Needs macOS Screen Recording
(capture) + Accessibility (input) granted to the controlling app. Run:
`octopus-agent/.venv/bin/python octopus-agent/scripts/pc_remote_server.py`.
Not yet wired into the runtime's dashboard/coordinator — it's a standalone driver for now.

**H.264 upgrade (commit 4c7b3dc, VERIFIED 2026-06-13):** remote desktop now streams H.264
instead of JPEG. 母体 driver uses hardware `h264_videotoolbox` via PyAV (Annex-B, 1280×720
@15fps, keyframe ~1s; static P-frames ~112 bytes vs ~44KB JPEG). Phone: H264Decoder.kt
(MediaCodec video/avc → SurfaceView, SPS/PPS→csd from first keyframe). Extra deps in
octopus-agent/.venv: `av` (PyAV) — numpy NOT needed (use VideoFrame.from_image).
GOTCHA: `adb screencap` shows the SurfaceView as BLACK (hardware overlay not captured) — it's
NOT a decode failure; verify with `adb screenrecord` (captures the compositor) + extract a
frame. Frame protocol type 0x01=H264 / 0x02=JPEG; flags bit0=keyframe.

**WebRTC upgrade (母体 side DONE + verified 2026-06-13, octopus-agent commit 40459ab):**
For true cross-NAT / lower-latency. ws_server got `on_custom` hook (routes webrtc/* signaling)
+ `send_json`. `octopus-agent/scripts/pc_remote_webrtc.py` = aiortc peer (screen VideoStreamTrack
+ 'input' DataChannel → pyautogui, STUN hole-punch, non-trickle ICE). Signaling rides the
tentacle WS: phone→webrtc/request → 母体→webrtc/offer{sdp} → phone→webrtc/answer{sdp}; media+
input then go WebRTC P2P. Verified end-to-end in Python (a phone-sim got 15 video frames +
input round-trip). Deps in .venv: `uv pip install aiortc av pyautogui pillow mss`.
**BLOCKER for the PHONE client:** a native `org.webrtc` Android SDK CANNOT be added — GeckoView
(the in-app Firefox engine) already bundles `org.webrtc.*`, so every class collides
(checkDebugDuplicateClasses fails). The phone WebRTC client is done via a **WebView/JS RTCPeerConnection** (OS WebView Chromium
WebRTC; no native dep, no conflict) — octopus-mobile commit 5065676: assets/pc_remote.html
(JS peer: recv video→<video>, touch→datachannel) + PcRemoteWebrtcActivity (WebView + JS↔WS
signaling bridge). Settings → 🖥 远程桌面 (WebRTC).
**VERIFIED ON THE EMULATOR** (surprisingly — ICE found a working candidate pair, didn't need
TURN): WS offer→answer, connection: connected, live Mac desktop rendered in the WebView
<video> (screencap CAN capture WebView video, unlike SurfaceView), tap applied via datachannel.
So the full WebRTC remote desktop (母体 aiortc + phone WebView) works end to end.

STUN (both ends list multiple, parallel-query = degrade/switch; commits octopus-mobile f14571e,
octopus-agent 6710632): tested reachable from this network = stun.cloudflare.com:3478,
stun.chat.bilibili.com:3478 (CN), stun.l.google.com:19302, stun.nextcloud.com:3478. NOT
reachable = stun.miwifi.com / stun.qq.com (timeout — don't list dead ones, they slow ICE
gathering). Phone has a 15s connect-timeout + 'failed' → auto-retry (5x backoff). For
guaranteed cross-NAT (symmetric NAT) add a TURN server (coturn) to iceServers on both ends —
still the one missing piece; STUN-only fails on symmetric NAT.

Related: [[mimo-vision-model]] (the LLM/vision config used when the phone is the brain).
