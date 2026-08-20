---
name: web-control-console
description: Browser-based remote control of the phone via ConfigServer (port 9527) + the auth token
metadata: 
  node_type: memory
  type: reference
  originSessionId: 27adccef-faf0-404c-bc4e-e6905ab458c1
---

octopus-mobile's ConfigServer (NanoHTTPD, port 9527, bound to the phone's WiFi IP) serves a
LAN web control console — **browser → phone**, scrcpy-web style (commit 82b8bb3):
- Open **`http://<phone-ip>:9527/console?token=<token>`** (cross-net: phone on Tailscale →
  `http://<phone-100.x>:9527/console?token=...`).
- Live screen = MJPEG `/api/screen/stream` in an `<img>`; control = `POST /api/control/input`
  (click=tap, drag=swipe, hold=long_press, wheel=scroll) + back/home/recent/⌫ + text box.
  Page = assets/web/console.html; served public, but every `/api/*` needs the token.
- Control actions (handleControlInput): tap{x,y} / swipe{x1,y1,x2,y2,duration} / long_press /
  key{keyCode} / text{text} / open_app{package} / back / home / recent. **x,y are RAW DEVICE
  pixels** — map via `/api/screen/info` ({width,height}, e.g. 1080×2400).

**Auth token** (`config_server_auth_token` in MMKV, 24-byte base64url = **32 chars**, e.g.
A0g9c_GuhrUZUq32aoJdhHXHL4SMrbKs): generated **lazily on the first authed `/api/*` request** —
a request with NO token short-circuits before generating it, so to force creation hit
`/api/screen/screenshot?token=dummy` once, then read it. Shown in-app (LAN Config / the H5
page's Token field). Accepted as `?token=` or `Authorization: Bearer`.

To reach the emulator's 9527 from the host: `adb forward tcp:9527 tcp:9527`. MMKV token-read
gotcha: values aren't NUL-delimited, so a greedy regex grabs bytes from the next entry — the
real token is exactly 32 base64url chars.

**Split-screen console (commit 2f57b1c):** /console is now two panes — LEFT phone mirror +
control, RIGHT a standalone Agent chat (talk continuously while controlling). Backend:
AgentWebBridge buffers ChatAgentBridge's streaming callbacks into absolute-indexed events;
endpoints POST /api/agent/run {prompt} + GET /api/agent/events?since=N (page polls every 800ms).
GOTCHA fixed: NanoHTTPD parseBody decodes POST bodies as ASCII/Latin-1 → Chinese became '?'.
`readJsonBody` now reads the raw inputStream by Content-Length as UTF-8 (bypassing parseBody);
used by /api/agent/run and /api/control/input. Other POST handlers (channels/llm) still use
parseBody (ASCII-only). The agent's final answer (incl. Finish-tool result) is delivered via
the `done` event and rendered as the reply bubble; the Finish tool step is suppressed.

**Security hardening (commit 39d90da, the audit's 🔴 blockers — now CLOSED):**
- Path traversal fixed: `/api/files/browse` + `/api/files/search` had NO path check and
  `ShizukuShellService.isValidPath` only validates charset (allows `/data/data/...` → reads
  MMKV secrets). Added `isAllowedUserPath()` (only `/sdcard`, no `..`/injection) to ALL file
  endpoints (browse/search/download/upload/delete). Verified: `/data/data`, `/etc`,
  `/sdcard/../` → 403; `/sdcard*` → passes.
- Key echo fixed: GET `/api/llm` + `/api/channels` returned raw secrets → now `maskSecret()`
  (last-4 only). POST already skips masked (`*`) values, so the web Save button won't overwrite
  the real key with the mask (verified round-trip: MMKV key intact).
- Crash races also fixed same commit: H264Decoder.stop() joins worker before codec release;
  DefaultAgentService null-executor guard; ChatAgentBridge shared busy lock (web+app one Agent
  service — concurrent run rejected); PcRemoteWebrtcActivity WebView-missing try-catch.
- STILL OPEN from audit (🟡, not blockers): permission slimming, 母体 driver integration,
  signed release. Cleartext HTTP + token-in-URL left by design (LAN/WS/stream need it).

**i18n DONE (commit fe2bc4f):** app already had EN(default values/)+ZH(values-zh)+JA(values-ja),
~315 strings, but newer UI screens hard-coded Chinese. Extracted ALL user-facing Chinese across
29 files (ui/ + floating/ + Toast/Notification) → 278 new keys (38 reused), now 593/locale.
@Composable→stringResource(); Activity→getString(); plain object/top-level fn (ChatAgentBridge,
ControlTarget.label() "本机"→This device)→ClawApplication.instance.getString(R.string...). Logs,
LLM prompts, and equality-comparison sentinels deliberately NOT translated. strings.xml files are
CRLF + BOM — keep that (append before </resources>, don't let an editor reflow to LF or the diff
explodes). Test a locale on-device: `adb shell cmd locale set-app-locales com.octopus.mobile
--locales en-US` (Android 13+, no reboot); reset with `--locales ""`.
