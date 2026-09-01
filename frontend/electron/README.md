# Electron 桌面壳

## MCP OAuth 回调

以 `octopus-mcp-oauth` 窗口名打开的 OAuth 请求会留在隔离的桌面弹窗中。
标准 HTTP 回调按原流程处理；通达信这类把授权结果返回到 `workbuddy://` 的
服务商，由主进程仅在服务商精确 HTTPS 授权路径下接收，校验 state 和回调载荷后
转入现有 loopback PKCE 回调。主框架、重定向、子框架和新窗口共用同一条单飞
桥接链路，授权码与完整回调地址不会写入日志。

> 2026-06-13 重建。原 `frontend/electron/` 从未进入 git(`git log --all -- frontend/electron`
> 为空),在本地清理中丢失。本次按 `src/types/electron.d.ts` 留存的完整契约重写。

## 运行

```bash
pnpm electron:dev    # 启动 Vite(:3000)并在就绪后拉起 Electron
pnpm electron        # 仅拉起 Electron(假定 dev server 已在运行)
```

后端默认 `http://127.0.0.1:8000`,可用 `OCTOPUS_BACKEND_URL` 覆盖;
桌面壳只接受无凭据、无额外路径的 loopback HTTP(S) origin(`127.0.0.1`、
`localhost`、`::1`),远端或伪装 host 会在创建窗口前 fail-closed。
前端地址可用 `ELECTRON_START_URL` 覆盖(默认 `http://127.0.0.1:3000`)。

## 打包渲染源

- 正式包和 Electron 冒烟使用固定安全源 `octopus-app://app/index.html`,不使用
  `file://` / `loadFile`,也不关闭 Chromium `webSecurity`。
- 自定义协议仅从随包 `dist` 读取静态文件(含 realpath 边界校验),并只把
  `/api`、`/v1`、`/media`、`/.well-known`、`/.a2a` 转发到上述固定 loopback
  后端。因此 `/community/*`、原生 `/api/*` 与 `/api/plugins/*` 都具有正常同源语义,
  不需要通配 CORS。
- WebSocket 无法通过自定义 HTTP 协议升级;renderer 仅为 realtime/terminal/
  tentacle/team-room WebSocket 使用 preload 注入的 loopback transport URL。

## 实现状态(对照 electron.d.ts)

| 命名空间                                                                                       | 状态                                                           |
| ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `app` / `dialog` / `window` / `backend.getBaseURL`                                             | ✅ 完整                                                        |
| `desktop`(桌面助手:列举/打开/分类移动/批量/撤销/系统信息 + items-changed 监听)                 | ✅ 完整                                                        |
| `browser`(导航/JS/截图/取文/click/type/hover/scroll/waitFor/pressKey/ariaTree/清站点数据/下载) | ✅ 完整(ariaTree 走 CDP)                                       |
| `extensions`(list/installFromFolder/setEnabled/remove)                                         | ✅ 基本(Electron loadExtension 的 API 子集限制)                |
| `on` 八个事件通道                                                                              | ✅ 已接线(`app:update-downloaded` 已接 electron-updater,见下)  |
| `desktop.installContextMenu`(Windows 右键菜单)                                                 | ✅ Windows 注册 "Open with Octopus" 壳菜单;非 Windows 诚实降级 |
| `backend.restart`(打包模式重启子进程)                                                          | ✅ 打包模式 kill+respawn 后端子进程;dev 模式独立运行降级       |

## 自动更新(electron-updater)

- 打包模式下 main.cjs 惰性加载 `electron-updater`。未安装时自动降级为
  "disable",不崩溃;安装:`pnpm add -D electron-updater`。
- 更新源(body 由 `packaging/desktop/build.yml` 的 `publish` 决定):GitHub
  Releases 或自托管 generic,目前未配置(见 build.yml 注释示例)。
- 触发:`window.octopus.app.checkForUpdate()` → `check-for-update` IPC →
  下载完成后向渲染进程发送 `app:update-downloaded`(此前该通道"无触发源")。
  下载完成后可调用 `window.octopus.app.installUpdate()` 退出安装。

## 打包(electron-builder)

- 唯一发布壳是 `frontend/electron/`，配置为 `packaging/desktop/build.yml`；
  `extras/desktop/electron/` 已退役，不得直接产出安装包。
- 当前生产打包仅支持 Windows x64。CI 先用 PyInstaller 生成
  `extras/desktop/build/backend/octopus-backend.exe`，再从 pnpm 锁定的官方
  `@openai/codex@0.149.0` Windows 平台包生成 `extras/desktop/build/codex/`，
  最后从 `frontend/` 执行 `pnpm electron:build:win`。macOS/Linux 在拥有对应的
  随包后端前明确拒绝发布。
- 正式构建只从受保护的 `windows-code-signing` Environment 注入 base64 PKCS#12 与密码；
  缺任一 secret、证书无私钥/Code Signing EKU、签名或可信 RFC3161 时间戳无效都会停止。
  安装器文件名和两个 GitHub artifact 名均携带完整 `github.sha`，并生成
  `SHA256SUMS` 与逐文件签名证明。
- 打包模式只启动 `resources/backend/octopus-backend.exe`，并只允许后端使用
  Electron 注入的绝对路径 `resources/codex/bin/codex.exe`。任一文件缺失时首启
  fail-closed，不回退到系统 Python/uv/Codex/PATH，不在运行时下载依赖。
- 随包能力在 PyInstaller 构建时固定；不在用户设备上在线安装可选依赖。
- 首启会把 agents/prompts/protocols/skills.lock 种入 `userData/resources`。后续版本只补
  不存在的路径，不覆盖同名的用户安装/修改内容；需要采用新版内置资源时，先备份
  userData，再显式删除或迁移目标路径后重启应用。
- 升级继续使用旧壳的 `userData/config.yaml`。首启物化器会为新安装
  生成独立高熵 JWT secret，也会原子轮换旧安装的弱 secret。

## 已知边界

- `electron-builder` / `electron-updater` / `@openai/codex` 已由
  `frontend/package.json` 和 `frontend/pnpm-lock.yaml` 锁定。打包时
  `config.desktop.yaml`、只读资源、Windows 后端与 Codex 原生运行时由 build.yml 的
  `extraResources` 放入应用。
- `webview` 标签已启用(workspace 内嵌浏览器依赖它)。
- 安全基线:contextIsolation 开、nodeIntegration 关、主窗口只允许固定应用入口导航。
  HTTP(S)/mailto 外链交给系统浏览器;应用源内的新窗口使用无 preload、sandbox 开启的
  隔离 BrowserWindow。
