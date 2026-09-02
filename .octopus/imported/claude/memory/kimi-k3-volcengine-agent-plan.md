---
name: kimi-k3-volcengine-agent-plan
description: "Kimi K3 接入走火山 Agent Plan 专属 base(/api/plan/v3 非 /api/v3),已配进 custom_models.json"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 7515e253-50ff-4836-a231-b704e6f32e06
---

Kimi K3(2026-07-16 发布,月之暗面推理模型,常驻思考+返回 `reasoning_content`)在本机的**唯一可用通路是火山方舟 Agent Plan**(`ark-...` 前缀 key,Medium 包月/AFP 计费)。

**非显然的坑(排查烧了好几轮 401/402/404 才定位):**
- Agent Plan 有**专属 base URL**,跟标准方舟推理端点不是一回事:
  - OpenAI 兼容:`https://ark.cn-beijing.volces.com/api/plan/v3`(我们用这个)
  - Anthropic 兼容:`https://ark.cn-beijing.volces.com/api/plan`
  - ⚠️ **别用 `https://ark.cn-beijing.volces.com/api/v3`**——控制台明确警告"接入会产生额外费用",而且那把 Agent Plan key 在 `/api/v3` 上直接 401(无权)。
- 模型名:钉死 `kimi-k3`,或用 `ark-code-latest`(Auto 智能路由,服务端返回 `model=auto`)。`kimi-k2` 走这个 plan 会 404 UnsupportedModel。
- 该 plan 端点**没有 `/models`**(404),别指望列目录。
- K3 是推理模型:小查询也 ~16s、reasoning 吃 token(`max_tokens` 给小会导致 `content` 空,思考占满)。配了 `omit_sampling_parameters:true` + `timeout:180`。

**已落地**:`data/custom_models.json`(gitignored,含真 key,永不提交)加了 `kimi-k3` 和 `ark-code-latest` 两条,provider=openai。用 `build_fallback_router_from_custom_models(prefer="kimi-k3")` 端到端验证过真出内容。

**实测成本/表现(2026-07-18,行为套件代表子集 6 例 k=1)**:pass@k **5/6(83.3%)**,唯一失败 memory.crosscutting-change(大仓跨切面重命名,fixture_tests 未全绿,非崩溃)。**AFP ≈ 4000+/6 例 ≈ 670/例**,即 Medium 月额度(10万)的 ~4%;全 14 例粗估 1-1.5万 AFP(~10-15%),跑得起。墙钟 42.5 分钟/6 例(K3 推理慢,每例 5-12 分钟)。跑套件注意两点:①`--case` 是 `action="append"` 要**重复传**不是逗号分隔;②`--artifact-dir` **必须在仓库根内**(放 scratchpad 会在末尾聚合写盘时 ValueError,但 checkpoint 已存全部判定,可 `--resume` 补证据不重跑)。coding.concurrent-cache 满分那例=本会话 16MiB WS 帧修复的真端到端验证。

**另两把 kimi key 都废了**:`sk-sPX…`(`api.moonshot.cn`)欠费 429;`sk-kim…`(`api.kimi.com/coding`)会员未激活 402;且 `.cn` 和 `.ai`(K3 官方站 platform.moonshot.ai)是两套独立账号,`.cn` key 打 `.ai` 直接 401。相关见 [[octopus-agent-subagent-model-routing]]。
