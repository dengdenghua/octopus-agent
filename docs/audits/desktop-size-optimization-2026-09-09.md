# 桌面包体积优化

日期：2026-09-09。

Windows x64 基准为本机通过 electron-builder 26.15.3 生成的未签名 `win-unpacked`：1,318.52 MiB。两个官方执行引擎、冻结 Python 后端和全部用户可见功能均保留。

本轮修改 `packaging/desktop/build.yml`：

- renderer 依赖已由 Vite 写入 `dist`，Electron 主进程只直接使用 Node/Electron 内置模块；打包时排除重复的 `node_modules`。`app.asar` 从 198.74 MiB 降至 52.61 MiB，减少 146.13 MiB。
- 桌面种子角色继续携带头像和 front/side/back 等运行视图，排除不会被角色图片接口提供的 turnaround、portrait、`originals` 及 padding/upscale 生成中间图。角色资源从 105.67 MiB 降至 60.29 MiB，减少 45.38 MiB。
- Chromium 语言资源与前端正式支持的 `en-US`、`zh-CN`、`ja-JP`、`ko-KR` 对齐，只保留 `en-US.pak`、`zh-CN.pak`、`ja.pak`、`ko.pak`。55 个语言包收敛为 4 个，减少 41.79 MiB。
- electron-builder 压缩级别设为 `maximum`。

优化后的实际 `win-unpacked` 为 1,085.22 MiB，比基准减少 233.30 MiB，即 17.69%。使用相同内容生成的未签名 NSIS 安装器为 440.22 MiB（461.60 MB）。安装器只是本地体积与构建验收；正式发布物仍须经过 Windows 发布作业的 Authenticode 签名。

验证包含：electron-builder 真实 Windows 解包与 NSIS 构建、`app.asar` 不含 `node_modules`、角色包不含已排除的生成源图、四个 Electron 语言包清单、Codex 0.149.0 与 OpenCode 1.18.29 版本、OpenCode bundle 完整性、首次启动资源物化，以及冻结后端 `/readyz`。打包配置测试同时固定上述过滤与压缩设置。

剩余主要体积来自 Codex 376.19 MiB、Electron 外壳约 280 MiB、OpenCode 171.31 MiB 和冻结后端 140.58 MiB。继续显著缩减需要拆分可选引擎或按桌面功能白名单重做后端冻结清单，会改变离线能力或扩大回归范围，本轮没有采用。
