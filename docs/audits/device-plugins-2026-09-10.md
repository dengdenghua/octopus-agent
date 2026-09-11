# 手机能力插件化

- echo-android：30 项 Android 工具定义，需 Echo Android 客户端连接。
- echo-ios：13 项 iOS 工具定义，需已配置的 WebDriverAgent。
- 插件源码：extensions/codex-plugins/echo-android 和 echo-ios。工具放在 tool-manifests，不作为独立市场 Skills 投影。
- 开发版市场加入两个按需安装入口，沿用 CloudCatalog 安装、权限启用和卸载机制；源代码工作区支持本地安装，正式发行版仍要求受信签名包。
- 设备工具加载器仅使用已安装、已启用且通过包完整性/生产签名校验的插件。设备执行和 MCP 工具枚举实时检查启用状态；未安装、禁用、卸载时返回空能力列表。
- 原 runtime/tentacle 下的定义作为手机客户端构建/导出源码保留，不再作为宿主默认运行时入口。公共 Skills 列表排除 android.* 和 ios.*，本地对外显示 43 项。
- 两个归档及 SHA-256 位于 .codex-run/device-plugin-release/；状态 prepared_not_published。现有 build-plugin-store.py / build-cloud-bundles.py 会收录 extensions/codex-plugins 下的包进入正式签名发布链。
- 43 项测试通过（设备插件生命周期、库存和签名包校验）。未连接真机验证操作。
- 通用 Codex manifest 验证器不接受 Echo 专用 octopus 元数据；本项目 marketplace_package 验证已通过。

云端发布尚未完成：需要既有发布身份与仓库凭据。本地可安装不等于已经可以从公网下载。
