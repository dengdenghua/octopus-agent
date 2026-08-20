---
name: octopus-agent-frontend-ux-streaming-audit
description: 2026-07-05 前端UX+流式47代理审计:38确证/2驳回;协议契约3根性问题+适配层每帧全量重建+Kimi移植轮半成品清单
metadata: 
  node_type: memory
  type: project
  originSessionId: a6d99ef5-13f4-4c7a-86a7-593e240314d2
---

2026-07-05 对 frontend 流式链路与 UX 的 6 维度审计(47 代理,每条 finding 对抗核查:38 确证/2 驳回)。当时工作区有未提交的 Kimi replay UX 移植改动(chat-page-layout 三栏化/workbench -564行重构/消息回执/子任务网格),审计以工作区状态为准。

**流式底座结论**:client.ts/reducer.ts/use-realtime-thread.ts 三层是全仓最扎实的代码(RAF合批+coalesce、outbox断线清空防重放、心跳假活检测、resume双守卫,均有针对性测试)——别再重复审这层的"常见嫌疑"。已被驳回的误报:双车道RAF重排(有四层防护:事件连接绑定+resume replace 兜底等)、验证回执status短路。

**根性问题(修复时按这个序)**:
1. rAF 后台化冻结:BATCHED_METHODS 全押 requestAnimationFrame,后台 tab 不触发→buffer 无限积压+turn/interrupted 越过缓冲中 item/started→回前台永久转圈(client.ts:293;修法 visibilitychange 同步 flush 或 hidden 时走 setTimeout)
2. turn/start RPC 后端挂到回合结束才响应(realtime_gateway.py:594-651 "run a turn to completion"):回合中任何断线→failPending 误报"发送失败"+草稿回填诱导重发+sendError 横幅永不清除(use-thread-stream-realtime.ts:920);修法=以 turn/started 通知为投递成功锚点,或后端拆 ack+完成两段
3. resume 复活旧 turn 且后端 CancelledError 不产生任何终结事件(不写 log 不发通知,悬挂 turn 靠下次 resume 收尸)→转圈永不结束(use-realtime-thread.ts:231 + realtime_turn_lifecycle.py:595)
4. 适配层 conversationToAgentThreadState "fresh on every call"(realtime-adapter.ts:85)→流式每帧全量新建 message 对象→MemoizedGroup/MessageListItem 全失效,每 token 整列表重渲(幸 MarkdownContent 内层按 content 浅比较吸收了 AST 重解析);同族:requiresReportDeliverable 每帧 stringify 全部事件(page.tsx:1982)、workbench 快照每帧全量 stableStringify、TurnLocator 每帧拆装监听。**修适配层身份稳定性是一次性根治,别去每处包 useMemo(上游 [state] 每帧新身份,包了无效)**

**Kimi 移植轮半成品(未提交,提交前须修)**:验证清单/做同款按钮永不渲染(扫 assistant 组但该组不含 tool/human 消息,message-output-summary.tsx:294,零测试覆盖);失败回执双重抑制→react_completed success=False 类错误完全不可见(message-list.tsx:589 全历史some vs :1190 仅最新组);secondaryPanel 拖拽方向符号反了(chat-page-layout.tsx:197,主sidebar是 startX-clientX 它抄成 clientX-startX,已亲自复核);resultPreviewUrl 只接 emptyShell 分支(panel.tsx:964);子任务百分比是假进度 running 恒45%(真实源 parallel-agents SSE 只喂 swarm 未接消息流);窄屏 secondaryPanel width:100% 挤压聊天列到 0 且自动打开不判 isMobile;focusedAgentId 聚焦意图建模成持久 prop 被反复重放回跳(panel.tsx:394);button 嵌套 button(parallel-subtasks-grid.tsx:160);hover 预览 8px 死区+键盘不可达;MacWindowControls 无平台检测(Windows Electron 双窗口控件);~220 行死 fallback+AgentFilesPage+debug-page.js/inspect-header.js 调试残留;ja-JP「同款を作る」中文直搬。

后端契约另有:interrupt 标志 per-connection(第二标签页停不掉别人连接的 turn);turn/completed 的 completedAt 恒 null(live 路径从不赋值)→工具时长退化;turn/started 后 driver try 前异常→turn 永久 inProgress。

**2026-07-06 已按依赖序分 5 批提交(main,未 push)**:634822030 i18n → 535044168 gateway(跨连接interrupt/扇出/completedAt/取消闭环) → c9e36e9d3 realtime核心(保序/后台flush/投递锚点/身份缓存) → 4e95d69a4 messages(回执/进度/网格a11y) → 9fe871618 workspace壳层(secondaryPanel/焦点nonce/死码清扫/mode-selector a11y)。批序保证中间 commit 依赖完整(friendlyRoleName/events 均已在 HEAD 验证)。

**2026-07-05 第二轮(清遗留)也已落地**:8 代理+门禁全绿+复审;跨连接 interrupt=SharedTurnInterrupts 网关级注册表+终结通知扇出给 resume 过同 thread 的兄弟连接;panel ~224 行死 fallback/AgentFilesPage/recentFileEvents 全删(artifacts/plan tab 重映射到 agent);焦点事件加 view("summary"|"screen")+nonce(复审抓到 consume-once 按 agentId 判重会吞同 agent 第二次意图,已用 nonce 修);isReportLike 映射期预计算(core/threads/report-deliverable.ts,与 page 的 REPORT_DELIVERABLE_PATTERN 副本需保持同步);client 保序不变式(非批派发前必先 flush deltaBuffer,双车道重排彻底消除);mode-selector a11y 返工过一次(第一版 Tab 一律关弹层把 listbox 外的 audit 强度切换修成键盘不可达——WCAG 倒退,已改为弹层内 focusable 遍历、越界才关);ja/ko sidebar+agentWorkbenchPages ~160 key 补译。仍遗留:agentWorkbenchPanel 段 ja/ko 英文、CancelledError 路径终结通知不扇出、subtask 真实进度 SSE 接入(双写热点需设计)、做同款 URL 长度。

**2026-07-05 修复轮已落地(未提交)**:8 修复代理(文件所有权分区并行)+门禁全绿(tsc/1073 vitest/eslint/848 pytest/ruff)+8 对抗复审无 critical,我再手补 12 处 minor。已修:上面 4 根性中 1/2/3(rAF hidden 走 setTimeout+visibilitychange 同步 flush、turn/started FIFO 投递锚点、CancelledError 终结事件+completedAt+pre-driver FAILED 兜底)+适配层 WeakMap<Turn/Item> 身份稳定+MemoizedGroup 逐元素比较;半成品清单全修(拖拽方向/验证清单 turnMessages 切片/回执谓词统一/resultPreviewUrl 主路径+previewBlocks 同族劫持/假进度→null/嵌套 button 重构/hover 死区+focus-within/秒屏抽屉/宽度视口 clamp/MacWindowControls 全 Electron 隐藏)。**遗留(有意不修)**:per-connection interrupt(需设计)、requiresReportDeliverable 最坏路径(需映射层预计算 isReportLike)、panel ~220 行死 fallback+AgentFilesPage(降 diff 风险)、mode-selector 弹层键盘导航、ja/ko sidebar 成批英文占位、focus-within 钉住浮层怪癖、隐藏 tab setTimeout 节流有界竞态(彻底修需 reducer pending 暂存)。
