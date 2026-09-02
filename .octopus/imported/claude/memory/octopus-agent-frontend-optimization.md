---
name: octopus-agent-frontend-optimization
description: "前端\"优化\"审计结论——已很优；真正杠杆是后端 gzip；附已落地改动与雷区"
metadata: 
  node_type: memory
  type: project
  originSessionId: fbf142eb-1b83-47ab-98f1-a323c8d35e01
---

2026-06-28 对 frontend/ 做了一次 6 维度多代理优化审计（73 代理对抗核查，66 候选→58 否决）。

**核心结论：前端在明显轴上已经优化得很好**，别再去做这些（都已实证为已做/假阳性）：
路由全 `lazy()`（router.tsx，~40 路由+33 page chunk）、i18n 已惰性（translations.ts，en 静态/zh-ja-ko `()=>import`）、shiki 语言按需惰性、mermaid 走 shim+lazy import("mermaid-real")、消息列表已 `@tanstack/react-virtual` 虚拟化、流式路径有 `memo`+`useMemo`、lucide 已 tree-shake、巨型组件（agent-operator-panel 等）其实子组件都在模块顶层+有 memo（ARCH 类发现全是假阳性）。

**真正杠杆是后端，不是前端**：自托管路径（FastAPI `StaticFiles`，runtime/platform/ui/webui_static.py）**之前完全没有压缩**，18.8MB 产物裸发。已加 `GzipStaticMiddleware`（runtime/platform/ui/compression.py，内容类型白名单 JS/CSS/HTML/JSON/SVG，**显式跳过 text/event-stream/websocket/range/已编码/非200**，避免缓冲断 SSE），在 app.py:227 `add_middleware`。实测 18.8MB→4.68MB gzip(25%)，首屏 2654KB→695KB。8 个单测在 tests/test_ui_compression.py（纯 ASGI 驱动，验证 SSE 逐块不缓冲）。

**本次已落地（main 未提交，未 commit）**：A 后端 gzip；B 删 frontend/public/images 6 张损坏 jpg(4.55MB，UTF-8-mangled mojibake，被 case-study-section 当背景→生产破图)并换每卡渐变；D 删死代码 `useTask`(tasks/hooks.ts 零调用)、`StorageStatusDot`+`useStorageStatus`(零引用)；F router.tsx 加 idle requestIdleCallback 预取 workspace layout+chat page+预热 shiki js/ts/py。

**放弃的两项**：E「katex CSS 延迟」不可行——katex.min.css 是 **streamdown 依赖**副作用引入且在 eager 链，移不掉，何况 gzip 已压到 3.6KB；C「ai→devDeps」零价值(全 `import type`)且撞上 lockfile churn，撤回。

**生产级别打磨续（2026-06-29，本会话，主 worktree 当时被切到 main）**：基线实证——typecheck **0**、eslint **0 error**（20→2 warning，剩 2 在 knowledge-graph-view，并发在改不碰）、`vite build` 15.6s（codemirror/语言/wasm 都按需 lazy chunk）、vitest **921 全绿**、ErrorBoundary 齐（router+layout+组件级）、无真 debugger/`.only`。**修了 model-settings-page.test 2 个 flaky**：根因=ModelCookbook（近期加）on-mount fetch `/api/cookbook/snapshot` 抢占了测试顺序依赖的 `mockResolvedValueOnce`→custom-models fetch 拿到默认空列表。修法=测试里 `vi.mock` 掉无关的 ModelCookbook（**同类风险**：任何往页面加 on-mount fetch 的组件都会破坏顺序依赖 mock，测试该 stub 无关组件或改 URL-aware mock）。+ 删 18 个死 lucide import（local-skill-directory-panel）+ channels 的 debug `console.log`。**commit `27f3f6a8`（本地 main、未 push、pathspec 只提我 3 文件不碰并发的 staged/脏）**。坑：`debugger:` 在 agent-workbench 是对象 key（UI 标签）非语句，grep 误报别删；`eslint --fix` 不会删 no-unused-vars 的 import（要手删/脚本）。

**雷区**：① pnpm-lock.yaml 有预存漂移（package.json 已删 better-auth/dotenv/embla-carousel-react/hast/zod/@types/gsap 6 个+@types/node 升 ^22，lockfile 没同步）→ `pnpm install --lockfile-only` 会重写~1万行，**别提交**；见 [[octopus-agent-generated-artifact-drift]]。② 本次全程**有并发会话在改本仓**（knowledge-graph-view/i18n locales/runtime suckers/evolution 等 + 反复 pnpm install 让 node_modules/lockfile 漂移、vite 暂时消失）——只用显式 pathspec 操作自己的文件。③ python3 坏了（TRAE 残链），用 .venv/bin/python。
