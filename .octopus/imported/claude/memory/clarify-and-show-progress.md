---
name: clarify-and-show-progress
description: User wants clarifying questions BEFORE building + visible progress/streaming — not silent dive-in-and-finish
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 900aad5a-9593-4b2a-ac1a-12cea9e9d8da
---

用户明确要求:**不确定的需求要先反问确认,再动手;过程要能看见(流式/进度),别闷头一次性干完才给结果。**

**Why:** 2026-07-04 用户对 App 的「编程/建应用(generate_app)」功能提的:①「编程没有流式,看不到过程」②「也没有互动询问用户一些不确定的需求,就直接开始干了,应该有提问用户明确需求」。这既是对 App 功能的要求,也反映用户本人的偏好——他要参与感和可控,不喜欢黑箱。

**How to apply:**
- 面对**范围/取向不明确**的构建任务,先用 AskUserQuestion 问 2-3 个关键点再写代码,不要自行拍板一头扎进去(这条对我自己也适用——本会话前面几次都是直接开干)。需求清晰或纯机械改动则照常直接做。
- 涉及耗时的生成/执行,优先给**可见进度**(阶段提示/流式 token/实时预览),而不是只在结束时给结论。
- 对应到 App:generate_app 应加「先澄清需求(模糊才反问)+ 生成过程流式/分步可见」。工具当前是多次阻塞 callLlm(plan→code→repair→VLM),无流式;BaseTool.execute 无进度回调,ChatAgentBridge 有 streaming 通道可借鉴。见 [[tool-system-internals]]、[[octopus-code-exec-feature]]。
