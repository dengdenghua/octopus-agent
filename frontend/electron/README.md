# Electron 桌面壳

> 2026-06-13 重建。原 `frontend/electron/` 从未进入 git(`git log --all -- frontend/electron`
> 为空),在本地清理中丢失。本次按 `src/types/electron.d.ts` 留存的完整契约重写。

## 运行

```bash
pnpm electron:dev    # 启动 Vite(:3000)并在就绪后拉起 Electron
pnpm electron        # 仅拉起 Electron(假定 dev server 已在运行)
```

后端默认 `http://127.0.0.1:8000`,可用 `OCTOPUS_BACKEND_URL` 覆盖;
前端地址可用 `ELECTRON_START_URL` 覆盖(默认 `http://127.0.0.1:3000`)。

## 实现状态(对照 electron.d.ts)

| 命名空间                                                                                       | 状态                                                        |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `app` / `dialog` / `window` / `backend.getBaseURL`                                             | ✅ 完整                                                     |
| `desktop`(桌面助手:列举/打开/分类移动/批量/撤销/系统信息 + items-changed 监听)                 | ✅ 完整                                                     |
| `browser`(导航/JS/截图/取文/click/type/hover/scroll/waitFor/pressKey/ariaTree/清站点数据/下载) | ✅ 完整(ariaTree 走 CDP)                                    |
| `extensions`(list/installFromFolder/setEnabled/remove)                                         | ✅ 基本(Electron loadExtension 的 API 子集限制)             |
| `on` 八个事件通道                                                                              | ✅ 已接线(`app:update-downloaded` 已接 electron-updater,见下) |
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

- 配置:`packaging/desktop/build.yml`(需先 `pnpm add -D electron-builder`)。
- 脚本:`pnpm electron:build:mac|win|linux`(`frontend/package.json`)。
- 打包模式行为:main 进程 spawn `python -m runtime serve` 托管后端
  (`extraResources` 携带 `config.desktop.yaml` 与 `runtime/` 到 resources),
  退出时清理子进程。

## 已知边界

- `electron-builder` / `electron-updater` 未安装;打包前需在 `frontend/` 安装
  (`pnpm add -D electron-builder electron-updater`)。打包时
  `config.desktop.yaml` 与 `runtime/` 已由 build.yml 的 `extraResources` 放入 resources。
- `webview` 标签已启用(workspace 内嵌浏览器依赖它)。
- 安全基线:contextIsolation 开、nodeIntegration 关、`window.open` 一律转系统浏览器。
