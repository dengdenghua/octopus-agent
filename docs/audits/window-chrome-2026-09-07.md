# 跨平台窗口标题栏适配

## 实现

窗口按钮由桌面系统负责，页面根据 Electron preload 提供的平台和当前窗口能力预留空间。

| 环境 | 窗口按钮 | 页面标题栏空间 |
| --- | --- | --- |
| macOS 主窗口 | 左上角原生红黄绿按钮 | 36px，全屏时为 0 |
| Windows 主窗口 | 右上角原生最小化、最大化、关闭 | 使用原生 overlay 高度，默认 36px；全屏时为 0 |
| Linux | 由桌面环境绘制系统窗口边框 | 0，避免重复标题栏 |
| 独立媒体等辅助窗口 | 系统自带标题栏 | 0，避免重复标题栏 |
| 普通网页 | 外层浏览器负责窗口按钮 | 0；返回桌面和全屏属于应用导航 |

主窗口通过 `--octopus-titlebar-overlay` 告知 preload 需要预留内容区域，辅助窗口不设置此参数。平台判断优先采用桌面壳的 `process.platform`。普通浏览器的 UA 仅用于网页快捷键等展示。

工作区侧栏、内容容器、浏览器和媒体页使用统一标题栏策略。修复侧栏折叠后的 macOS 按钮避让、工作区重复增加顶部留白、Linux 和独立窗口重复标题栏的问题。移除浏览器页重复的 Windows 标题栏主题同步，统一由全局标题栏管理。

## 验证

- 5 个相关测试文件，51 项测试通过：平台策略、辅助窗口、全屏事件、导航控件、侧栏和浏览器路由契约。
- TypeScript、修改文件 ESLint、Electron main/preload 语法检查和主前端生产构建。
- 在 `http://localhost:3310` 实际检查网页：侧栏折叠宽度 45px、展开宽度 210px，内容起点与侧栏宽度一致，没有横向溢出；浏览器页可切换并返回对话页。
- 网页内没有伪造的原生窗口按钮或标题栏。

原生 Windows、macOS、Linux 窗口尚未做各系统实机交互验收。主进程和 preload 的改动需要重启 Echo 桌面客户端生效；仅刷新普通网页不会出现原生窗口控件。

参考：Electron [Custom Title Bar](https://www.electronjs.org/docs/latest/tutorial/custom-title-bar) 和 [Custom Window Interactions](https://www.electronjs.org/docs/latest/tutorial/custom-window-interactions)。
