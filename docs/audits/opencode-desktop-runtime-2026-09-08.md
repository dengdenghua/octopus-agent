# OpenCode 桌面运行时准备

日期：2026-09-08。

桌面版锁定 OpenCode 1.18.29。`frontend/electron/opencode-runtime-lock.json` 记录官方 GitHub release 页面及 Windows x64、macOS arm64/x64、Linux arm64/x64 五个发布资产的固定 URL、GitHub 公布的 SHA-256、归档格式、唯一成员名和目标可执行格式，不使用浮动版本。许可证来自该版本源码的 `LICENSE`，保存在 `extras/desktop/licenses/opencode-1.18.29/LICENSE`，SHA-256 为 `625f0f619133f89bbbb2abe37369613dfa1885eba1e50d02170deb62bb42cb6b`。

`extras/desktop/prepare-opencode.py` 只在构建阶段运行。下载工作进程有 30 秒网络操作超时，父进程施加 180 秒总期限；Windows 超时时按已创建的确切 PID 结束整个子进程树。脚本限制归档与可执行文件大小，先校验整个官方归档的 SHA-256，再从 ZIP 或 TAR.GZ 中复制唯一的固定普通文件成员，不使用归档提供的目标路径。链接、重复、缺失、超限成员和可执行格式不匹配都会拒绝发布。许可证也按锁文件复验。

生成的 `echo.opencode_bundle.v1` manifest 记录版本、平台、发布资产、归档 SHA-256、签名前文件哈希阶段以及可执行文件和许可证的 SHA-256。manifest 最后写入输出目录；已验证的完整 bundle 会直接复用。准备器和桌面运行时都要求目录只包含可执行文件、许可证和 manifest，不接受额外文件。运行时返回安装资源内的绝对路径；任何缺失或校验失败都明确拒绝 PATH 或在线安装回退。

Windows 和 macOS 的安装构建会在资源复制后签名原生可执行文件，因此运行时检查其平台文件头和其余资源哈希，发布 CI 再验证签名后的发行文件。Linux 可执行文件不会经过该签名变化，运行时继续核对其完整 SHA-256。Windows CI 已把 `resources/opencode/opencode.exe` 纳入 Authenticode 发布证明，三个桌面平台的构建流程都在 electron-builder 前运行对应准备器，并在打包后检查版本、资源定位和后端环境注入。

真实 Windows x64 准备于本机成功完成。官方资产 `opencode-windows-x64.zip` 的 SHA-256 为 `b32618aa3d1415f6e4f473aec248edef25759203fb707d7d968359d86d4a35ee`；解出的 `opencode.exe` SHA-256 为 `88d2fa691b2d9e32fde6d1039382a850ddf96fe49cd41683c6375fe1dc8ec2a5`，与此前完成匿名免费模型及 MCP 验收的本机受管 1.18.29 可执行文件完全一致。`--version` 返回 `1.18.29`，Electron 资源验证器返回该 bundle 的绝对路径；随后缓存复验约 0.31 秒。

本轮定向验证结果：准备器与桌面打包契约 Python 测试 10 项通过，Node 运行时测试 7 项通过，Ruff、Prettier、项目约束检查和前端生产构建通过。测试覆盖 ZIP 链接、重复和错误成员、Linux TAR.GZ 提取、归档篡改保留旧 bundle、下载超时保留旧 bundle、Windows 精确进程树终止、错平台、错发布资产、损坏许可证、错误可执行格式、额外文件及禁止 PATH/网络回退。完整桌面打包测试文件另有 55 项通过，唯一失败是工作区既有的 Codex 第三方许可证报告测试仍保存旧哈希；当前 Codex 准备器锁定的哈希与文件一致，本轮没有改动该独立问题。

本机还使用冻结后端、Codex 和 OpenCode 三项真实构建资源生成了独立的 Windows `win-unpacked` 目录。由于 electron-builder 在本机下载后的 Electron 临时目录重命名持续收到 Windows EPERM，验收改用项目已经安装的同版本 Electron 39.8.10 分发，随后打包成功。复制后的 `app.asar`、后端、Codex 和 OpenCode 均存在；OpenCode 源文件与打包后文件 SHA-256 相同，资源验证器通过，Codex 返回 `codex-cli 0.149.0`，OpenCode 返回 `1.18.29`，冻结后端使用首次启动物化的配置与资源启动并通过 `/readyz`。官方 Codex 和 OpenCode 可执行文件的 Authenticode 状态为 `Valid`；本机生成的 Echo 外壳和冻结后端为 `NotSigned`，因此这个目录只是本地打包验收，不是正式发布物。

早期曾尝试 npm 平台包，两次下载都在本机网络层长期保持零字节，因此改用官方 GitHub release 的不可变资产与 GitHub 公布摘要。早期尝试留下两个位于忽略构建目录中的零字节暂存目录；它们不进入资源清单或安装包。本记录证明准备、资源校验、electron-builder 复制及真实 Windows 后端启动可用；最终签名安装包仍以发布 CI 的平台签名与安装验收为准。
