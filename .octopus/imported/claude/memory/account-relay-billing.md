---
name: account-relay-billing
description: "octo 账号/积分中转网关 — api.octoapk.com 实测通,MiMo+Agnes 上游、计费公式、无限额度邮箱、App 路由"
metadata: 
  node_type: memory
  type: project
  originSessionId: 29f83dca-25be-402b-991b-b9b20cd54f03
---

octopus 的**付费积分体系 + LLM 中转网关**(server/app.py，FastAPI，部署在 **https://api.octoapk.com**):

- **App 路由**:`account/LlmRouting.kt` 决定本回合用哪个模型。默认走**平台中转**(登录即有 token、扣积分);会员且显式选 BYO 且积分耗尽才用自己的 key。`AccountConfig.baseUrl` 默认 `https://api.octoapk.com`,App 调 `…/v1/chat/completions`,`apiKey=账户 token`,默认 `platformModel=mimo-v2.5`。
- **入口必须走 LlmRouting**:`ChatAgentBridge`(浏览器「问 AI/执行」+ 对话页)原来只看 BYO key(`KVUtils.getLlmApiKey`),导致付费用户被错误要求「先配置模型」。已于 2026-06-14 改为 `isConfigured()/buildConfig()` 都走 `LlmRouting.effective()`(与 `AppViewModel.getAgentConfig()` 一致)。对话页那张 `SetupGuideCard`(`ChatScreen.kt:131/381`)由同一个 `isConfigured()` 驱动。结论:**只要登录就不再提示配置模型**(relayConfigured 默认恒 true,只差 isLoggedIn)。
- **中转实测通过(2026-06-14)**:`mimo-v2.5` 与 `agnes-2.0-flash` 两个上游都 200 出字、流式 SSE 正常。说明线上 env `MIMO_API_KEY/MIMO_BASE_URL`、`AGNES_*` 都配好了。模型目录 `/v1/models` 公开(agnes-2.0-flash / mimo-v2.5 / mimo-v2.5-pro)。注意 [[mimo-vision-model]]:`mimo-v2.5` 可用(支持视觉),`mimo-v2.5-pro` 上游会 404。
- **计费**:`CREDITS_PER_1K_TOKENS`(默认1)×模型 `multiplier`(mimo-v2.5=0.5、pro=1.0、agnes=0.5)。中转**预扣**(按 prompt 估算+max_tokens 的 worst-case 原子扣,防并发超支)→ 上游返回后 `_reconcile_usage` 按真实 usage **多退少补**;上游报错/断开全额退。短调用约 1 分/次。`MAX_OUTPUT_TOKENS` 默认 8192 会压请求里更大的 max_tokens。
- **管理员/大额账号**:不走「免扣」(2026-06-14 一度加过 `UNLIMITED_EMAILS` 免扣,**已按需求回退** —— 管理员账号也要正常扣分)。要给某账号大额积分,用管理后台改余额即可(见下),不改代码。`dengdenghua@dangbei.com` = `u_f1ecddf33eaf16f9`,目标余额 10 万。
- **管理后台改积分**:`POST /admin/api/users/{uid}/credits` body `{"delta": <相对增减>, "reason": "..."}`(相对值,|delta|≤1000万,负向被 MAX(0,…) 截断),Header `X-Admin-Token: <ADMIN_TOKEN>`。线上 `api.octoapk.com` 后台**已启用**(无 token 返回 401 而非 503;`/admin` 页 200)。ADMIN_TOKEN 不在本地、需找运维要,或直接进 `/admin` 网页控制台操作。
- **登录拿 token 测试**:短信关(`SMS_PROVIDER=mock`→403);邮箱是真 SMTP(`/auth/email/send` 返 200 不回 devCode)。注册赠 `SIGNUP_BONUS=100`。本地联调要 mock 验证码须 `ALLOW_MOCK_AUTH=1`。
- **构建/部署**:`cp .env.example .env` 填 env → `uvicorn app:app`。管理后台 `/admin` 需 `ADMIN_TOKEN`(与「无限额度邮箱」是两套东西:后台是口令鉴权改积分/封号,无限额度是按 email 免扣)。
