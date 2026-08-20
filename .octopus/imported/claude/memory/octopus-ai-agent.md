---
name: octopus-ai-agent
description: octopus 通用对话 Agent 与 LLM 配置（DeepSeek）现状
metadata: 
  node_type: memory
  type: project
  originSessionId: 7da12040-c4fa-41f4-a971-66846e188e43
---

octopus 企业版有一个 Codex 风格的通用对话 Agent，2026-06-11 接入并实测可用。

**架构**：`backend/app/services/chat_agent.py` 是 function-calling Agent 循环（最多 8 轮），注册了 10 个工具（项目概况/任务列表/团队 等查询 + 任务增删改/里程碑/风险 等写入）。所有工具限定在已通过租户校验的当前项目内；写操作走 WebSocket 广播，前端表格/甘特/线轴/泳道/看板自动同步。路由 `POST /api/v1/projects/{id}/agent/chat`（认证+租户+限流 20/min）。前端入口是任意页面右下角悬浮按钮 → 侧滑抽屉 `AgentFreeChat.tsx`，回复用零依赖的 `MiniMarkdown.tsx` 渲染（项目无 markdown 库且离线，勿引入 react-markdown）。

**LLM 配置走应用内设置**（不是 .env）：管理员在「项目设置→集成配置」保存，经 `runtime_settings.save_settings` 加密入库 + 即时 setattr 到全局 settings。当前已配 **DeepSeek**（base `https://api.deepseek.com/v1`，model `deepseek-chat`），function calling 实测正常。

**Why/坑**：`llm_client` 是模块级单例，原来 `__init__` 把 `settings.LLM_API_KEY` 拷成实例属性 → 应用内配置永不生效、必须重启。已改成 property 动态读 settings。**新增任何读 settings 的单例服务都要注意这个模式**——用 property 或每次重新读，别在 __init__ 缓存可运行时变更的配置。

**How to apply**：换 LLM 供应商只需在设置页改三项（KEY/BASE_URL/MODEL），无需重启；要求供应商支持 OpenAI 兼容的 tools/function calling，否则对话 Agent 的写操作不工作。相关 [[octopus-project-state]] [[octopus-dev-toolchain]]
