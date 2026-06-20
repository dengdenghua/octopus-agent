# octopus-agent · Web UI

Vite + React 19 + TypeScript + Tailwind。支持浏览器开发与 Electron 打包，生产产物由 FastAPI 挂载到 `/ui/`。

## 开发

```bash
corepack enable
make frontend-install   # 或 cd frontend && pnpm install --frozen-lockfile
make frontend-dev       # vite dev server · localhost:3000
# 另开终端起后端：
#   octopus-agent serve --port 8000
# /api/* 和 /v1/* 自动代理到 8000
```

## 生产 build

```bash
make frontend-build
# 产出 frontend/dist/
# 后端 create_app 会自动探测并挂到 /ui/
# 或设环境变量 OCTOPUS_WEBUI_DIST 指定路径
```

## Docker

`Dockerfile` 是三阶段 · 自动：

1. `node:20-alpine` build frontend → /webui/dist
2. `python:3.12-slim` pip install
3. runtime · COPY --from=webui-builder → /app/webui
   · 设 `OCTOPUS_WEBUI_DIST=/app/webui` · WebUI 自动挂载

## 路由

所有业务页面在 `/workspace` layout 下，由 `src/router.tsx` 统一注册。
当前产品入口已经收敛到 realtime-first workspace：

- `/workspace` 默认进入 `/workspace/realtime/new`。
- `/workspace/realtime/:threadId` 是单人对话 / 任务执行主界面，使用 `/api/realtime` WebSocket JSON-RPC item protocol。
- `/workspace/chats/:threadId` 保留为旧链接兼容入口，但渲染同一个 `ChatPage`，不再代表独立 SSE chat transport。
- `/workspace/code*` 保留为旧链接兼容入口，并重定向到 realtime；coding 是 thread/runtime 内的工作模式，不是独立页面产品面。
- `/workspace/team*` 是团队模式，独立于单人 realtime 对话。

| 页面                  | 路径                            | 后端 API                                              |
| --------------------- | ------------------------------- | ----------------------------------------------------- |
| Landing               | `/`                             | —                                                     |
| Login / Register      | `/login`, `/register`           | `/api/auth/*`                                         |
| Realtime conversation | `/workspace/realtime/:threadId` | `/api/realtime` WebSocket                             |
| Legacy chat link      | `/workspace/chats/:threadId`    | 同 `Realtime conversation`                            |
| Legacy code link      | `/workspace/code*`              | 重定向到 `/workspace/realtime/*`                      |
| Team                  | `/workspace/team*`              | `/api/teams/*`                                        |
| Agents                | `/workspace/agents`             | `/api/agents`                                         |
| Skills                | `/workspace/skills`             | `/api/skills`                                         |
| Channels              | `/workspace/channels`           | `/api/channels`                                       |
| MCP                   | `/workspace/mcp`                | `/api/mcp/*`                                          |
| Browser               | `/workspace/browser`            | `/api/browser/*`                                      |
| Computer              | `/workspace/computer`           | `/api/computer/*`                                     |
| Observability         | `/workspace/observability`      | `/api/stream` `/api/journal` `/api/kg` `/api/reflect` |
| Workflows             | `/workspace/workflows`          | `/api/workflows/*`                                    |
| Intelligence          | `/workspace/intelligence`       | `/api/intel/*`                                        |
| Swarm                 | `/workspace/swarm`              | `/api/swarm/*`                                        |
| Knowledge             | `/workspace/knowledge`          | `/api/kg/*`                                           |
| Evolution             | `/workspace/evolution`          | `/api/evolution/*`                                    |
| Reflex                | `/workspace/reflex`             | `/api/reflex/*`                                       |
| Architecture          | `/workspace/architecture`       | — (纯前端可视化)                                      |
| Realtime dev index    | `/realtime`                     | `/api/realtime` WebSocket                             |
| Desktop               | `/desktop`                      | — (Electron 专用)                                     |

## 设计

- **Dark only**（短期）· 配色 ink（深蓝灰）+ cephalo（紫）+ sucker（cyan）
- **Radix 原语 + Tailwind 组合**（无 MUI / antd）· 轻量 headless 基础 + 自定义样式
- **TypeScript 严格**（`strict: true`）
- **后端契约** → `src/core/api/openapi-types.ts`（openapi-typescript 自动生成）· 后端改请同步 `npm run generate-types`

## Size 预算

使用 `vite build --reportCompressedSize` 查看最新产物体积。
构建配置中 `chunkSizeWarningLimit: 1400 KB`，超出会告警。
主要 vendor chunk 按 react / radix / codemirror / tanstack-query 拆分。
