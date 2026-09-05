# Echo Windows 本地运行

项目目录：`D:\echo agent`。完整 Git 历史已下载，默认分支为 `main`。

## 启动与停止

- 双击根目录 `Start-Echo.cmd`：启动 Python 后端、Vite 前端和 Electron 桌面窗口。
- 浏览器模式：运行 `Start-Echo.cmd -Web`，地址为 http://127.0.0.1:3000 。
- 双击 `Stop-Echo.cmd`：停止这些脚本启动的本地进程。
- `Start-Octopus.cmd` / `Stop-Octopus.cmd` 仍保留为兼容入口。
- 关闭桌面窗口不会停止后端；需要完全退出时使用停止脚本。

登录页可选择“本地登录”，输入自己的用户名。已使用 `local` 验证进入工作台，你也可以使用这个用户名。真实 AI 对话需要在应用中配置模型提供商或登录相应服务；安装过程没有配置 API 密钥或验证付费模型调用。

## 文件与开发环境

本机账号 `123` 已通过 `config.local.yaml` 的 `local_auth.admin_usernames: ["123"]`
配置为本地管理员，可安装工作台插件。其他账号默认仍为 `user/local`。
修改管理员名单后需重启后端并重新登录；名单不会绕过用户名或密码验证。
此配置仅适用于当前本地开发实例。

“自进化”的页面源码已包含在仓库中，但当前云内容包缺少对应工作台包。
已新增本地构建脚本，在项目根目录运行 `node frontend/scripts/build-self-evolution.mjs`，
会生成 `extensions/workbench-apps/self_evolution`。随后在应用中心安装“自进化”，
本地开发模式会使用该目录，并保留安装校验与回滚记录。修改页面源码后需重新构建并安装。
该第一方页面声明 `host.same_origin`，使用现有宿主登录态访问 API。
工作台清单接口会签发一小时有效、仅限对应插件静态资源路径的 HttpOnly Cookie；
长时间停留后如新页面资源无法加载，刷新宿主页面可重新获取凭证。

其他工作台也可使用统一脚本构建：`node frontend/scripts/build-local-workbench.mjs design`，
将 `design` 替换为 `narrative_studio`、`paper-trading`、`intelligence`、`community`
或 `self_evolution`。`node frontend/scripts/build-workbenches.mjs` 会顺序构建全部六个工作台，
也修复了前端已有的 `pnpm build:workbenches` 命令。构建只准备安装包，安装仍由应用中心执行。

项目管理已加入工作台插件，包名为 `projects`，统一构建脚本现在覆盖七个工作台。
项目管理页面通过独立安装包加载；主路由和内嵌浏览器均使用插件加载器。
项目与任务 API、工作目录、权限和数据存储仍由宿主提供，卸载此 UI 包不会移除核心项目记录。
在本机已验证安装、卸载、重新安装后 `/api/projects` 的返回数据保持一致。

OpenCode Zen 插件确认权限后需在应用内填写自己的 API Key，验证成功才启用模型路由。

- Python 3.12 虚拟环境：`.venv`，后端为可编辑安装，修改 Python 源码后重启。
- 前端源码：`frontend/src`；Vite 提供修改即时更新。
- 本地配置：`config.local.yaml`，基于项目桌面模板生成，含本机独立登录签名密钥，已被 Git 忽略。
- 运行数据：`.codex-run/octopus`；日志与进程记录：`.codex-run`。
- Node.js 使用本机 Codex 附带运行时；其路径保存在被忽略的 `.codex-run/runtime-paths.json` 中。换机器后需重新安装依赖并设置 Node.js。
- 后端健康检查：http://127.0.0.1:8000/api/health 。

Codex 按账号、任务隔离的状态目录会超过 Windows 旧的 260 字符限制。本机已于
2026-09-05 将 `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled`
从 `0` 改为 `1`，并验证新 Python 进程支持长路径。换机器安装时，在管理员
PowerShell 中执行下面命令，然后重新启动后端；撤销时将值改回 `0`。

```powershell
Set-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1
```

## 手动开发命令

在项目根目录运行：

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = '1'
$env:OCTOPUS_HOME = Join-Path $PWD '.codex-run\octopus'
python -m runtime serve --config config.local.yaml --host 127.0.0.1 --port 8000
```

另一个终端运行前端：

```powershell
cd frontend
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000 --strictPort
```

在项目根目录打开新终端，构建前端：

```powershell
cd frontend
node node_modules/vite/bin/vite.js build
```

重新同步 Python 依赖：

```powershell
.\.venv\Scripts\uv.exe sync --frozen --inexact --extra dev --extra desktop-core --extra mcp --extra code-intel --extra desktop --extra local-auth
```

前端使用仓库锁文件安装：在 `frontend` 中运行 `pnpm install --frozen-lockfile`。`electron-winstaller` 的可选构建脚本已明确禁用；当前使用 Electron 开发运行方式，尚未生成签名的 Windows 安装包。
