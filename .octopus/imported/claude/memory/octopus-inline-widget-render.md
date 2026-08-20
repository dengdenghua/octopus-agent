---
name: octopus-inline-widget-render
description: 把 Claude 的 show_widget(内联可交互组件渲染)移植进 octopus 聊天;这是对照"值得移植清单"后唯一真缺的能力
metadata:
  node_type: memory
  type: project
  originSessionId: ff25d56e-cd25-4c88-9ed5-a162bd9c628b
---

**结论(2026-06-28)**:把 Claude Code "值得移植到 octopus 的能力清单"逐条对照后,octopus **几乎全有**——docx/pdf/pptx/xlsx 文档处理、code-quality/code-vuln/web-security 审计、deep-research、skill-creator/plugin-creator、mcp-tools/mcporter、完成前验证、chart-gen/data-viz、explorer/reviewer/researcher 委派角色都在。**唯一真缺**=内联**可交互**(JS)组件渲染(Claude 的 `show_widget`)。已补。

**已建(全在 frontend + 一个 SKILL.md,均测试绿,未提交——前端被并发会话搅动)**:
- `frontend/src/components/workspace/messages/widget-frame.tsx`:`<WidgetFrame code/>` = 沙箱 iframe。**安全核心**:`sandbox="allow-scripts"` **单独一项**(=唯一 null 源,脚本能跑但读不到 app DOM/cookie/同源请求)。**绝不能加 `allow-same-origin`**(与 allow-scripts 同时=逃逸进 app 源)。`srcDoc` 注入代码 + 透明背景/系统字体 + `postMessage({__octopusWidget,height})` 自适应高度(parent 按 frameId 校验)。
- `frontend/src/components/workspace/messages/markdown-content.tsx`:`pre` override 加分支——fenced 语言 `widget`/`html-widget`/`octopus-widget` → `<WidgetFrame>`(镜像既有 `mermaid`→`MermaidBlock` 分支,line ~141)。**关键机制**:用 fenced 代码块承载,故绕过消息级 DOMPurify(它会剥 `<script>`),改在 iframe 沙箱里渲染。
- `runtime/execution/all_skills/show-widget/SKILL.md`:面向 agent 的"用法说明",教模型可发 ```widget 块。被 `_add_file_backed_skill_catalog()`(all_skills/__init__.py L307,`iterdir` 自动扫)收录;`ALL_SKILL_IDS` 264(+1)。group=market(domain 技能,按 goal 排进 react_context 目录)。

**验证**:`pnpm typecheck` 净、eslint 两文件净、catalog 导入净、`markdown-content.test.tsx` 4 绿(含 2 个 widget 断言:sandbox 恰为 allow-scripts、srcdoc 含代码且**不**含 allow-same-origin)。聊天面被 ProtectedRoute 挡,浏览器实拍要登录,故以单测为准。

**未提交**:同 [[octopus-tool-migration]] 的处境——前端文件被并发会话搅动,等其 WIP 落定再提。安全约束见 [[octopus-agent-integration-debt-audit]]。
