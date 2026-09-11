# 悬浮输入横条 · 2026-09-08

依据用户纠正，本版本取代此前默认整块悬浮面板的设计。

- 默认打开为 640 × 64px 横条；窄屏为容器宽度减 24px，仍为 64px 高。
- 底部始终只有一个输入区；“对话”向上展开记录，再次点击只隐藏记录，不隐藏输入。
- 桌面展开高度默认 520px；窄屏按容器约束，最高 640px。
- 展开/收起共享同一会话与草稿；回复开始、出现错误或待确认操作时展开记录，避免重要状态藏在横条里。
- 保留拖动、可选右侧停靠和整体收起入口。
- 展开的消息文本不再按 1500 字截断。

验证：

- 9 项相关测试通过，覆盖横条默认高度、展开/收起、草稿及组件实例保留、拖动、键盘尺寸调整、窄屏以及浏览器布局/状态。
- 类型检查和生产构建通过。
- 浏览器实际测量：桌面展开与收起时，textarea 的 x=661.25、y=660.5、width=405.5、height=24 完全相同，输入框不发生位移。
- 浏览器验证了未发送草稿在展开/收起时保留。
- 390 × 844 视口下，展开面板 x=12、y=192、width=361、height=640，无横向溢出；输入横条收起后留在底部。
- 截图：collapsed.png、expanded.png、mobile-collapsed.png、mobile-expanded.png。
- 测试未向模型发送消息；实际流式回复和系统级独立小窗没有在本轮实机验证。
# Updated to the supplied Codex screenshot

The latest implementation supersedes the earlier right-aligned 640 × 64 layout below: centered 736px composer, 48px pill input, inset 38px recent-message strip with 8px overlap, conversation expanding upward. Latest evidence files start with `centered-`; `centered-comparison.png` shows the supplied reference above the final implementation at 1:1 pixel density. See the latest section of the root `design-qa.md` for validation.
