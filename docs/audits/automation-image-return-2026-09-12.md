# 自动化截图回传 — 2026-09-12

已补齐 Echo 截图工具到外部引擎的图片传输。此前工具结果在原生执行出口被序列化、裁剪成文本，Codex 动态工具和 OpenCode MCP 都不能稳定获得截图像素。

## 实现

- `screen_capture`、`browser_screenshot`、`live_browser_screenshot` 成功后，在文本裁剪前提取图片；工具执行仍经过原有权限、审批与审计边界。
- Codex 使用 `inputImage/imageUrl`；OpenCode MCP 使用 `ImageContent`。小图片保持原始字节；大图片压缩、缩放到传输上限以内，同时返回原始尺寸和传输尺寸。区域截图的偏移、页面视口和 DPI 坐标仍需由调用方正确处理。
- 原始图片上限 20 MiB、4000 万像素，单张 data URL 不超过 512,000 字符。媒体超限明确拒绝，不进行会破坏编码的字符串截断。工具结果缓存增加约 8 Mi 字符上限，仍保留原有条目数量上限。
- 路径型截图只从当前工作区读取，并额外检查当前任务的读取权限；不根据返回内容扩大文件范围，不下载远程图片 URL。图片不能附加时返回 `visual_observation.attached=false`，不自动重试截图或先前动作。
- 普通原生工具调用保持原有文本接口；只有显式请求图片结果的外部工具桥启用图片提取。

## 验证

146 项回归通过，覆盖图片解码、压缩尺寸、小图原字节保留、越界路径、任务读取拒绝、损坏图片、失败工具不附图、最近重复请求不重复截图、Codex JSONL、OpenCode 真实 MCP HTTP、原生执行与协议兼容。

真实本地 Chrome 使用隔离测试页面，通过实际 ToolExecutor 与浏览器处理器完成截图、点击、再次截图；回传图片由红色背景变为蓝色背景，像素差异断言通过。没有访问外部站点或用户浏览器会话。

扩大回归发现 App Server 客户端三个测试使用 `/workspace` 等 Unix 绝对路径；已改用跨平台临时目录，保留原协议和权限断言。Ruff、仓库约束及差异空白检查通过。

## 后续：真实 Codex 视觉操作验证

新增 `tests/test_codex_vision_live.py`，通过环境变量 `OCTOPUS_RUN_CODEX_VISION_LIVE=1` 显式启用；普通测试默认跳过，不消耗线上模型额度。使用本机已认证的官方 Codex App Server，经过实际 `CodexExecutionSession`、动态工具 broker 和原生 `ToolExecutor` 回传图片。

测试页面在隔离的无头 Chrome 中创建，不使用用户浏览器会话。6 个按钮中 START 的位置每次随机；点击正确按钮后，画布才显示随机 8 位验证码。模型仅获得截图工具和坐标点击工具；提示词与工具文本均不包含按钮位置或验证码，也不提供 DOM。测试断言模型完成点击、成功后重新截图并正确读出验证码，同时检查没有命令执行、文件改动、MCP 或网页搜索工具调用。点击处理器只绑定该测试页面，坐标、动作次数和总时间均有上限。

2026-09-12 实测：`gpt-5.6-sol`，**1 项通过，55.71 秒**；4 次截图、1 次点击，成功画面验证码匹配。模型点击坐标 `(400, 360)`；App Server 观测到的 item 类型为 `agentMessage`、`dynamicToolCall`、`reasoning`、`userMessage`。模型取了 3 张初始截图后才点击，因此这次通过不能视为效率已优化或稳定成功率证明。

PowerShell 运行方式：

```powershell
$env:OCTOPUS_RUN_CODEX_VISION_LIVE = '1'
.venv/Scripts/python.exe -m pytest tests/test_codex_vision_live.py -q -s
```

该验证包含真实模型与真实浏览器，但使用了只服务测试页面的坐标适配器；没有验证生产浏览器会话选择、Electron/Relay 路由、DPI 转换、页面导航恢复、真实桌面跨应用操作或与官方 Codex 桌面端的成功率对测，也未重启正在运行的 Echo 服务。以上证据证明图片传输以及受控浏览器视觉操作闭环，不代表完整自动化能力已追平官方。
