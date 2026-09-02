---
name: mimo-vision-model
description: "Xiaomi MiMo config for octopus-mobile — which model name does vision, and the gateway quirk"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 27adccef-faf0-404c-bc4e-e6905ab458c1
---

The user's Xiaomi MiMo (小米 mimo) API config lives in the sibling project
`octopus-agent/data/custom_models.json`, entry `mimo2.5`:
- base_url: `https://token-plan-cn.xiaomimimo.com/v1` (OpenAI-compatible)
- api_key: `tp-…` (51 chars) — keep on-device MMKV / out of git; never echo in full
- available models (from GET /models): mimo-v2.5, mimo-v2.5-pro, mimo-v2-omni, +asr/tts variants

**Gateway quirk (verified on-device 2026-06-13):** on this `token-plan-cn` gateway,
`mimo-v2.5-pro` is **text-only** — sending image_url returns HTTP 404
`"No endpoints found that support image input"`. **`mimo-v2.5`** (non-pro) **accepts images.**

So in octopus-mobile configure:
- **Main agent model = `mimo-v2.5-pro`** — confirmed it emits real OpenAI function/tool calls
  (LangChain4j tool path works; agent did open_app + anchored taps end-to-end).
- **Vision model (look_at_screen) = `mimo-v2.5`** — set it in the Vision section of model
  config; leave Vision API Key / Base URL empty so they inherit the main config.

mimo-v2.5 is a **reasoning model** (fills `reasoning_content` before `content`); needs a
large enough `max_tokens` (2048+) or `content` comes back empty. octopus-mobile handles this
(see commit 3a6e4b4: VisionAnalyzer max_tokens=2048 + reasoning_content fallback).

Security: per [[octopus-mobile-secrets]], the MiMo key, like the DeepSeek key, stays in
on-device MMKV only. I do not type API keys into input fields myself (user enters them).
